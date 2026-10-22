"""Montagem do ``ForensicReport`` (RF-22 a RF-26, RF-30, RF-31): função pura, sem I/O.

``report_sha256`` = SHA-256 do JSON canônico do laudo (chaves ordenadas, floats com 6
casas, separadores ``(",", ":")``) sem ``report_sha256`` e sem ``created_at`` (relógio de
parede, fora do determinismo). O ``report_id`` é um ULID determinístico do ``run_id``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Final

import numpy as np

from simremap.damage.contracts import (
    CalibrationDiff,
    CausalLink,
    ChannelStats,
    ComponentHealth,
    FailureEvent,
    ForensicReport,
    LwTracePoint,
    ReportKind,
    TimeWindow,
)
from simremap.damage.errors import DamageError
from simremap.damage.failure import make_ulid
from simremap.damage.forensic.chain import build_causal_chain, chain_family
from simremap.damage.forensic.recommend import build_recommendations
from simremap.damage.forensic.texts import GENERATOR_VERSION, TextContext, render_texts
from simremap.damage.forensic.view import TraceView
from simremap.damage.forensic.warnings import detect_early_warnings
from simremap.damage.trace import DamageTraceSnapshot
from simremap.dyno.contracts import DynoRun

__all__ = [
    "MAX_REPORT_BYTES",
    "build_forensic_report",
    "build_minimal_report",
    "canonical_json",
    "report_sha256",
    "select_failure",
]

MAX_REPORT_BYTES: Final = 64 * 1024
LW_TRACE_WINDOW_S: Final = 2.0
LW_TRACE_MAX: Final = 200
FULL_BUFFER_S: Final = 10.0
MIN_WINDOW_S: Final = 0.1
_WINDOWS: Final = (("before", 10.0, 3.0), ("warning", 3.0, 0.5), ("collapse", 0.5, 0.0))
_STATS_CHANNELS: Final = (
    ("rpm", "rpm"),
    ("map_kpa", "kPa"),
    ("torque_nm", "N.m"),
    ("egt_collector_c", "C"),
    ("iat_c", "C"),
    ("lambda_collector", "lambda"),
    ("boost_target_kpa", "kPa"),
)
_EPS: Final = 1e-9


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6) + 0.0
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def canonical_json(data: dict[str, Any]) -> bytes:
    """JSON canônico: chaves ordenadas, floats com 6 casas, separadores compactos."""
    return json.dumps(
        _round(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def report_sha256(report: ForensicReport | dict[str, Any]) -> str:
    """SHA-256 do laudo sem ``report_sha256`` e ``created_at``."""
    data = report.model_dump(mode="json") if isinstance(report, ForensicReport) else dict(report)
    data.pop("report_sha256", None)
    data.pop("created_at", None)
    return hashlib.sha256(canonical_json(data)).hexdigest()


def select_failure(
    trace: DamageTraceSnapshot, run_id: str, kind: ReportKind
) -> FailureEvent | None:
    """Falha do laudo: 1.ª catastrófica (``failure``) ou 1.ª falha virtual (``near_miss``)."""
    events = [f for f in trace.failures if f.run_id in (None, run_id)]
    if kind == "failure":
        return next((f for f in events if f.catastrophic), None)
    return next((f for f in events if f.simulated_only and f.health_after <= 0.0), None)


def _windows(view: TraceView) -> tuple[list[TimeWindow], bool]:
    t_f = view.t_f
    t0 = view.t_start
    truncated = t0 > t_f - FULL_BUFFER_S + _EPS
    t = view.t
    out: list[TimeWindow] = []
    for name, start_before, end_before in _WINDOWS:
        start = max(t0, t_f - start_before)
        end = t_f - end_before
        if end - start < MIN_WINDOW_S - _EPS:
            continue
        mask = (t >= start - _EPS) & (t <= end + _EPS)
        stats: dict[str, ChannelStats] = {}
        for channel, unit in _STATS_CHANNELS:
            data = view.tick(channel)[mask]
            data = data[~np.isnan(data)]
            if data.size:
                lo, hi = float(data.min()), float(data.max())
                mean = min(hi, max(lo, float(data.mean())))
                stats[channel] = ChannelStats(min=lo, max=hi, mean=mean, unit=unit)
        cycles = (view.cycle("t_sim_s") >= start - _EPS) & (view.cycle("t_sim_s") <= end + _EPS)
        intensity = view.cycle("intensity")[cycles]
        if intensity.size:
            lo, hi = float(intensity.min()), float(intensity.max())
            mean = min(hi, max(lo, float(intensity.mean())))
            stats["knock_intensity"] = ChannelStats(min=lo, max=hi, mean=mean, unit="bar")
        out.append(TimeWindow(name=name, t_start_s=start, t_end_s=end, stats=stats))  # type: ignore[arg-type]
    return out, truncated


def _lw_trace(view: TraceView) -> list[LwTracePoint]:
    t = view.cycle("t_sim_s")
    mask = t >= view.t_f - LW_TRACE_WINDOW_S - _EPS
    idx = np.flatnonzero(mask)[-LW_TRACE_MAX:]
    points: list[LwTracePoint] = []
    for k in idx:
        theta = float(view.cycle("theta_onset_deg_atdc")[k])
        points.append(
            LwTracePoint(
                t_sim_s=float(t[k]),
                cylinder=int(view.cycle("cylinder")[k]),
                lw_integral_end=max(0.0, float(np.nan_to_num(view.cycle("lw_integral_end")[k]))),
                theta_onset_deg_atdc=None if np.isnan(theta) else theta,
                intensity=max(0.0, float(view.cycle("intensity")[k])),
            )
        )
    return points


def _critical_cycle(view: TraceView, octane: float) -> dict[str, float]:
    intensity = view.cycle("intensity")
    if intensity.size == 0:
        return {"octane": octane}
    k = int(np.nanargmax(np.nan_to_num(intensity, nan=-1.0)))
    return {
        "cylinder": float(view.cycle("cylinder")[k]),
        "lw_end": float(view.cycle("lw_integral_end")[k]),
        "theta_k": float(view.cycle("theta_onset_deg_atdc")[k]),
        "mapo": float(intensity[k] * 100.0),
        "intensity": float(intensity[k]),
        "tu_max": float(view.cycle("t_unburned_max_k")[k]),
        "octane": octane,
    }


def _diff_txt(diff: CalibrationDiff | None) -> str:
    if diff is None:
        return "Sem puxada base para comparar a calibração."
    parts = [f"{d.table_id} {d.max_delta:+.1f} {d.unit}" for d in diff.deltas]
    return "Diferenças face à puxada base: " + (", ".join(parts) or "nenhuma") + "."


def _component_kind(failure: FailureEvent | None) -> str:
    if failure is None:
        return "none"
    prefix = failure.component_id.split(":")[0]
    return "turbine" if prefix == "turbo" else prefix


def build_forensic_report(
    trace: DamageTraceSnapshot,
    run: DynoRun,
    baseline: DynoRun | None,
    calibration_diff: CalibrationDiff | None,
    kind: ReportKind,
    *,
    created_at: datetime | None = None,
) -> ForensicReport:
    """Laudo completo a partir do buffer congelado (pura, sem I/O)."""
    failure = select_failure(trace, run.run_id, kind)
    if kind == "failure" and failure is None:
        raise DamageError(
            "Laudo 'failure' sem FailureEvent catastrófico no buffer", code="DAMAGE_INPUT_INVALID"
        )
    diff = calibration_diff if baseline is not None else None
    t_f = failure.t_sim_s if failure is not None else trace.t_end_s
    view = TraceView(trace, t_f)
    warnings = detect_early_warnings(view)
    chain = build_causal_chain(view, failure, diff)
    recommendations = build_recommendations(view, failure, warnings, diff)
    windows, truncated = _windows(view)
    octane = trace.meta.octane
    knock_cyls = sorted({int(c) for c in view.cycle("cylinder")[view.cycle("knock_class") >= 2.0]})  # noqa: PLR2004
    texts = render_texts(
        TextContext(
            kind=kind,
            family=chain_family(None if failure is None else failure.mechanism.value),
            failure=failure,
            component_kind=_component_kind(failure),
            t_end_s=t_f,
            warnings=tuple(warnings),
            recommendations=tuple(recommendations),
            chain=tuple(chain),
            knock_cylinders=tuple(knock_cyls),
            critical=_critical_cycle(view, octane),
            diff_txt=_diff_txt(diff),
        )
    )
    damaged = [c for c in trace.components if c.health < 1.0 or c.virtual_health < 1.0]
    data: dict[str, Any] = {
        "report_id": make_ulid(round(t_f * 1000.0), "forensic", run.run_id, kind),
        "report_kind": kind,
        "run_id": run.run_id,
        "session_id": run.session_id,
        "vehicle_id": trace.meta.vehicle_id,
        "fuel_id": trace.meta.fuel_id,
        "calibration_hash": run.calibration_hash,
        "seed": trace.meta.seed,
        "sim_hz": trace.meta.sim_hz,
        "failure_event": None if failure is None else failure.model_dump(mode="json"),
        "primary_mode": None if failure is None else failure.mode.value,
        "damaged_components": [
            ComponentHealth.model_validate(c.model_dump()).model_dump(mode="json") for c in damaged
        ],
        "causal_chain": [c.model_dump(mode="json") for c in chain],
        "time_windows": [w.model_dump(mode="json") for w in windows],
        "early_warnings": [w.model_dump(mode="json") for w in warnings],
        "recommendations": [r.model_dump(mode="json") for r in recommendations],
        "texts": {k: v.model_dump(mode="json") for k, v in texts.items()},
        "calibration_diff": None if diff is None else diff.model_dump(mode="json"),
        "lw_trace": [p.model_dump(mode="json") for p in _lw_trace(view)],
        "buffer_truncated": truncated,
        "simulated_only": not trace.meta.damage_enabled,
        "generator_version": GENERATOR_VERSION,
    }
    while len(canonical_json(data)) > MAX_REPORT_BYTES and data["lw_trace"]:
        data["lw_trace"] = data["lw_trace"][len(data["lw_trace"]) // 2 + 1 :]
    return _finalize(data, created_at)


def _finalize(data: dict[str, Any], created_at: datetime | None) -> ForensicReport:
    data = _round(data)
    data["report_sha256"] = hashlib.sha256(canonical_json(data)).hexdigest()
    data["created_at"] = (created_at or datetime.now(UTC)).isoformat()
    return ForensicReport.model_validate(data)


def build_minimal_report(
    trace: DamageTraceSnapshot,
    run: DynoRun,
    kind: ReportKind,
    *,
    created_at: datetime | None = None,
) -> ForensicReport:
    """Fallback do EC-07: falha + 1 elo (geração acima de 5 s)."""
    failure = select_failure(trace, run.run_id, kind)
    t_f = failure.t_sim_s if failure is not None else trace.t_end_s
    if failure is not None:
        link = CausalLink(
            order=1,
            t_sim_s=t_f,
            kind="failure",
            cylinder=failure.cylinder,
            variable=failure.component_id,
            value=failure.health_after,
            threshold=0.0,
            unit="health",
            description=f"Falha {failure.mode.value} em {failure.component_id}",
        )
    else:
        link = CausalLink(
            order=1,
            t_sim_s=t_f,
            kind="warning",
            variable="run_end",
            value=t_f,
            unit="s",
            description="Fim da puxada por proteção (quase-falha)",
        )
    texts = render_texts(
        TextContext(
            kind=kind,
            family=chain_family(None if failure is None else failure.mechanism.value),
            failure=failure,
            component_kind=_component_kind(failure),
            t_end_s=t_f,
            warnings=(),
            recommendations=(),
            chain=(link,),
            knock_cylinders=(),
            critical={},
            diff_txt=_diff_txt(None),
        )
    )
    data: dict[str, Any] = {
        "report_id": make_ulid(round(t_f * 1000.0), "forensic", run.run_id, kind),
        "report_kind": kind,
        "run_id": run.run_id,
        "session_id": run.session_id,
        "vehicle_id": trace.meta.vehicle_id,
        "fuel_id": trace.meta.fuel_id,
        "calibration_hash": run.calibration_hash,
        "seed": trace.meta.seed,
        "sim_hz": trace.meta.sim_hz,
        "failure_event": None if failure is None else failure.model_dump(mode="json"),
        "primary_mode": None if failure is None else failure.mode.value,
        "damaged_components": [],
        "causal_chain": [link.model_dump(mode="json")],
        "time_windows": [],
        "early_warnings": [],
        "recommendations": [],
        "texts": {k: v.model_dump(mode="json") for k, v in texts.items()},
        "calibration_diff": None,
        "lw_trace": [],
        "buffer_truncated": True,
        "simulated_only": not trace.meta.damage_enabled,
        "generator_version": GENERATOR_VERSION,
    }
    return _finalize(data, created_at)
