"""Fixtures do pacote ``catalog``: cópia editável dos dados e serviço carregado."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from simremap.catalog import loader as loader_module
from simremap.catalog.loader import Catalog, load_catalog_data
from simremap.catalog.service import CatalogService, reset_catalog
from simremap.catalog.settings import DEFAULT_CATALOG_DIR
from simremap.catalog.tools.jsonfmt import write_json
from simremap.catalog.tools.rehash import rehash


@dataclass
class CatalogCopy:
    """Cópia dos dados do pacote num diretório temporário."""

    root: Path

    def read(self, rel: str) -> Any:
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def write(self, rel: str, data: Any) -> None:
        write_json(self.root / rel, data)

    def edit(self, rel: str, fn: Callable[[Any], None], *, rehash_after: bool = True) -> None:
        data = self.read(rel)
        fn(data)
        self.write(rel, data)
        if rehash_after:
            self.rehash()

    def rehash(self, version: str | None = None) -> None:
        current = self.read("manifest.json")["catalog_version"]
        if version is None:
            major, minor, patch = (int(p) for p in current.split("."))
            version = f"{major}.{minor}.{patch + 1}"
        rehash(self.root, version)

    def load(self, **kwargs: Any) -> Catalog:
        return load_catalog_data(self.root, **kwargs)


@pytest.fixture(autouse=True)
def _isolate_catalog_state() -> Iterator[None]:
    """Cada teste começa sem serviço global e sem validadores de calibração."""
    reset_catalog()
    saved = list(loader_module._CALIBRATION_VALIDATORS)
    loader_module._CALIBRATION_VALIDATORS.clear()
    yield
    reset_catalog()
    loader_module._CALIBRATION_VALIDATORS[:] = saved


@pytest.fixture
def catalog_copy(tmp_path: Path) -> CatalogCopy:
    target = tmp_path / "catalog"
    shutil.copytree(DEFAULT_CATALOG_DIR, target, ignore=shutil.ignore_patterns(".*"))
    return CatalogCopy(target)


@pytest.fixture(scope="session")
def real_catalog() -> Catalog:
    return load_catalog_data()


@pytest.fixture
def service(real_catalog: Catalog) -> CatalogService:
    return CatalogService(real_catalog, allow_drafts=False)
