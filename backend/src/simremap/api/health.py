"""Router da fundação: ``GET /api/v1/health`` e ``GET /api/v1/version`` (RF-07, RF-08; T238).

Equivalência com o actions.md: T238 cita ``api/routers/system.py``; o router da
fundação é este ``api/health.py`` (layout da spec seção 8).

Health:
- ``database``: ``SELECT 1`` com timeout de 1 s (``down`` ⇒ 503 ``SERVICE_UNAVAILABLE``).
- ``redis``: ``disabled`` sem ``SIMREMAP_REDIS_URL``; senão ``PING`` com timeout de 0,5 s
  pelo ``KeyValueCache`` da app (``app.state.cache.check()``), que passa a memória se falhar.
- ``sim_worker``: ``app.state.worker_host.health()`` quando existir (``HealthCheck``);
  sem host (worker ainda não integrado) ⇒ ``ok`` com 0 sessões.
Estado agregado: ``down`` se ``database = down``; ``degraded`` se ``redis`` ou
``sim_worker`` = ``down``; senão ``ok``.

Version: ``native_enabled``/``native_version`` dizem se a extensão ``simremap_rs`` está ativa
neste processo (o worker resolve a mesma ``SIMREMAP_NATIVE``).
"""

from __future__ import annotations

import asyncio
import platform
import time
from datetime import datetime
from typing import Any, Final, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from simremap.core.config import Settings
from simremap.core.errors import SimRemapError, catalog_sha256
from simremap.core.native import native_enabled, native_version
from simremap.core.versions import (
    API_VERSION,
    DATALOG_FORMAT_VERSION,
    PACKAGE_FORMAT_VERSION,
    WS_ENVELOPE_VERSION,
    alembic_head,
)

__all__ = ["TAG", "HealthCheck", "HealthStatus", "VersionInfo", "router"]

TAG: Final = "platform"
router = APIRouter(prefix="/api/v1", tags=[TAG])

CheckStatus = Literal["ok", "down", "disabled"]
_DB_TIMEOUT_S: Final = 3.0
_REDIS_TIMEOUT_S: Final = 0.5


class HealthCheck(BaseModel):
    status: CheckStatus
    latency_ms: float | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=200)


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checks: dict[str, HealthCheck]
    uptime_s: float = Field(..., ge=0)
    active_sessions: int = Field(..., ge=0)


class VersionInfo(BaseModel):
    app_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    api_version: Literal["v1"] = "v1"
    ws_envelope_version: Literal[1] = 1
    package_format_version: int = Field(1, ge=1)
    datalog_format_version: int = Field(1, ge=1)
    alembic_head: str
    error_catalog_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    git_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    build_time_utc: datetime | None = None
    python_version: str
    native_enabled: bool = False  # extensão simremap_rs ativa (feature 003, SIMREMAP_NATIVE)
    native_version: str | None = Field(default=None, max_length=64)  # None ⇒ fallback Python


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


async def _check_database(engine: AsyncEngine | None) -> HealthCheck:
    if engine is None:
        return HealthCheck(status="down", detail="engine de banco não inicializado")
    start = time.perf_counter()
    try:
        async with asyncio.timeout(_DB_TIMEOUT_S), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except TimeoutError:
        return HealthCheck(status="down", latency_ms=_elapsed_ms(start), detail="timeout de 1 s")
    except Exception as exc:  # qualquer falha do driver ⇒ banco em baixo
        return HealthCheck(
            status="down", latency_ms=_elapsed_ms(start), detail=type(exc).__name__[:200]
        )
    return HealthCheck(status="ok", latency_ms=_elapsed_ms(start))


async def _check_redis(settings: Settings, cache: Any = None) -> HealthCheck:
    if not settings.redis_url:
        return HealthCheck(status="disabled")
    check = getattr(cache, "check", None)
    if callable(check):
        status, latency, detail = await check()
        return HealthCheck(status=status, latency_ms=latency, detail=detail)
    from redis.asyncio import Redis  # noqa: PLC0415 - import só quando Redis está configurado

    start = time.perf_counter()
    client: Redis = Redis.from_url(settings.redis_url, socket_timeout=_REDIS_TIMEOUT_S)
    try:
        async with asyncio.timeout(_REDIS_TIMEOUT_S):
            await client.ping()
    except Exception as exc:  # qualquer falha ⇒ degraded
        return HealthCheck(
            status="down", latency_ms=_elapsed_ms(start), detail=type(exc).__name__[:200]
        )
    finally:
        await client.aclose()
    return HealthCheck(status="ok", latency_ms=_elapsed_ms(start))


def _check_worker(state: Any) -> tuple[HealthCheck, int]:
    host = getattr(state, "worker_host", None)
    if host is None:
        return HealthCheck(status="ok", detail="0 sessões ativas"), 0
    check = host.health()
    active = int(getattr(host, "active_sessions", 0))
    if not isinstance(check, HealthCheck):
        check = HealthCheck.model_validate(check)
    return check, active


@router.get("/health", response_model=HealthStatus, summary="Estado agregado do serviço")
async def get_health(request: Request) -> HealthStatus:
    state = request.app.state
    settings: Settings = state.settings
    database, redis = await asyncio.gather(
        _check_database(getattr(state, "engine", None)),
        _check_redis(settings, getattr(state, "cache", None)),
    )
    worker, active = _check_worker(state)
    checks = {"database": database, "redis": redis, "sim_worker": worker}
    started = float(getattr(state, "started_at_monotonic", time.monotonic()))
    uptime = max(0.0, time.monotonic() - started)
    if database.status == "down":
        raise SimRemapError(
            "O banco de dados não responde; o serviço está em baixo.",
            code="SERVICE_UNAVAILABLE",
            checks={k: v.model_dump(exclude_none=True) for k, v in checks.items()},
        )
    status: Literal["ok", "degraded"] = (
        "degraded" if "down" in (redis.status, worker.status) else "ok"
    )
    return HealthStatus(status=status, checks=checks, uptime_s=uptime, active_sessions=active)


@router.get("/version", response_model=VersionInfo, summary="Versões da aplicação e formatos")
async def get_version(request: Request) -> VersionInfo:
    settings: Settings = request.app.state.settings
    return VersionInfo(
        app_version=settings.app_version,
        api_version=API_VERSION,
        ws_envelope_version=WS_ENVELOPE_VERSION,
        package_format_version=PACKAGE_FORMAT_VERSION,
        datalog_format_version=DATALOG_FORMAT_VERSION,
        alembic_head=alembic_head(),
        error_catalog_sha256=catalog_sha256(),
        git_sha=settings.git_sha,
        build_time_utc=settings.build_time_utc,
        python_version=platform.python_version(),
        native_enabled=native_enabled(),
        native_version=native_version(),
    )
