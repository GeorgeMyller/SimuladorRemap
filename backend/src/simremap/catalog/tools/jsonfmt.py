"""Escrita legível e estável dos arquivos JSON do catálogo (UTF-8 sem BOM, fim ``\\n``).

Objetos indentados com 2 espaços; listas de escalares numa só linha (grelhas legíveis
por linha). A ordem das chaves é a de inserção, para manter os arquivos próximos dos
exemplos dos contratos; os hashes canónicos não dependem desta formatação.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["dumps_pretty", "write_json"]


def _scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _is_flat(value: Any) -> bool:
    return isinstance(value, list) and all(not isinstance(v, dict | list) for v in value)


def _render(value: Any, indent: int) -> str:
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}{_scalar(k)}: {_render(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(value, list):
        if _is_flat(value):
            return "[" + ", ".join(_scalar(v) for v in value) + "]"
        items = [f"{pad}{_render(v, indent + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return _scalar(value)


def dumps_pretty(value: Any) -> str:
    return _render(value, 0) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_pretty(value), encoding="utf-8", newline="\n")
