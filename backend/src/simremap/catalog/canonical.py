"""JSON canónico e hashes do catálogo (vehicle-catalog RF-24, RF-25, RF-29; D-FF-02).

Regras (``contracts/file-formats.md`` seção 7.1):
- ``sha256`` de arquivo do manifesto: SHA-256 dos **bytes** do arquivo.
- ``catalog_sha256`` e ``data_sha256``: SHA-256 do JSON canónico dos modelos (chaves
  ordenadas, separadores compactos, UTF-8 sem escape, floats em ``repr``).
- ``benchmark_sha256``: SHA-256 do JSON canónico da lista ``[{path, sha256}]`` das
  entradas de curva do manifesto, ordenada por ``path``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any, Final

__all__ = [
    "CURVE_PATH_GLOB",
    "benchmark_sha256",
    "canonical_dumps",
    "canonical_sha256",
    "sha256_bytes",
]

CURVE_PATH_GLOB: Final = "vehicles/*/reference-curves/*.json"


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON canónico não aceita NaN nem infinito")
    if isinstance(value, Mapping):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_finite(item)


def canonical_dumps(value: Any) -> bytes:
    """Serialização canónica: ``sort_keys``, ``(",", ":")``, UTF-8, floats em ``repr``."""
    _check_finite(value)
    text = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def benchmark_sha256(entries: Iterable[Mapping[str, str]]) -> str:
    """D-FF-02: hash da lista ``[{path, sha256}]`` das curvas do manifesto, por ``path``."""
    curves = sorted(
        (
            {"path": entry["path"], "sha256": entry["sha256"]}
            for entry in entries
            if fnmatch.fnmatchcase(entry["path"], CURVE_PATH_GLOB)
            and entry["path"].count("/") == CURVE_PATH_GLOB.count("/")
        ),
        key=lambda item: item["path"],
    )
    return canonical_sha256(curves)
