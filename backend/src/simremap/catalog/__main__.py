"""Valida o catálogo fora do servidor: ``python -m simremap.catalog [--catalog-dir D]``.

Saída 0 com o resumo em JSON quando o catálogo é válido; saída 4 (``CATALOG_INVALID``)
com a lista de erros (arquivo, ponteiro JSON, subcódigo e mensagem) em caso contrário.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from simremap.catalog.errors import CatalogInvalid
from simremap.catalog.loader import load_catalog_data
from simremap.catalog.settings import CatalogSettings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida o catálogo de veículos.")
    parser.add_argument("--catalog-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.catalog_dir or CatalogSettings().resolved_dir
    try:
        catalog = load_catalog_data(root)
    except CatalogInvalid as exc:
        report = {"code": "CATALOG_INVALID", "issues": [i.as_log() for i in exc.issues]}
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return exc.exit_code
    summary = {
        "catalog_version": catalog.catalog_version,
        "catalog_sha256": catalog.catalog_sha256,
        "benchmark_sha256": catalog.benchmark_sha256,
        "vehicles": {vid: entry.spec.validation_status for vid, entry in catalog.vehicles.items()},
        "fuels": list(catalog.fuels),
        "load_ms": round(catalog.load_ms, 1),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
