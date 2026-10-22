"""Comparação de dois logs por bins de RPM (tel RF-19; EC-12, EC-13; RNF-06).

Algoritmo (spec seção 9, "Algoritmo de comparação"):

1. segmento da puxada pedido (``pull_index``; padrão o 1.º) e, nele, só as amostras com
   ``run.state = running`` na fase ``pull`` e derivada de ``rpm`` ≥ 0 (puxada ascendente);
2. bin ``floor(rpm / bin_rpm) · bin_rpm``; bins com menos de ``min_samples_per_bin``
   amostras são descartados;
3. por bin: média de ``torque_nm``, ``power_kw``, ``whp``, ``lambda`` e ``egt_c``; máximo
   de ``knock_intensity_cyl<k>``;
4. deltas B − A nos bins comuns; ``delta_peak_whp_pct``; ``vehicle_mismatch`` não é erro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from simremap.telemetry.contracts import (
    ComparisonBin,
    DataLogSummary,
    LogCompareRequest,
    LogComparison,
)
from simremap.telemetry.datalog import LogData
from simremap.telemetry.errors import telemetry_error

__all__ = ["BinStats", "bin_log", "compare_logs", "pull_mask", "summary_of"]

_METRICS: Final = ("torque_nm", "power_kw", "whp", "lambda", "egt_c")
_REQUIRED: Final = ("rpm", "torque_nm", "power_kw", "whp", "egt_c")


@dataclass(frozen=True, slots=True)
class BinStats:
    rpm_bin: int
    n: int
    torque_nm: float
    power_kw: float
    whp: float
    lambda_: float | None
    egt_c: float
    knock_max: float


def summary_of(log: LogData) -> DataLogSummary:
    return DataLogSummary(
        log_id=log.log_id or log.header.run_id,
        run_id=log.header.run_id,
        vehicle_id=log.header.vehicle_id,
        sha256=log.sha256,
        n_samples=log.header.n_samples,
        sim_hz=log.header.sim_hz,
        source="imported" if log.source == "imported" else "simulated",
    )


def _segment(log: LogData, pull_index: int | None) -> tuple[int, int]:
    n = log.header.n_samples
    pulls = sorted(log.header.pulls, key=lambda p: p.pull_index)
    if not pulls:
        if pull_index not in (None, 1):
            raise telemetry_error(
                "VALIDATION_FAILED", f"O log {log.header.run_id} não tem a puxada {pull_index}."
            )
        return 0, n
    if pull_index is None:
        return pulls[0].start_index, pulls[0].end_index
    for seg in pulls:
        if seg.pull_index == pull_index:
            return seg.start_index, seg.end_index
    raise telemetry_error(
        "VALIDATION_FAILED", f"O log {log.header.run_id} não tem a puxada {pull_index}."
    )


def pull_mask(log: LogData) -> np.ndarray:
    """Amostras com ``run.state = running`` na fase ``pull`` (pelos eventos do cabeçalho)."""
    n = log.header.n_samples
    mask = np.zeros(n, dtype=bool)
    changes: list[tuple[int, bool]] = []
    for event in log.header.events:
        if event.type != "run.state":
            continue
        payload = event.payload
        active = payload.get("state") == "running" and payload.get("phase") in (None, "pull")
        changes.append((event.index, active))
    current = False
    last = 0
    for raw_index, active in changes:
        index = min(max(raw_index, 0), n)
        if current:
            mask[last:index] = True
        current, last = active, index
    if current:
        mask[last:n] = True
    return mask


def bin_log(
    log: LogData, bin_rpm: int, pull_index: int | None, min_samples: int
) -> dict[int, BinStats]:
    """Bins de RPM do segmento ascendente da puxada."""
    missing = [name for name in _REQUIRED if not log.has(name)]
    if missing:
        raise telemetry_error(
            "LOG_SCHEMA_INVALID", f"O log não tem os canais {', '.join(missing)}."
        )
    start, end = _segment(log, pull_index)
    rpm = log.column("rpm").astype(np.float64)
    mask = pull_mask(log)
    seg = np.zeros_like(mask)
    seg[start:end] = True
    rising = np.diff(rpm, prepend=rpm[:1]) >= 0.0
    select = mask & seg & rising & np.isfinite(rpm)
    idx = np.flatnonzero(select)
    if idx.size == 0:
        return {}
    bins = (np.floor(rpm[idx] / bin_rpm) * bin_rpm).astype(np.int64)
    values = {name: log.column(name)[idx].astype(np.float64) for name in _METRICS if log.has(name)}
    knock_cols = [
        log.columns[i][idx].astype(np.float64)
        for i, c in enumerate(log.header.channels)
        if c.base == "knock_intensity" and c.cylinder is not None
    ]
    knock = np.fmax.reduce(np.vstack(knock_cols), axis=0) if knock_cols else np.zeros(idx.size)
    out: dict[int, BinStats] = {}
    for b in np.unique(bins).tolist():
        sel = bins == b
        count = int(sel.sum())
        if count < min_samples:
            continue
        means = {}
        for name, col in values.items():
            chunk = col[sel]
            finite = chunk[np.isfinite(chunk)]
            means[name] = float(finite.mean()) if finite.size else None
        if any(means.get(name) is None for name in ("torque_nm", "power_kw", "whp", "egt_c")):
            continue
        k = knock[sel]
        k = k[np.isfinite(k)]
        out[int(b)] = BinStats(
            rpm_bin=int(b),
            n=count,
            torque_nm=float(means["torque_nm"] or 0.0),
            power_kw=float(means["power_kw"] or 0.0),
            whp=float(means["whp"] or 0.0),
            lambda_=means.get("lambda"),
            egt_c=float(means["egt_c"] or 0.0),
            knock_max=float(min(max(k.max(), 0.0), 1.0)) if k.size else 0.0,
        )
    return out


def _range(bins: dict[int, BinStats], bin_rpm: int) -> str:
    if not bins:
        return "sem amostras de puxada ascendente"
    return f"{min(bins)}–{max(bins) + bin_rpm} rpm"


def compare_logs(a: LogData, b: LogData, request: LogCompareRequest) -> LogComparison:
    """``LogComparison`` B − A (``LOG_COMPARE_NO_OVERLAP`` sem bins comuns)."""
    bin_rpm = request.bin_rpm
    bins_a = bin_log(a, bin_rpm, request.pull_index_a, request.min_samples_per_bin)
    bins_b = bin_log(b, bin_rpm, request.pull_index_b, request.min_samples_per_bin)
    common = sorted(set(bins_a) & set(bins_b))
    if not common:
        raise telemetry_error(
            "LOG_COMPARE_NO_OVERLAP",
            f"Sem bins de RPM comuns: A {_range(bins_a, bin_rpm)}, B {_range(bins_b, bin_rpm)}.",
            range_a=_range(bins_a, bin_rpm),
            range_b=_range(bins_b, bin_rpm),
        )
    rows: list[ComparisonBin] = []
    for rpm_bin in common:
        x, y = bins_a[rpm_bin], bins_b[rpm_bin]
        lam_delta = None if x.lambda_ is None or y.lambda_ is None else y.lambda_ - x.lambda_
        rows.append(
            ComparisonBin(
                rpm_bin=rpm_bin,
                torque_nm_a=x.torque_nm,
                torque_nm_b=y.torque_nm,
                delta_torque_nm=y.torque_nm - x.torque_nm,
                power_kw_a=x.power_kw,
                power_kw_b=y.power_kw,
                delta_power_kw=y.power_kw - x.power_kw,
                whp_a=x.whp,
                whp_b=y.whp,
                delta_whp=y.whp - x.whp,
                lambda_a=x.lambda_,
                lambda_b=y.lambda_,
                delta_lambda=lam_delta,
                egt_c_a=x.egt_c,
                egt_c_b=y.egt_c,
                delta_egt_c=y.egt_c - x.egt_c,
                knock_intensity_max_a=x.knock_max,
                knock_intensity_max_b=y.knock_max,
                n_a=x.n,
                n_b=y.n,
            )
        )
    peak_whp_a = max(s.whp for s in bins_a.values())
    peak_whp_b = max(s.whp for s in bins_b.values())
    deltas = {
        "torque_nm": [abs(r.delta_torque_nm) for r in rows],
        "power_kw": [abs(r.delta_power_kw) for r in rows],
        "whp": [abs(r.delta_whp) for r in rows],
        "lambda": [abs(r.delta_lambda) for r in rows if r.delta_lambda is not None],
        "egt_c": [abs(r.delta_egt_c) for r in rows],
    }
    return LogComparison(
        a=summary_of(a),
        b=summary_of(b),
        bin_rpm=bin_rpm,
        vehicle_mismatch=a.header.vehicle_id != b.header.vehicle_id,
        bins=rows,
        peak_torque_nm_a=max(s.torque_nm for s in bins_a.values()),
        peak_torque_nm_b=max(s.torque_nm for s in bins_b.values()),
        peak_whp_a=peak_whp_a,
        peak_whp_b=peak_whp_b,
        delta_peak_whp_pct=(peak_whp_b - peak_whp_a) / peak_whp_a * 100.0 if peak_whp_a else 0.0,
        max_abs_delta={k: max(v) if v else 0.0 for k, v in deltas.items()},
        bins_only_in_a=len(set(bins_a) - set(bins_b)),
        bins_only_in_b=len(set(bins_b) - set(bins_a)),
    )
