"""DataLog canónico: hash, arquivo ``.simlog.gz`` e validação de import (tel RF-14 a RF-16,
RF-18; file-formats 4.2 e 4.4; D-12).

Conteúdo do arquivo antes do gzip (nível 6)::

    b"SIMLOG1\\n" | uint32 LE (tamanho do cabeçalho) | cabeçalho canónico UTF-8
    | t_sim_s float64 LE [n] | 1 coluna float32 LE [n] por canal | sha256 hex ASCII (64 B)

Cabeçalho canónico: ``json.dumps(header.model_dump(mode="json"), sort_keys=True,
separators=(",", ":"), ensure_ascii=False)`` com os floats arredondados a 6 casas.
Hash: ``sha256(cabeçalho + t_sim_s + Σ colunas)``; ``log_id``, ``created_at`` e ``source``
ficam fora. Ausente = NaN quiet ``0x7FC00000``.

Import (``parse_import``): corpo ≤ 64 MB descomprimido (``Content-Encoding: gzip`` aceite),
profundidade JSON ≤ 32, ≤ 256 canais, ``format_version`` (``LOG_FORMAT_UNSUPPORTED``),
schema (``LOG_SCHEMA_INVALID``) e SHA-256 recalculado (``LOG_HASH_MISMATCH``).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
from pydantic import ValidationError

from simremap.core.versions import DATALOG_FORMAT_VERSION
from simremap.telemetry.contracts import MAX_IMPORT_CHANNELS, DataLog, DataLogHeader
from simremap.telemetry.errors import telemetry_error

__all__ = [
    "GZIP_LEVEL",
    "MAGIC",
    "MAX_IMPORT_BYTES",
    "MAX_JSON_DEPTH",
    "LogData",
    "canonical_header",
    "compute_sha256",
    "decode_simlog",
    "encode_simlog",
    "json_depth_exceeds",
    "normalize_nan",
    "parse_import",
    "read_simlog",
    "round_floats",
    "write_simlog",
]

MAGIC: Final = b"SIMLOG1\n"
GZIP_LEVEL: Final = 6
MAX_IMPORT_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_DEPTH: Final = 32
HEADER_FLOAT_DECIMALS: Final = 6
_NAN32: Final = np.uint32(0x7FC00000)


def round_floats(value: Any, decimals: int = HEADER_FLOAT_DECIMALS) -> Any:
    """Arredonda recursivamente os floats (payloads de eventos do cabeçalho)."""
    if isinstance(value, float):
        return round(value, decimals) if np.isfinite(value) else None
    if isinstance(value, dict):
        return {k: round_floats(v, decimals) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [round_floats(v, decimals) for v in value]
    return value


def canonical_header(header: DataLogHeader) -> bytes:
    """Cabeçalho canónico UTF-8 (chaves ordenadas, sem espaços, floats a 6 casas)."""
    data = round_floats(header.model_dump(mode="json"))
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def normalize_nan(columns: np.ndarray) -> np.ndarray:
    """``float32`` little-endian com todo NaN no padrão quiet ``0x7FC00000``."""
    out = np.ascontiguousarray(columns, dtype="<f4").copy()
    mask = np.isnan(out)
    if mask.any():
        out.view(np.uint32)[mask] = _NAN32
    return out


def compute_sha256(header: DataLogHeader, t_sim_s: np.ndarray, columns: np.ndarray) -> str:
    """SHA-256 canónico: cabeçalho + ``t_sim_s`` float64 + colunas float32 (ordem do catálogo)."""
    digest = hashlib.sha256(canonical_header(header))
    digest.update(np.ascontiguousarray(t_sim_s, dtype="<f8").tobytes())
    digest.update(normalize_nan(columns).tobytes())
    return digest.hexdigest()


@dataclass(slots=True)
class LogData:
    """Log em memória: cabeçalho, ``t_sim_s`` [n] e colunas ``float32`` [canais, n]."""

    header: DataLogHeader
    t_sim_s: np.ndarray
    columns: np.ndarray
    sha256: str
    log_id: str | None = None
    created_at: datetime | None = None
    source: str = "simulated"

    def __post_init__(self) -> None:
        n = self.header.n_samples
        n_ch = len(self.header.channels)
        self.t_sim_s = np.ascontiguousarray(self.t_sim_s, dtype=np.float64)
        self.columns = normalize_nan(np.asarray(self.columns, dtype=np.float32).reshape(n_ch, n))
        if self.t_sim_s.shape != (n,):
            raise ValueError("t_sim_s com comprimento diferente de n_samples")

    @classmethod
    def build(cls, header: DataLogHeader, t_sim_s: np.ndarray, columns: np.ndarray) -> LogData:
        """Log novo com o ``sha256`` calculado."""
        cols = normalize_nan(columns)
        return cls(header, t_sim_s, cols, compute_sha256(header, t_sim_s, cols))

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.header.channels]

    def column(self, name: str) -> np.ndarray:
        """Coluna ``float32`` do canal ``name`` (``KeyError`` se ausente)."""
        column: np.ndarray = self.columns[self.names.index(name)]
        return column

    def has(self, name: str) -> bool:
        return name in self.names

    def recomputed_sha256(self) -> str:
        return compute_sha256(self.header, self.t_sim_s, self.columns)


# --------------------------------------------------------------------------- binário


def encode_simlog(log: LogData) -> bytes:
    """Conteúdo do ``.simlog`` antes do gzip."""
    header = canonical_header(log.header)
    parts = [
        MAGIC,
        struct.pack("<I", len(header)),
        header,
        np.ascontiguousarray(log.t_sim_s, dtype="<f8").tobytes(),
        normalize_nan(log.columns).tobytes(),
        log.sha256.encode("ascii"),
    ]
    return b"".join(parts)


def decode_simlog(raw: bytes) -> LogData:
    """Conteúdo descomprimido → ``LogData``; valida magic, tamanhos e hash (``LOG_CORRUPTED``)."""
    try:
        if not raw.startswith(MAGIC):
            raise ValueError("magic inválido")
        (size,) = struct.unpack_from("<I", raw, len(MAGIC))
        start = len(MAGIC) + 4
        header = DataLogHeader.model_validate_json(raw[start : start + size])
        n = header.n_samples
        n_ch = len(header.channels)
        offset = start + size
        t_end = offset + 8 * n
        c_end = t_end + 4 * n * n_ch
        if len(raw) != c_end + 64:
            raise ValueError("tamanho do arquivo inconsistente")
        t = np.frombuffer(raw[offset:t_end], dtype="<f8")
        cols = np.frombuffer(raw[t_end:c_end], dtype="<f4").reshape(n_ch, n)
        declared = raw[c_end:].decode("ascii")
        log = LogData(header, t, cols, declared)
    except (ValueError, ValidationError, struct.error, UnicodeDecodeError) as exc:
        raise telemetry_error("LOG_CORRUPTED", f"Arquivo de log inválido: {exc}"[:500]) from exc
    computed = log.recomputed_sha256()
    if computed != declared:
        raise telemetry_error(
            "LOG_CORRUPTED",
            "O SHA-256 recalculado do arquivo difere do gravado.",
            expected=declared,
            computed=computed,
        )
    return log


def write_simlog(path: Path, log: LogData) -> int:
    """Grava ``path`` (gzip nível 6, escrita atómica); devolve os bytes comprimidos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(encode_simlog(log), compresslevel=GZIP_LEVEL, mtime=0)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return len(data)


def read_simlog(path: Path) -> LogData:
    """Lê e valida ``path`` (``LOG_CORRUPTED`` em gzip ou hash inválido)."""
    try:
        raw = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, zlib.error) as exc:
        raise telemetry_error("LOG_CORRUPTED", f"Gzip do log inválido: {exc}"[:500]) from exc
    return decode_simlog(raw)


# --------------------------------------------------------------------------- import


def _decompress(body: bytes, limit: int) -> bytes:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decoder.decompress(body, limit + 1)
    except zlib.error as exc:
        raise telemetry_error("LOG_SCHEMA_INVALID", f"Corpo gzip inválido: {exc}") from exc
    if len(out) > limit or decoder.unconsumed_tail:
        raise telemetry_error(
            "PAYLOAD_TOO_LARGE", f"O log descomprimido excede {limit} bytes.", limit=limit
        )
    return out


def json_depth_exceeds(value: Any, limit: int = MAX_JSON_DEPTH) -> bool:
    """``True`` se a profundidade de aninhamento passa de ``limit`` (iterativo)."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children: Any = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth > limit:
            return True
        for child in children:
            if isinstance(child, dict | list):
                stack.append((child, depth + 1))
    return False


def _schema_error(detail: str) -> Exception:
    return telemetry_error("LOG_SCHEMA_INVALID", detail[:2000])


def parse_import(body: bytes, content_encoding: str | None = None) -> LogData:
    """Valida o ``DataLog`` JSON do import e devolve o log com o hash conferido."""
    encoding = (content_encoding or "").strip().lower()
    if encoding in ("gzip", "x-gzip"):
        body = _decompress(body, MAX_IMPORT_BYTES)
    elif encoding not in ("", "identity"):
        raise telemetry_error(
            "UNSUPPORTED_MEDIA_TYPE", f"Content-Encoding {encoding!r} não suportado."
        )
    if len(body) > MAX_IMPORT_BYTES:
        raise telemetry_error(
            "PAYLOAD_TOO_LARGE", f"O log excede {MAX_IMPORT_BYTES} bytes.", limit=MAX_IMPORT_BYTES
        )
    try:
        raw = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise _schema_error(f"JSON inválido: {exc}") from exc
    if json_depth_exceeds(raw):
        raise _schema_error(f"Profundidade JSON acima de {MAX_JSON_DEPTH}.")
    if not isinstance(raw, dict) or not isinstance(raw.get("header"), dict):
        raise _schema_error("O corpo deve ser um DataLog com 'header'.")
    version = raw["header"].get("format_version")
    if isinstance(version, int) and not isinstance(version, bool):
        if version > DATALOG_FORMAT_VERSION:
            raise telemetry_error(
                "LOG_FORMAT_UNSUPPORTED",
                f"format_version {version} não suportado (máximo {DATALOG_FORMAT_VERSION}).",
                format_version=version,
            )
    channels = raw["header"].get("channels")
    data = raw.get("data")
    if (isinstance(channels, list) and len(channels) > MAX_IMPORT_CHANNELS) or (
        isinstance(data, dict) and len(data) > MAX_IMPORT_CHANNELS
    ):
        raise _schema_error(f"Mais de {MAX_IMPORT_CHANNELS} canais.")
    try:
        model = DataLog.model_validate(raw)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][:4])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise _schema_error(f"DataLog fora do schema: {errors}") from exc
    log = from_model(model)
    computed = log.recomputed_sha256()
    if computed != model.sha256:
        raise telemetry_error(
            "LOG_HASH_MISMATCH",
            f"SHA-256 declarado {model.sha256} difere do recalculado {computed}.",
            expected=model.sha256,
            computed=computed,
        )
    return log


def from_model(model: DataLog) -> LogData:
    """``DataLog`` (JSON) → ``LogData`` (valores convertidos para ``float32``)."""
    header = model.header
    n = header.n_samples
    cols = np.empty((len(header.channels), n), dtype=np.float32)
    for i, channel in enumerate(header.channels):
        values = model.data[channel.name]
        cols[i] = np.array([np.nan if v is None else v for v in values], dtype=np.float64)
    t = np.array(model.t_sim_s, dtype=np.float64)
    return LogData(
        header,
        t,
        cols,
        model.sha256,
        log_id=model.log_id,
        created_at=model.created_at,
        source=model.source,
    )
