"""Estado canónico, ``state_digest()`` e ``snapshot``/``restore`` (RF-20, RF-25; D-08).

Formato do snapshot (sem ``pickle``, seção 12 da spec)::

    b"SRPHYS1\\n" + uint32 LE (tamanho do cabeçalho) + cabeçalho JSON canónico + payload

O payload é o vetor do estado em float64 little-endian, na ordem fixa dos campos do
``dataclass``; listas entram com o comprimento declarado no cabeçalho. O cabeçalho leva
``schema_version``, o layout, o estado dos geradores de ruído e o SHA-256 do payload.
O digest é o SHA-256 de ``payload + estado dos geradores (JSON canónico)``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
from typing import Any, Final

import numpy as np

from simremap.physics.errors import PHYSICS_SNAPSHOT_INVALID, PhysicsError

__all__ = [
    "SCHEMA_VERSION",
    "SNAPSHOT_MAGIC",
    "canonical_json",
    "layout_of",
    "pack_state",
    "read_snapshot",
    "state_digest",
    "unpack_state",
    "write_snapshot",
]

SCHEMA_VERSION: Final = 1
SNAPSHOT_MAGIC: Final = b"SRPHYS1\n"


def canonical_json(obj: object) -> bytes:
    """JSON canónico (chaves ordenadas, sem espaços, UTF-8)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def layout_of(state: object) -> list[list[Any]]:
    """Layout ``[[nome, comprimento], ...]`` (0 = escalar) na ordem dos campos."""
    out: list[list[Any]] = []
    for f in dataclasses.fields(state):  # type: ignore[arg-type]
        value = getattr(state, f.name)
        out.append([f.name, len(value) if isinstance(value, list) else 0])
    return out


def pack_state(state: object) -> bytes:
    """Serializa o estado em float64 LE na ordem fixa dos campos."""
    values: list[float] = []
    for f in dataclasses.fields(state):  # type: ignore[arg-type]
        value = getattr(state, f.name)
        if isinstance(value, list):
            values.extend(float(v) for v in value)
        else:
            values.append(float(value))
    return np.asarray(values, dtype="<f8").tobytes()


def unpack_state(state: object, payload: bytes, layout: list[list[Any]]) -> None:
    """Escreve no ``state`` os valores do payload (tipos preservados pelos atuais)."""
    current = layout_of(state)
    if current != layout:
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "layout do snapshot difere do motor atual")
    data = np.frombuffer(payload, dtype="<f8")
    expected = sum(max(n, 1) if n else 1 for _, n in layout)
    if data.size != expected:
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "tamanho do payload incoerente")
    pos = 0
    updates: dict[str, Any] = {}
    for f in dataclasses.fields(state):  # type: ignore[arg-type]
        value = getattr(state, f.name)
        if isinstance(value, list):
            n = len(value)
            updates[f.name] = [float(v) for v in data[pos : pos + n]]
            pos += n
        else:
            raw = float(data[pos])
            pos += 1
            if isinstance(value, bool):
                updates[f.name] = raw != 0.0
            elif isinstance(value, int):
                updates[f.name] = int(raw)
            else:
                updates[f.name] = raw
    for name, value in updates.items():
        setattr(state, name, value)


def state_digest(payload: bytes, rng_state: bytes) -> str:
    """SHA-256 hex do estado canónico (payload + geradores)."""
    h = hashlib.sha256()
    h.update(payload)
    h.update(rng_state)
    return h.hexdigest()


def write_snapshot(
    payload: bytes, layout: list[list[Any]], rng: dict[str, Any], meta: dict[str, Any]
) -> bytes:
    header = {
        "schema_version": SCHEMA_VERSION,
        "layout": layout,
        "rng": rng,
        "meta": meta,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_len": len(payload),
    }
    raw = canonical_json(header)
    return SNAPSHOT_MAGIC + struct.pack("<I", len(raw)) + raw + payload


def read_snapshot(blob: bytes) -> tuple[dict[str, Any], bytes]:
    """Valida o blob e devolve ``(cabeçalho, payload)``; ``PHYSICS_SNAPSHOT_INVALID`` se não."""
    if not isinstance(blob, bytes | bytearray) or not blob.startswith(SNAPSHOT_MAGIC):
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "snapshot sem cabeçalho SRPHYS1")
    start = len(SNAPSHOT_MAGIC)
    if len(blob) < start + 4:
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "snapshot truncado")
    (hlen,) = struct.unpack("<I", blob[start : start + 4])
    raw = bytes(blob[start + 4 : start + 4 + hlen])
    payload = bytes(blob[start + 4 + hlen :])
    try:
        header = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "cabeçalho JSON inválido") from exc
    if not isinstance(header, dict) or header.get("schema_version") != SCHEMA_VERSION:
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "schema_version do snapshot incompatível")
    if header.get("payload_len") != len(payload) or (
        header.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "hash do payload não coincide")
    return header, payload
