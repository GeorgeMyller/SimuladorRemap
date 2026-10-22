"""Curva da puxada: agregação em 25 rpm, suavização, resumo e hash (dyno RF-11, RF-12, RF-18; D-11).

- Agregação: cada amostra medida em ``running`` cai no intervalo
  ``round(rpm / 25) · 25``; o ponto guarda a média das grandezas (``knock_retard_max_deg``
  guarda o máximo). ``steady_state_hold`` gera um ponto médio por célula.
- Correção (fator constante por puxada) aplicada a potência e torque.
- Suavização: média móvel centrada de janela ímpar 1..11 sobre os pontos agregados; nas
  pontas a janela mantém o tamanho e desloca-se para dentro da curva (o último ponto não
  fica com janela 1, o que tornaria o pico sensível ao ruído). ``window = 1`` devolve a
  curva bruta.
- Resumo: picos sobre a curva suavizada e corrigida (janela do pedido); lambda mínimo e
  máximo só nos pontos com pedal ≥ 90 %; EGT e IAT máximas sobre a curva bruta.
- ``curve_sha256``: SHA-256 do JSON da curva bruta com chaves ordenadas, floats a 6 casas
  e separadores ``(",", ":")``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from simremap.dyno.contracts import DynoCurvePoint, RunSummary
from simremap.dyno.correction import CorrectionResult
from simremap.dyno.rig import HP_KW

__all__ = [
    "BIN_RPM",
    "MAX_CURVE_POINTS",
    "CurveAggregator",
    "CurveSample",
    "MeanAccumulator",
    "canonical_curve_json",
    "curve_sha256",
    "peak_spread_pct",
    "smooth_curve",
    "summarize",
]

BIN_RPM: Final = 25.0
MAX_CURVE_POINTS: Final = 400
LAMBDA_PEDAL_MIN_PCT: Final = 90.0

_MEAN_FIELDS: Final = (
    "rpm",
    "t_sim_s",
    "power_wheel_kw",
    "power_crank_kw",
    "torque_wheel_nm",
    "torque_engine_nm",
    "lambda_",
    "afr",
    "egt_c",
    "map_kpa",
    "iat_c",
    "ect_c",
    "oil_c",
    "ignition_deg_btdc",
    "pedal_pct",
)
_SMOOTH_FIELDS: Final = (
    "power_wheel_kw",
    "power_wheel_kw_corr",
    "power_crank_kw",
    "power_crank_kw_corr",
    "torque_wheel_nm",
    "torque_engine_nm",
    "torque_engine_nm_corr",
    "lambda_",
    "afr",
    "egt_c",
    "map_kpa",
    "iat_c",
    "ect_c",
    "oil_c",
    "ignition_deg_btdc",
    "knock_retard_max_deg",
)


@dataclass(slots=True)
class CurveSample:
    """Amostra medida num tick (alinhada com a aceleração do rolo)."""

    rpm: float
    t_sim_s: float
    power_wheel_kw: float
    power_crank_kw: float
    torque_wheel_nm: float
    torque_engine_nm: float
    lambda_: float
    afr: float
    egt_c: float
    map_kpa: float
    iat_c: float
    ect_c: float
    oil_c: float
    ignition_deg_btdc: float
    knock_retard_max_deg: float
    pedal_pct: float


@dataclass(slots=True)
class MeanAccumulator:
    """Somas de um intervalo de rpm ou de uma célula."""

    sums: list[float] = field(default_factory=lambda: [0.0] * len(_MEAN_FIELDS))
    count: int = 0
    knock_max: float = 0.0

    def add(self, s: CurveSample) -> None:
        sums = self.sums
        for i, name in enumerate(_MEAN_FIELDS):
            sums[i] += getattr(s, name)
        self.count += 1
        self.knock_max = max(self.knock_max, s.knock_retard_max_deg)

    def mean(self, name: str) -> float:
        return self.sums[_MEAN_FIELDS.index(name)] / max(self.count, 1)

    def point(
        self,
        correction: float,
        *,
        rpm: float | None = None,
        cell_index: int | None = None,
        stable: bool | None = None,
    ) -> DynoCurvePoint:
        m = self.mean
        p_wheel = m("power_wheel_kw")
        p_crank = m("power_crank_kw")
        t_eng = m("torque_engine_nm")
        return DynoCurvePoint.model_validate(
            {
                "rpm": max(m("rpm") if rpm is None else rpm, 0.0),
                "t_sim_s": max(m("t_sim_s"), 0.0),
                "power_wheel_kw": p_wheel,
                "power_wheel_kw_corr": p_wheel * correction,
                "power_crank_kw": p_crank,
                "power_crank_kw_corr": p_crank * correction,
                "torque_wheel_nm": m("torque_wheel_nm"),
                "torque_engine_nm": t_eng,
                "torque_engine_nm_corr": t_eng * correction,
                "lambda": max(m("lambda_"), 0.0),
                "afr": max(m("afr"), 0.0),
                "egt_c": m("egt_c"),
                "map_kpa": max(m("map_kpa"), 0.0),
                "iat_c": m("iat_c"),
                "ect_c": m("ect_c"),
                "oil_c": m("oil_c"),
                "ignition_deg_btdc": m("ignition_deg_btdc"),
                "knock_retard_max_deg": max(self.knock_max, 0.0),
                "cell_index": cell_index,
                "stable": stable,
            }
        )


class CurveAggregator:
    """Agrega amostras em intervalos de 25 rpm (≤ 400 pontos por puxada)."""

    __slots__ = ("_bins", "bin_rpm")

    def __init__(self, bin_rpm: float = BIN_RPM) -> None:
        self.bin_rpm = bin_rpm
        self._bins: dict[int, MeanAccumulator] = {}

    def __len__(self) -> int:
        return len(self._bins)

    def add(self, sample: CurveSample) -> None:
        index = math.floor(sample.rpm / self.bin_rpm + 0.5)
        acc = self._bins.get(index)
        if acc is None:
            acc = MeanAccumulator()
            self._bins[index] = acc
        acc.add(sample)

    def pedals(self) -> list[float]:
        return [self._bins[i].mean("pedal_pct") for i in sorted(self._bins)]

    def points(self, correction: float) -> list[DynoCurvePoint]:
        indices = sorted(self._bins)
        if len(indices) > MAX_CURVE_POINTS:  # agrupa pares até caber em 400 pontos
            merged: dict[int, MeanAccumulator] = {}
            stride = math.ceil(len(indices) / MAX_CURVE_POINTS)
            for pos, idx in enumerate(indices):
                key = indices[pos - pos % stride]
                target = merged.setdefault(key, MeanAccumulator())
                src = self._bins[idx]
                target.sums = [a + b for a, b in zip(target.sums, src.sums, strict=True)]
                target.count += src.count
                target.knock_max = max(target.knock_max, src.knock_max)
            return [merged[i].point(correction) for i in sorted(merged)]
        return [self._bins[i].point(correction, rpm=i * self.bin_rpm) for i in indices]


def smooth_curve(points: Sequence[DynoCurvePoint], window: int) -> list[DynoCurvePoint]:
    """Média móvel centrada (janela ímpar); ``window = 1`` devolve cópia idêntica."""
    if window < 1 or window % 2 == 0:
        raise ValueError("smoothing_window deve ser ímpar e ≥ 1")
    if window == 1 or len(points) < 2:  # noqa: PLR2004
        return list(points)
    half = window // 2
    n = len(points)
    columns = {name: [getattr(p, name) for p in points] for name in _SMOOTH_FIELDS}
    out: list[DynoCurvePoint] = []
    size = min(window, n)
    for i, point in enumerate(points):
        lo = min(max(i - half, 0), n - size)
        hi = lo + size
        update = {name: math.fsum(col[lo:hi]) / (hi - lo) for name, col in columns.items()}
        out.append(point.model_copy(update=update))
    return out


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6) + 0.0  # normaliza -0.0
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def canonical_curve_json(
    curve: Iterable[DynoCurvePoint] | Iterable[Iterable[DynoCurvePoint]],
) -> str:
    """JSON canónico de uma curva (ou lista de curvas do ``multi_pull``)."""
    data: list[Any] = []
    for item in curve:
        if isinstance(item, DynoCurvePoint):
            data.append(item.model_dump(mode="json", by_alias=True))
        else:
            data.append([p.model_dump(mode="json", by_alias=True) for p in item])
    return json.dumps(_round(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def curve_sha256(
    curve: Iterable[DynoCurvePoint] | Iterable[Iterable[DynoCurvePoint]],
) -> str:
    """SHA-256 hex da curva bruta canónica (RNF-03)."""
    return hashlib.sha256(canonical_curve_json(curve).encode("utf-8")).hexdigest()


def summarize(
    raw: Sequence[DynoCurvePoint],
    smoothed: Sequence[DynoCurvePoint],
    pedals: Sequence[float],
    correction: CorrectionResult,
    *,
    knock_events: int,
    event_codes: Iterable[str],
    failure_event_id: str | None = None,
    forensic_report_url: str | None = None,
) -> RunSummary:
    """``RunSummary`` da puxada (RF-18)."""
    codes = sorted(set(event_codes))
    if not smoothed:
        return RunSummary(
            peak_whp=0.0,
            peak_whp_rpm=0.0,
            peak_power_crank_kw=0.0,
            peak_torque_engine_nm=0.0,
            peak_torque_rpm=0.0,
            lambda_min=0.0,
            lambda_max=0.0,
            egt_max_c=0.0,
            iat_max_c=0.0,
            correction_factor=correction.factor,
            correction_out_of_range=correction.out_of_range,
            knock_events=knock_events,
            event_codes=codes,
            failure_event_id=failure_event_id,
            forensic_report_url=forensic_report_url,
        )
    p_peak = max(smoothed, key=lambda p: p.power_wheel_kw_corr)
    t_peak = max(smoothed, key=lambda p: p.torque_engine_nm_corr)
    wot = [
        p.lambda_ for p, ped in zip(smoothed, pedals, strict=False) if ped >= LAMBDA_PEDAL_MIN_PCT
    ]
    wot = [lam for lam in wot if lam > 0.0]
    return RunSummary(
        peak_whp=p_peak.power_wheel_kw_corr / HP_KW,
        peak_whp_rpm=p_peak.rpm,
        peak_power_crank_kw=max(p.power_crank_kw_corr for p in smoothed),
        peak_torque_engine_nm=t_peak.torque_engine_nm_corr,
        peak_torque_rpm=t_peak.rpm,
        lambda_min=min(wot) if wot else 0.0,
        lambda_max=max(wot) if wot else 0.0,
        egt_max_c=max(p.egt_c for p in raw),
        iat_max_c=max(p.iat_c for p in raw),
        correction_factor=correction.factor,
        correction_out_of_range=correction.out_of_range,
        knock_events=knock_events,
        event_codes=codes,
        failure_event_id=failure_event_id,
        forensic_report_url=forensic_report_url,
    )


def peak_spread_pct(values: Sequence[float]) -> float:
    """``100 · (max − min) / média`` (0 com menos de 2 valores ou média nula)."""
    if len(values) < 2:  # noqa: PLR2004
        return 0.0
    mean = math.fsum(values) / len(values)
    if mean == 0.0:
        return 0.0
    return 100.0 * (max(values) - min(values)) / mean
