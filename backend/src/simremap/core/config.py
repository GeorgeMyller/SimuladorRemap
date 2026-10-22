"""Configuração da aplicação por variáveis ``SIMREMAP_*`` (platform-foundation RF-04, seção 9).

Regras:
- Prefixo ``SIMREMAP_``; arquivo ``.env`` opcional; ``DATABASE_URL`` sem prefixo é alias.
- Sem ``database_url`` explícito, o banco é ``sqlite+aiosqlite:///<data_dir>/simremap.db``.
- Só os drivers ``sqlite+aiosqlite://`` e ``postgresql+asyncpg://`` são aceites.
- CORS só para ``http://localhost[:porta]`` e ``http://127.0.0.1[:porta]`` (D-32).

Catálogo: ``SIMREMAP_CATALOG_DIR`` (raiz alternativa) e ``SIMREMAP_CATALOG_ALLOW_DRAFTS``
(sem valor: ``true`` em ``dev``/``test``, ``false`` em ``staging``/``prod``).

Feature flags (D-27; rollback sem perda de dados = desligar a flag):
- ``SIMREMAP_FEATURE_DYNO``, ``SIMREMAP_FEATURE_TELEMETRY``, ``SIMREMAP_FEATURE_SCENARIOS``,
  ``SIMREMAP_FEATURE_DEFECT_WASTEGATE``: booleanos (padrão ligado).
- ``ECU_STRATEGIES_ENABLED`` e ``ECU_PROFILES_ENABLED`` (também com prefixo
  ``SIMREMAP_``): lista separada por vírgulas; ausente, ``all`` ou ``*`` = todas
  ativas; vazio = nenhuma. Consulte com ``ecu_strategy_enabled``/``ecu_profile_enabled``.

``worker_mode`` padrão (T409, D-04): ``process``, fixado pelo benchmark T083 com a física
real (``PhysicsOnlyTask``, T408; ``muscle-v8-sc`` a 6000 rpm em plena carga, 1000 Hz, frames
a 50 FPS, 10 s; 2026-10-18, macOS arm64 com 10 núcleos — não é o hardware de referência de
4 núcleos): ``process`` = 1000 Hz (RTF 1,00), ``GET /health`` P95 3,0 ms, lag do event loop
P99 2,1 ms, 2 ticks em overrun; ``thread`` = 1000 Hz, P95 5,7 ms, lag P99 3,1 ms, 73 ticks em
overrun. Os dois cumprem D-04 (P95 < 50 ms, P99 < 20 ms, ≥ 99 % de ``sim_hz``); ``process``
tem folga maior e isola o GIL, logo é o padrão. ``thread`` fica como alternativa explícita
(``SIMREMAP_WORKER_MODE=thread``).
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["ALLOWED_DB_DRIVERS", "WORKER_MODE_DEFAULT", "FeatureList", "Settings", "get_settings"]

WORKER_MODE_DEFAULT: Final[Literal["process", "thread"]] = "process"  # T409: benchmark D-04

ALLOWED_DB_DRIVERS: Final = ("sqlite+aiosqlite://", "postgresql+asyncpg://")
_LOCAL_ORIGIN: Final = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")
_ALL_MARKERS: Final = frozenset({"all", "*"})

FeatureList = Annotated[tuple[str, ...] | None, NoDecode]
"""Lista de nomes ativos (``None`` = todos ativos)."""


def _parse_feature_list(value: Any) -> Any:
    """``"a, b"`` → ``("a", "b")``; ``"all"``/``"*"``/``None`` → ``None``; ``""`` → ``()``."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _ALL_MARKERS:
            return None
        return tuple(part.strip() for part in text.split(",") if part.strip())
    if isinstance(value, list | tuple | set | frozenset):
        items = tuple(str(v).strip() for v in value)
        return None if any(i.lower() in _ALL_MARKERS for i in items) else items
    return value


class Settings(BaseSettings):
    """Configuração imutável lida do ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="SIMREMAP_",
        env_file=".env",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    env: Literal["dev", "test", "staging", "prod"] = "prod"
    app_version: str = Field("0.1.0", pattern=r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    git_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    build_time_utc: datetime | None = None

    data_dir: Path = Path("/data")
    static_dir: Path | None = Path("/app/static")
    # Catálogo (vehicle-catalog RF-01, RF-23): raiz alternativa dos dados e veículos ``draft``
    # em sessões (``None`` = ``true`` em dev/test, ``false`` em staging/prod).
    catalog_dir: Path | None = None
    catalog_allow_drafts: bool | None = None

    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "SIMREMAP_DATABASE_URL", "database_url"),
    )
    db_auto_migrate: bool = True
    db_pool_size: int = Field(5, ge=1, le=20)
    db_connect_retries: int = Field(5, ge=1, le=10)

    redis_url: str | None = None
    cache_max_keys: int = Field(10_000, ge=100, le=1_000_000)

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    bind_public: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_body_bytes: int = Field(16 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)

    sim_hz: int = Field(1000, ge=100, le=1000)
    ws_fps: int = Field(50, ge=30, le=60)
    worker_mode: Literal["process", "thread"] = WORKER_MODE_DEFAULT
    max_active_sessions: int = Field(1, ge=1, le=2)

    # ---------------------------------------------------------------- feature flags (D-27)
    feature_dyno: bool = True
    feature_telemetry: bool = True
    feature_scenarios: bool = True
    feature_defect_wastegate: bool = True
    ecu_strategies_enabled: FeatureList = Field(
        default=None,
        validation_alias=AliasChoices(
            "ECU_STRATEGIES_ENABLED", "SIMREMAP_ECU_STRATEGIES_ENABLED", "ecu_strategies_enabled"
        ),
    )
    ecu_profiles_enabled: FeatureList = Field(
        default=None,
        validation_alias=AliasChoices(
            "ECU_PROFILES_ENABLED", "SIMREMAP_ECU_PROFILES_ENABLED", "ecu_profiles_enabled"
        ),
    )

    @field_validator("ecu_strategies_enabled", "ecu_profiles_enabled", mode="before")
    @classmethod
    def _feature_list(cls, value: Any) -> Any:
        return _parse_feature_list(value)

    @field_validator("git_sha", "build_time_utc", "redis_url", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        """Variáveis vazias (``ARG`` do Docker sem valor) valem como ausentes."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def _driver(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(ALLOWED_DB_DRIVERS):
            raise ValueError("DATABASE_URL deve usar sqlite+aiosqlite ou postgresql+asyncpg")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _localhost_only(cls, value: list[str]) -> list[str]:
        for origin in value:
            if not _LOCAL_ORIGIN.fullmatch(origin):
                raise ValueError(
                    f"origem CORS {origin!r} recusada: só http://localhost ou http://127.0.0.1"
                )
        return value

    @model_validator(mode="after")
    def _default_database_url(self) -> Self:
        if self.database_url is None:
            url = f"sqlite+aiosqlite:///{self.data_dir.as_posix()}/simremap.db"
            # Modelo congelado: o valor derivado é fixado uma única vez na validação.
            self.__dict__["database_url"] = url
        return self

    @property
    def db_url(self) -> str:
        """URL efetiva do banco (nunca ``None`` depois da validação)."""
        if self.database_url is None:  # pragma: no cover - garantido pelo model_validator
            raise RuntimeError("database_url não resolvido")
        return self.database_url

    def ecu_strategy_enabled(self, name: str) -> bool:
        """Estratégia de ECU ativa segundo ``ECU_STRATEGIES_ENABLED`` (ecu-core seção 12)."""
        return self.ecu_strategies_enabled is None or name in self.ecu_strategies_enabled

    def ecu_profile_enabled(self, profile_id: str) -> bool:
        """Perfil de ECU ativo segundo ``ECU_PROFILES_ENABLED`` (ecu-profiles seção 12)."""
        return self.ecu_profiles_enabled is None or profile_id in self.ecu_profiles_enabled

    @property
    def catalog_drafts_allowed(self) -> bool:
        """``SIMREMAP_CATALOG_ALLOW_DRAFTS`` explícito ou, sem ele, ``env`` em dev/test."""
        if self.catalog_allow_drafts is not None:
            return self.catalog_allow_drafts
        return self.env in ("dev", "test")

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite+aiosqlite://")

    @property
    def sqlite_path(self) -> Path | None:
        """Caminho do arquivo SQLite, ou ``None`` para PostgreSQL e ``:memory:``."""
        if not self.is_sqlite:
            return None
        raw = self.db_url.removeprefix("sqlite+aiosqlite:///").split("?", 1)[0]
        if raw in ("", ":memory:"):
            return None
        return Path(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings do processo (cache único). Testes passam ``Settings`` explícito a ``create_app``."""
    return Settings()
