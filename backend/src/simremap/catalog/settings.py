"""Variáveis de ambiente do catálogo (vehicle-catalog RF-01, RF-23; seção 13).

- ``SIMREMAP_CATALOG_DIR``: raiz alternativa dos dados (padrão: ``catalog/data/`` do pacote).
- ``SIMREMAP_CATALOG_ALLOW_DRAFTS``: aceita veículos ``draft`` em ``get_for_session``.
  Sem valor explícito, vale ``true`` em ``dev``/``test`` e ``false`` em ``staging``/``prod``
  (``SIMREMAP_ENV``).

O ``Settings`` da fundação tem os mesmos campos (``catalog_dir``, ``catalog_allow_drafts``),
usados no arranque (``startup_catalog(settings)``); esta classe serve a carga sob demanda
(``get_catalog()`` sem lifespan, ex.: testes e ferramentas), com o mesmo prefixo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DEFAULT_CATALOG_DIR", "CatalogSettings", "drafts_allowed"]

DEFAULT_CATALOG_DIR: Final = Path(__file__).resolve().parent / "data"
_DRAFT_ENVS: Final = frozenset({"dev", "test"})


class CatalogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMREMAP_", extra="ignore", frozen=True)

    env: Literal["dev", "test", "staging", "prod"] = "prod"
    catalog_dir: Path | None = None
    catalog_allow_drafts: bool | None = None

    @property
    def resolved_dir(self) -> Path:
        return self.catalog_dir if self.catalog_dir is not None else DEFAULT_CATALOG_DIR

    def allow_drafts(self, env: str | None = None) -> bool:
        """Flag explícita ou, sem ela, ``env`` (ou ``SIMREMAP_ENV``) em ``dev``/``test``."""
        if self.catalog_allow_drafts is not None:
            return self.catalog_allow_drafts
        return (env or self.env) in _DRAFT_ENVS


def drafts_allowed(env: str | None = None) -> bool:
    return CatalogSettings().allow_drafts(env)
