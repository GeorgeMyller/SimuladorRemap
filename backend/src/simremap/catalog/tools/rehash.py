"""Recalcula os SHA-256 do ``manifest.json`` do catálogo (vehicle-catalog RF-24, RF-25).

Uso::

    uv run python -m simremap.catalog.tools.rehash               # diretório padrão
    uv run python -m simremap.catalog.tools.rehash --version 1.1.0
    uv run python -m simremap.catalog.tools.rehash --check       # só verifica (CI)

Passos:
1. Atualiza o ``sha256`` de cada ``factory_calibrations[]`` nos ``vehicle.json`` com o
   hash dos bytes do arquivo de calibração (RF-19).
2. Lista todos os arquivos de dados (exceto ``manifest.json`` e nomes começados por
   ``.``), ordenados por caminho, com o SHA-256 dos bytes.
3. Recusa (saída 2) mudar uma curva do ``Reference Benchmark Baseline v1`` sem subir o
   ``catalog_version`` (``contracts/file-formats.md`` seção 7, regra 4).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from simremap.catalog.canonical import CURVE_PATH_GLOB, sha256_bytes
from simremap.catalog.settings import DEFAULT_CATALOG_DIR
from simremap.catalog.tools.jsonfmt import dumps_pretty, write_json

__all__ = [
    "DEFAULT_CATALOG_DIR",
    "MANIFEST_NAME",
    "RehashError",
    "RehashResult",
    "build_manifest",
    "data_files",
    "main",
    "rehash",
]

MANIFEST_NAME: Final = "manifest.json"
SEMVER: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
EXIT_OUTDATED: Final = 1
EXIT_REFUSED: Final = 2


class RehashError(RuntimeError):
    """Rehash recusado (ex.: curva alterada sem nova versão do catálogo)."""


@dataclass(frozen=True, slots=True)
class RehashResult:
    manifest: dict[str, Any]
    changed_paths: list[str]
    updated_vehicle_files: list[str]
    written: bool


def _semver(version: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(version)
    if match is None:
        raise RehashError(f"catalog_version {version!r} não é SemVer X.Y.Z")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def data_files(root: Path) -> list[str]:
    """Caminhos relativos (com ``/``) dos arquivos de dados, ordenados."""
    paths = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or "__pycache__" in rel.parts:
            continue
        if path.is_file() and rel.as_posix() != MANIFEST_NAME:
            paths.append(rel.as_posix())
    return sorted(paths)


def build_manifest(root: Path, catalog_version: str) -> dict[str, Any]:
    _semver(catalog_version)
    files = [{"path": p, "sha256": sha256_bytes((root / p).read_bytes())} for p in data_files(root)]
    return {"catalog_version": catalog_version, "files": files}


def _update_calibration_refs(root: Path, write: bool) -> list[str]:
    updated: list[str] = []
    for vehicle_file in sorted(root.glob("vehicles/*/vehicle.json")):
        data = json.loads(vehicle_file.read_text(encoding="utf-8"))
        refs = data.get("factory_calibrations") if isinstance(data, dict) else None
        if not isinstance(refs, list):
            continue
        changed = False
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("file"), str):
                continue
            target = vehicle_file.parent / ref["file"]
            if not target.is_file():
                continue
            digest = sha256_bytes(target.read_bytes())
            if ref.get("sha256") != digest:
                ref["sha256"] = digest
                changed = True
        if changed:
            updated.append(vehicle_file.relative_to(root).as_posix())
            if write:
                write_json(vehicle_file, data)
    return updated


def _curve_changes(old: dict[str, str], new: dict[str, str]) -> list[str]:
    keys = {k for k in old.keys() | new.keys() if fnmatch.fnmatchcase(k, CURVE_PATH_GLOB)}
    return sorted(k for k in keys if old.get(k) != new.get(k))


def rehash(
    root: Path = DEFAULT_CATALOG_DIR, version: str | None = None, *, check: bool = False
) -> RehashResult:
    """Recalcula e (sem ``check``) grava o manifesto; devolve o resultado."""
    manifest_path = root / MANIFEST_NAME
    old: dict[str, Any] = {}
    if manifest_path.is_file():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_version = str(old.get("catalog_version", "1.0.0"))
    new_version = version or old_version
    updated = _update_calibration_refs(root, write=not check)
    manifest = build_manifest(root, new_version)
    old_files = {f["path"]: f["sha256"] for f in old.get("files", []) if isinstance(f, dict)}
    new_files = {f["path"]: f["sha256"] for f in manifest["files"]}
    changed = sorted(
        k for k in old_files.keys() | new_files.keys() if old_files.get(k) != new_files.get(k)
    )
    curves = _curve_changes(old_files, new_files)
    if old and curves and _semver(new_version) <= _semver(old_version):
        raise RehashError(
            "curvas do benchmark alteradas sem subir catalog_version: " + ", ".join(curves)
        )
    written = False
    if not check and (changed or new_version != old_version or not old):
        manifest_path.write_text(dumps_pretty(manifest), encoding="utf-8", newline="\n")
        written = True
    return RehashResult(manifest, changed, updated, written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recalcula o manifest.json do catálogo.")
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument("--version", help="novo catalog_version (SemVer)")
    parser.add_argument(
        "--check", action="store_true", help="só verifica; saída 1 se desatualizado"
    )
    args = parser.parse_args(argv)
    try:
        result = rehash(args.catalog_dir, args.version, check=args.check)
    except RehashError as exc:
        print(f"rehash recusado: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if args.check and (result.changed_paths or result.updated_vehicle_files):
        print("manifesto desatualizado: " + ", ".join(result.changed_paths), file=sys.stderr)
        return EXIT_OUTDATED
    print(
        f"manifest.json: {len(result.manifest['files'])} arquivos, "
        f"catalog_version {result.manifest['catalog_version']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
