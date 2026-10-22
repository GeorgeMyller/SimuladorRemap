"""Factory da aplicação FastAPI (platform-foundation RF-02, RF-03, RF-05; T239, T448, T449).

Ordem de startup (eventos ``startup.<etapa>``): ``settings`` (logging JSON) →
``database`` (engine + ligação com retry) → ``migrations`` (backup + ``upgrade head``
com ``SIMREMAP_DB_AUTO_MIGRATE``) → ``seeds`` → ``cache`` → ``catalog`` (carga e
validação do catálogo de veículos) → ``worker_host`` → ``routers`` → ``complete``. Os
lifespans dos routers dos componentes (seeds de calibrações de série, cenários base,
instalação do dyno e da telemetria) correm depois, dentro do ``yield`` desta etapa.
Shutdown na ordem inversa: ``worker_host`` (stop + join
5 s) → ``cache`` → ``database`` (dispose).

Banco indisponível no arranque (EC-01): 5 tentativas com backoff 0,5/1/2/4/8 s; depois
``startup.failed`` com ``code = DATABASE_UNAVAILABLE`` e ``StartupError(exit_code=3)``
(o uvicorn termina com código 3 e o Docker reinicia o container). Catálogo inválido
(vehicle-catalog RF-01): ``startup.failed`` com ``code = CATALOG_INVALID`` e saída com
código 4. ``Settings`` inválido ao criar ``simremap.api.main:app`` (EC-08):
``startup.invalid_settings`` e saída com código 2. O código da última falha de arranque
fica em ``last_startup_exit_code()`` (lido por ``simremap.api.serve``).

``app.state`` guarda: ``settings``, ``engine``, ``sessionmaker``, ``cache``, ``catalog``,
``worker_host``, ``router_tags``, ``static_available``, ``install_id`` e
``started_at_monotonic``. Execução: ``uvicorn simremap.api.main:app``.

Equivalência com o actions.md: T239/T448/T449 citam ``api/app.py``; o módulo da
factory é este ``api/main.py`` (layout da spec seção 8).
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final

from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simremap import __version__
from simremap.api.middleware import enforce_declared_body_limit, install_middlewares
from simremap.api.problems import install_problem_handlers
from simremap.api.registry import collect_routers
from simremap.api.static import install_static
from simremap.catalog.errors import CatalogInvalid
from simremap.catalog.service import CatalogService, startup_catalog
from simremap.core.cache import build_cache
from simremap.core.config import Settings, get_settings
from simremap.core.errors import ProblemDetail, load_component_errors
from simremap.core.logging import configure_logging, get_logger
from simremap.core.versions import API_VERSION
from simremap.core.worker.host import SimWorkerHost
from simremap.db.engine import build_engine, build_sessionmaker
from simremap.db.migrate import migrate_on_startup
from simremap.db.seeds import has_app_meta, seed_app_meta

__all__ = [
    "DB_RETRY_DELAYS_S",
    "EXIT_CATALOG_INVALID",
    "OPENAPI_TAG_DESCRIPTIONS",
    "StartupError",
    "create_app",
    "last_startup_exit_code",
]

logger = get_logger("simremap.api")

DB_RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)
"""Espera após cada tentativa falhada de ligação ao banco (5 tentativas, EC-01)."""

_DB_PROBE_TIMEOUT_S: Final = 5.0
EXIT_DATABASE_UNAVAILABLE: Final = 3
EXIT_INVALID_SETTINGS: Final = 2
EXIT_CATALOG_INVALID: Final = 4
_LAST_STARTUP_EXIT: list[int] = []

OPENAPI_TAG_DESCRIPTIONS: Final[dict[str, str]] = {
    "platform": "Fundação: health, versões e infraestrutura comum (platform-foundation).",
    "vehicle-catalog": "Catálogo de veículos validados e curvas de referência.",
    "dyno-bench": "Sessões de simulação e puxadas no dinamômetro.",
    "knock-and-failure-model": "Saúde do motor, restauração e laudo forense.",
    "ecu-core": "Calibrações versionadas, tabelas e aplicação na sessão.",
    "ecu-profiles": "Perfis de ECU, troca para standalone e setup base.",
    "telemetry-datalogger": "Canais de telemetria, datalogs e WebSocket.",
    "training-scenarios": "Perfis locais, cenários, tentativas, avaliação e pacotes.",
    "ai-tuning": "Otimização autônoma de calibração via LAYA.ai.",
}


class StartupError(RuntimeError):
    """Falha fatal no arranque com código de saída do processo e ``code`` do catálogo."""

    def __init__(self, message: str, *, code: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def last_startup_exit_code() -> int | None:
    """Código de saída da última ``StartupError`` do processo (``None`` sem falha)."""
    return _LAST_STARTUP_EXIT[-1] if _LAST_STARTUP_EXIT else None


def _load_catalog(settings: Settings) -> CatalogService:
    """Etapa ``startup.catalog``: ``CatalogInvalid`` vira ``StartupError`` (saída 4)."""
    try:
        return startup_catalog(settings)
    except CatalogInvalid as exc:
        raise StartupError(str(exc), code="CATALOG_INVALID", exit_code=int(exc.exit_code)) from exc


async def _probe_database(engine: AsyncEngine) -> None:
    async with asyncio.timeout(_DB_PROBE_TIMEOUT_S), engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def connect_with_retry(
    engine: AsyncEngine,
    attempts: int,
    delays: tuple[float, ...] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Liga ao banco com backoff; devolve o nº de tentativas ou lança ``StartupError``."""
    waits = DB_RETRY_DELAYS_S if delays is None else delays
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            await _probe_database(engine)
        except Exception as exc:
            last = exc
            logger.warning(
                "startup.database_retry",
                attempt=attempt,
                attempts=attempts,
                reason=type(exc).__name__,
            )
            if attempt < attempts:
                await sleep(waits[min(attempt - 1, len(waits) - 1)])
            continue
        return attempt
    logger.error(
        "startup.failed",
        code="DATABASE_UNAVAILABLE",
        attempts=attempts,
        reason=type(last).__name__ if last else None,
        exit_code=EXIT_DATABASE_UNAVAILABLE,
    )
    raise StartupError(
        f"Banco de dados indisponível após {attempts} tentativas.",
        code="DATABASE_UNAVAILABLE",
        exit_code=EXIT_DATABASE_UNAVAILABLE,
    )


async def _migrate_and_seed(app: FastAPI, engine: AsyncEngine, settings: Settings) -> None:
    """Etapas ``startup.migrations`` e ``startup.seeds``."""
    if settings.db_auto_migrate:
        result = await migrate_on_startup(engine, settings)
        logger.info(
            "startup.migrations",
            applied=result.applied,
            head=result.head,
            backup=result.backup.name if result.backup else None,
        )
    if await has_app_meta(engine):
        seed = await seed_app_meta(app.state.sessionmaker, settings.app_version)
        app.state.install_id = seed.install_id
        logger.info("startup.seeds", first_boot=seed.created)
    else:
        app.state.install_id = None
        logger.warning("startup.seeds_skipped", reason="app_meta ausente (sem migração)")


def _make_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        logger.info("startup.settings", env=settings.env, worker_mode=settings.worker_mode)
        if settings.bind_public:
            logger.warning("startup.bind_public", detail="porta publicada fora de 127.0.0.1")

        engine = build_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = build_sessionmaker(engine)
        cache = None
        host: SimWorkerHost | None = None
        try:
            attempts = await connect_with_retry(engine, settings.db_connect_retries)
            logger.info("startup.database", sqlite=settings.is_sqlite, attempts=attempts)

            await _migrate_and_seed(app, engine, settings)

            cache = build_cache(settings)
            app.state.cache = cache
            logger.info("startup.cache", backend=cache.backend)

            app.state.catalog = _load_catalog(settings)

            host = SimWorkerHost.from_settings(settings)
            await host.start()
            app.state.worker_host = host
            logger.info("startup.worker_host", mode=host.mode)

            logger.info("startup.routers", tags=app.state.router_tags)
            app.state.started_at_monotonic = time.monotonic()
            logger.info("startup.complete", app_version=settings.app_version)
        except BaseException as exc:
            if isinstance(exc, StartupError):
                _LAST_STARTUP_EXIT.append(exc.exit_code)
            if host is not None:
                await host.stop()
            if cache is not None:
                await cache.close()
            await engine.dispose()
            raise

        try:
            yield
        finally:
            await host.stop()
            logger.info("shutdown.worker_host")
            await cache.close()
            logger.info("shutdown.cache")
            await engine.dispose()
            logger.info("shutdown.database")

    return lifespan


def _openapi_tags(tags: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tag in tags:
        entry: dict[str, Any] = {"name": tag}
        description = OPENAPI_TAG_DESCRIPTIONS.get(tag)
        if description:
            entry["description"] = description
        result.append(entry)
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    """Cria a app; lança ``RouterPrefixError`` se algum router sair de ``/api/v1``/``/ws/v1``."""
    settings = settings or get_settings()
    load_component_errors()
    entries = collect_routers()
    tags = [tag for tag, _ in entries]
    docs = settings.env in ("dev", "test")

    app = FastAPI(
        title="SimuladorRemap API",
        version=API_VERSION,
        summary="Simulador de remap automotivo em dinamômetro (API v1).",
        description=(
            "API REST local-first do SimuladorRemap. Todas as rotas usam o prefixo "
            "`/api/v1/` (WebSocket em `/ws/v1/`); todo erro é `application/problem+json` "
            f"(RFC 7807) com `code` estável. Versão da aplicação: {__version__}."
        ),
        lifespan=_make_lifespan(settings),
        dependencies=[Depends(enforce_declared_body_limit)],
        openapi_tags=_openapi_tags(tags),
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        responses={
            "default": {"model": ProblemDetail, "description": "Erro (application/problem+json)"}
        },
    )
    app.state.settings = settings
    app.state.router_tags = tags
    install_problem_handlers(app)
    for tag, router in entries:
        app.include_router(router, tags=[tag] if tag not in router.tags else None)
    app.state.static_available = install_static(app, settings.static_dir)
    install_middlewares(app, settings)
    return app


def _create_default_app() -> FastAPI:
    try:
        settings = get_settings()
    except ValidationError as exc:
        configure_logging("INFO")
        logger.error(
            "startup.invalid_settings",
            errors=[
                {"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg")}
                for err in exc.errors()
            ],
            exit_code=EXIT_INVALID_SETTINGS,
        )
        sys.exit(EXIT_INVALID_SETTINGS)
    # Logging JSON antes de o servidor emitir as primeiras linhas (RF-13: 100 % JSON).
    configure_logging(settings.log_level)
    return create_app(settings)


def __getattr__(name: str) -> FastAPI:
    """``simremap.api.main:app`` criado sob demanda (evita ler o ambiente no import)."""
    if name == "app":
        instance = _create_default_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(name)
