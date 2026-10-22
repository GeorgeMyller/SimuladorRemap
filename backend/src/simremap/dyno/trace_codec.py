"""Transporte do ``DamageTraceSnapshot`` do worker para o event loop (saída ``damage.trace``).

O laudo forense corre fora do laço (``ForensicService.submit``) e o worker em modo
``process`` só fala por bytes JSON. O codec serializa o snapshot sem ``pickle``:
metadados como JSON, ``ComponentHealth``/``FailureEvent``/``DamageConfig`` pelo Pydantic e
cada array como ``float64`` little-endian em base64 (cópia exata, sem arredondamento).
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any

import numpy as np
from numpy.typing import NDArray

from simremap.damage.config import DamageConfig
from simremap.damage.contracts import ComponentHealth, FailureEvent
from simremap.damage.mechanical import StructuralLimits
from simremap.damage.trace import DamageTraceSnapshot, TraceMeta

__all__ = ["decode_trace", "encode_trace"]


def _encode_array(array: NDArray[np.float64]) -> dict[str, Any]:
    data = np.ascontiguousarray(array, dtype="<f8")
    return {"shape": list(data.shape), "data": base64.b64encode(data.tobytes()).decode("ascii")}


def _decode_array(raw: dict[str, Any]) -> NDArray[np.float64]:
    shape = tuple(int(n) for n in raw["shape"])
    data = np.frombuffer(base64.b64decode(raw["data"]), dtype="<f8").astype(np.float64)
    array = data.reshape(shape)
    array.flags.writeable = False
    return array


def _encode_meta(meta: TraceMeta) -> dict[str, Any]:
    return {
        "session_id": meta.session_id,
        "vehicle_id": meta.vehicle_id,
        "fuel_id": meta.fuel_id,
        "seed": meta.seed,
        "sim_hz": meta.sim_hz,
        "n_cyl": meta.n_cyl,
        "damage_enabled": meta.damage_enabled,
        "component_ids": list(meta.component_ids),
        "limits": asdict(meta.limits),
        "hot_spot_threshold_c": meta.hot_spot_threshold_c,
        "stock_boost_kpa": meta.stock_boost_kpa,
        "octane": meta.octane,
        "config": meta.config.model_dump(mode="json"),
    }


def _decode_meta(raw: dict[str, Any]) -> TraceMeta:
    return TraceMeta(
        session_id=str(raw["session_id"]),
        vehicle_id=str(raw["vehicle_id"]),
        fuel_id=str(raw["fuel_id"]),
        seed=int(raw["seed"]),
        sim_hz=int(raw["sim_hz"]),
        n_cyl=int(raw["n_cyl"]),
        damage_enabled=bool(raw["damage_enabled"]),
        component_ids=tuple(str(c) for c in raw["component_ids"]),
        limits=StructuralLimits(**raw["limits"]),
        hot_spot_threshold_c=float(raw["hot_spot_threshold_c"]),
        stock_boost_kpa=None if raw["stock_boost_kpa"] is None else float(raw["stock_boost_kpa"]),
        octane=float(raw["octane"]),
        config=DamageConfig.model_validate(raw["config"]),
    )


def encode_trace(trace: DamageTraceSnapshot) -> dict[str, Any]:
    """Snapshot → dict JSON (arrays em base64)."""
    return {
        "meta": _encode_meta(trace.meta),
        "tick": {name: _encode_array(arr) for name, arr in trace.tick.items()},
        "cycle": {name: _encode_array(arr) for name, arr in trace.cycle.items()},
        "components": [c.model_dump(mode="json") for c in trace.components],
        "failures": [f.model_dump(mode="json") for f in trace.failures],
        "t_start_s": trace.t_start_s,
        "t_end_s": trace.t_end_s,
        "extra": dict(trace.extra),
    }


def decode_trace(raw: dict[str, Any]) -> DamageTraceSnapshot:
    """dict JSON → ``DamageTraceSnapshot`` (arrays só de leitura)."""
    return DamageTraceSnapshot(
        meta=_decode_meta(raw["meta"]),
        tick={name: _decode_array(arr) for name, arr in raw["tick"].items()},
        cycle={name: _decode_array(arr) for name, arr in raw["cycle"].items()},
        components=tuple(ComponentHealth.model_validate(c) for c in raw["components"]),
        failures=tuple(FailureEvent.model_validate(f) for f in raw["failures"]),
        t_start_s=float(raw["t_start_s"]),
        t_end_s=float(raw["t_end_s"]),
        extra={str(k): float(v) for k, v in raw.get("extra", {}).items()},
    )
