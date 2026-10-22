"""Registo único de routers (platform-foundation RF-03, D-01, D-33).

Ponto de registo fixo: cada componente expõe ``router: APIRouter`` em
``simremap/<pacote>/router.py`` (lista estática ``COMPONENT_ROUTER_MODULES``).
O módulo pode definir ``TAG = "<componente>"``; sem ``TAG``, vale ``router.tags[0]``
ou o nome do pacote. Toda rota do router tem de começar por ``/api/v1`` (REST) ou
``/ws/v1`` (WebSocket); caso contrário ``create_app`` falha com ``RouterPrefixError``.

Exemplo (``simremap/catalog/router.py``)::

    from fastapi import APIRouter

    TAG = "vehicle-catalog"
    router = APIRouter(prefix="/api/v1", tags=[TAG])

    @router.get("/vehicles")
    async def list_vehicles() -> list[VehicleSummary]: ...
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Final

from fastapi import APIRouter
from starlette.routing import BaseRoute

__all__ = [
    "ALLOWED_PREFIXES",
    "COMPONENT_ROUTER_MODULES",
    "ROUTERS",
    "RouterEntry",
    "RouterPrefixError",
    "RouterRegistryError",
    "collect_routers",
    "register",
    "validate_router",
]

ALLOWED_PREFIXES: Final[tuple[str, ...]] = ("/api/v1", "/ws/v1")

COMPONENT_ROUTER_MODULES: Final[tuple[str, ...]] = (
    "simremap.api.health",
    "simremap.catalog.router",
    "simremap.dyno.router",
    "simremap.damage.router",
    "simremap.ecu.router",
    "simremap.profiles.router",
    "simremap.telemetry.router",
    "simremap.scenarios.router",
    "simremap.career.router",
    "simremap.ai.router",
)

RouterEntry = tuple[str, APIRouter]
"""(tag OpenAPI do componente, router com rotas sob ``/api/v1`` ou ``/ws/v1``)."""

ROUTERS: list[RouterEntry] = []
"""Registos extra feitos por ``register`` (ex.: testes); somados aos módulos fixos."""


class RouterRegistryError(RuntimeError):
    """Erro de configuração do registo de routers."""


class RouterPrefixError(RouterRegistryError):
    """Rota fora de ``/api/v1`` e ``/ws/v1``."""


def _iter_paths(routes: list[BaseRoute], base: str = "") -> Iterator[str]:
    """Caminhos completos das rotas, incluindo sub-routers (``_IncludedRouter`` do FastAPI)."""
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            yield base + path
            continue
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if isinstance(original, APIRouter) and context is not None:
            yield from _iter_paths(list(original.routes), base + str(context.prefix))
            continue
        raise RouterRegistryError(f"rota sem caminho: {route!r}")


def _allowed(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ALLOWED_PREFIXES)


def validate_router(router: APIRouter, origin: str = "<router>") -> None:
    """Recusa (``RouterPrefixError``) qualquer rota fora dos prefixos permitidos."""
    if router.prefix and not _allowed(router.prefix):
        raise RouterPrefixError(
            f"{origin}: prefixo {router.prefix!r} fora de {', '.join(ALLOWED_PREFIXES)}"
        )
    for path in _iter_paths(list(router.routes)):
        if not _allowed(path):
            raise RouterPrefixError(
                f"{origin}: rota {path!r} fora de {', '.join(ALLOWED_PREFIXES)}"
            )


def register(tag: str, router: APIRouter) -> None:
    """Regista um router extra; valida prefixo e recusa tag duplicada."""
    validate_router(router, origin=tag)
    if any(existing == tag for existing, _ in ROUTERS):
        raise RouterRegistryError(f"tag {tag!r} já registada")
    ROUTERS.append((tag, router))


def _default_tag(module_name: str, router: APIRouter) -> str:
    if router.tags:
        return str(router.tags[0])
    parts = module_name.split(".")
    return parts[1] if len(parts) > 1 else module_name


def collect_routers(
    modules: tuple[str, ...] = COMPONENT_ROUTER_MODULES,
) -> list[RouterEntry]:
    """Importa ``router`` de cada módulo existente, valida e devolve ``(tag, router)``.

    Módulo ausente é ignorado (componente ainda não implementado). Módulo presente sem
    atributo ``router`` do tipo ``APIRouter`` lança ``RouterRegistryError``; tags
    duplicadas também.
    """
    entries: list[RouterEntry] = []
    for name in modules:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing == name or name.startswith(missing + "."):
                continue
            raise
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            raise RouterRegistryError(f"{name} não expõe 'router: APIRouter'")
        validate_router(router, origin=name)
        tag = getattr(module, "TAG", None)
        entries.append((tag if isinstance(tag, str) else _default_tag(name, router), router))
    entries.extend(ROUTERS)
    tags = [tag for tag, _ in entries]
    duplicated = sorted({tag for tag in tags if tags.count(tag) > 1})
    if duplicated:
        raise RouterRegistryError(f"tags de router duplicadas: {duplicated}")
    return entries
