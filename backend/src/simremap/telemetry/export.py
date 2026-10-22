"""Export do log em JSON e CSV, em streaming (tel RF-17; RNF-06; file-formats 4.2 e 4.3; D-12).

- JSON: o ``DataLog`` completo; cada valor ``float32`` sai como ``repr(float(np.float32(v)))``
  (round-trip exato para ``float32``; NaN vira ``null``), por isso export → import mantém o
  ``sha256``. Gerado coluna a coluna (sem montar o documento inteiro em memória).
- CSV: separador ``,``, ponto decimal, ``\\n``, ausente = campo vazio, flags ``0``/``1``;
  cabeçalho ``nome (unidade)`` com as colunas fixas ``t_sim_s (s)`` e ``tick (-)``;
  ``tick = start_tick + índice``; ``decimate = n`` mantém 1 amostra a cada n. Células de
  texto que começam por ``= + - @`` (ou tabulação/CR) recebem o prefixo ``'`` (proteção
  contra fórmulas; premissa OQ-06: separador ``,`` no MVP).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Final

import numpy as np
import orjson

from simremap.telemetry.contracts import ChannelKind
from simremap.telemetry.datalog import LogData
from simremap.telemetry.errors import telemetry_error

__all__ = [
    "CSV_CHUNK_ROWS",
    "csv_cell",
    "csv_header",
    "iter_csv",
    "iter_json",
    "json_floats",
    "select_channels",
]

CSV_CHUNK_ROWS: Final = 2000
_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")


def json_floats(column: np.ndarray) -> bytes:
    """Lista JSON de ``float32`` com ``repr(float(np.float32(v)))`` e NaN como ``null``."""
    return orjson.dumps(
        np.asarray(column, dtype=np.float32).astype(np.float64),
        option=orjson.OPT_SERIALIZE_NUMPY,
    )


def iter_json(log: LogData) -> Iterator[bytes]:
    """``DataLog`` JSON em pedaços (cabeçalho, ``t_sim_s``, uma coluna por pedaço)."""
    header = log.header.model_dump_json().encode()
    yield b'{"header":' + header + b',"t_sim_s":'
    yield orjson.dumps(log.t_sim_s, option=orjson.OPT_SERIALIZE_NUMPY)
    yield b',"data":{'
    for i, name in enumerate(log.names):
        prefix = b"," if i else b""
        yield prefix + json.dumps(name).encode() + b":" + json_floats(log.columns[i])
    created = None if log.created_at is None else log.created_at.isoformat()
    tail = {"sha256": log.sha256, "log_id": log.log_id, "created_at": created, "source": log.source}
    yield b"}," + orjson.dumps(tail)[1:]


def csv_cell(text: str) -> str:
    """Célula de texto protegida contra fórmulas e aspas."""
    if text.startswith(_FORMULA_PREFIXES):
        text = "'" + text
    if any(ch in text for ch in ',"\n'):
        text = '"' + text.replace('"', '""') + '"'
    return text


def select_channels(log: LogData, channels: Sequence[str] | None) -> list[int]:
    """Índices das colunas pedidas (ordem do pedido) ou todas (ordem do cabeçalho)."""
    if not channels:
        return list(range(len(log.names)))
    index = {name: i for i, name in enumerate(log.names)}
    unknown = [c for c in channels if c not in index]
    if unknown:
        raise telemetry_error(
            "VALIDATION_FAILED", f"Canais fora do log: {', '.join(unknown)}"[:2000]
        )
    return [index[c] for c in dict.fromkeys(channels)]


def csv_header(log: LogData, columns: Sequence[int]) -> str:
    cells = ["t_sim_s (s)", "tick (-)"]
    for i in columns:
        channel = log.header.channels[i]
        cells.append(f"{channel.name} ({channel.unit})")
    return ",".join(csv_cell(c) for c in cells) + "\n"


def _format_column(values: np.ndarray, flag: bool) -> np.ndarray:
    if flag:
        out = np.where(np.isnan(values), "", np.where(values != 0, "1", "0"))
        return out.astype(object)
    text = values.astype(np.float32).astype(str).astype(object)
    text[np.isnan(values)] = ""
    return text


def iter_csv(
    log: LogData, channels: Sequence[str] | None = None, decimate: int = 1
) -> Iterator[bytes]:
    """CSV em pedaços de ``CSV_CHUNK_ROWS`` linhas (``n_samples + 1`` linhas com decimate 1)."""
    columns = select_channels(log, channels)
    yield csv_header(log, columns).encode("utf-8")
    n = log.header.n_samples
    step = max(1, int(decimate))
    flags = [log.header.channels[i].kind == ChannelKind.FLAG for i in columns]
    start_tick = log.header.start_tick
    for begin in range(0, n, CSV_CHUNK_ROWS * step):
        idx = np.arange(begin, min(n, begin + CSV_CHUNK_ROWS * step), step)
        parts: list[np.ndarray] = [
            np.array([repr(float(t)) for t in log.t_sim_s[idx]], dtype=object),
            (start_tick + idx).astype(str).astype(object),
        ]
        parts.extend(
            _format_column(log.columns[i, idx], flag)
            for i, flag in zip(columns, flags, strict=True)
        )
        rows = [",".join(row) for row in zip(*parts, strict=True)]
        yield ("\n".join(rows) + "\n").encode("utf-8")
