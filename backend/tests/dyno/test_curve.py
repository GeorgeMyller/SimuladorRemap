"""Curva: agregação em 25 rpm, suavização, whp/virabrequim, resumo e hash.

T121; dyno RF-11, RF-12, RF-18.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from simremap.dyno.contracts import AmbientConditions, CorrectionStandard, DynoCurvePoint
from simremap.dyno.correction import correction_factor
from simremap.dyno.curve import (
    MAX_CURVE_POINTS,
    CurveAggregator,
    CurveSample,
    MeanAccumulator,
    canonical_curve_json,
    curve_sha256,
    peak_spread_pct,
    smooth_curve,
    summarize,
)
from simremap.dyno.rig import HP_KW

CF1 = correction_factor(CorrectionStandard.NONE, AmbientConditions())


def sample(rpm: float, power_kw: float = 100.0, **over: float) -> CurveSample:
    data: dict[str, float] = {
        "rpm": rpm,
        "t_sim_s": rpm / 1000.0,
        "power_wheel_kw": power_kw,
        "power_crank_kw": power_kw / 0.85,
        "torque_wheel_nm": power_kw * 10.0,
        "torque_engine_nm": power_kw * 2.0,
        "lambda_": 0.85,
        "afr": 0.85 * 13.2,
        "egt_c": 850.0,
        "map_kpa": 220.0,
        "iat_c": 40.0,
        "ect_c": 90.0,
        "oil_c": 95.0,
        "ignition_deg_btdc": 18.0,
        "knock_retard_max_deg": 0.0,
        "pedal_pct": 100.0,
    }
    data.update(over)
    return CurveSample(**data)


def test_aggregation_in_25_rpm_bins_with_means_and_max_knock() -> None:
    agg = CurveAggregator()
    agg.add(sample(2001.0, 100.0))
    agg.add(sample(2010.0, 110.0, knock_retard_max_deg=2.0))
    agg.add(sample(2013.0, 120.0))  # arredonda para 2025
    agg.add(sample(2049.0, 130.0))  # 2050
    points = agg.points(1.0)
    assert [p.rpm for p in points] == [2000.0, 2025.0, 2050.0]
    assert points[0].power_wheel_kw == pytest.approx(105.0)
    assert points[0].knock_retard_max_deg == 2.0
    assert points[0].power_crank_kw == pytest.approx(105.0 / 0.85)
    assert len(agg) == 3
    assert agg.pedals() == [100.0, 100.0, 100.0]


def test_correction_applied_to_power_and_torque() -> None:
    agg = CurveAggregator()
    agg.add(sample(3000.0, 150.0))
    (point,) = agg.points(1.05)
    assert point.power_wheel_kw_corr == pytest.approx(150.0 * 1.05)
    assert point.power_crank_kw_corr == pytest.approx(150.0 / 0.85 * 1.05)
    assert point.torque_engine_nm_corr == pytest.approx(300.0 * 1.05)


def test_curve_is_limited_to_400_points() -> None:
    agg = CurveAggregator()
    for i in range(500):
        agg.add(sample(1000.0 + 25.0 * i))
    points = agg.points(1.0)
    assert len(points) <= MAX_CURVE_POINTS
    assert points == sorted(points, key=lambda p: p.rpm)


def _curve(values: list[float]) -> list[DynoCurvePoint]:
    agg = CurveAggregator()
    for i, v in enumerate(values):
        agg.add(sample(2000.0 + 25.0 * i, v))
    return agg.points(1.0)


def test_smoothing_window_one_is_identical_and_window_five_is_centred() -> None:
    raw = _curve([100.0, 110.0, 90.0, 120.0, 80.0, 100.0, 105.0])
    assert smooth_curve(raw, 1) == raw
    smoothed = smooth_curve(raw, 5)
    assert smoothed[3].power_wheel_kw == pytest.approx((110 + 90 + 120 + 80 + 100) / 5)
    # Nas pontas a janela de 5 desloca-se para dentro da curva.
    assert smoothed[0].power_wheel_kw == pytest.approx((100 + 110 + 90 + 120 + 80) / 5)
    assert smoothed[1].power_wheel_kw == smoothed[0].power_wheel_kw
    assert smoothed[-1].power_wheel_kw == pytest.approx((90 + 120 + 80 + 100 + 105) / 5)
    assert smoothed[3].rpm == raw[3].rpm
    with pytest.raises(ValueError, match="ímpar"):
        smooth_curve(raw, 4)
    assert smooth_curve(raw[:1], 5) == raw[:1]


def test_summary_peaks_lambda_window_and_flags() -> None:
    raw = _curve([100.0, 150.0, 160.0, 140.0])
    pedals = [100.0, 100.0, 50.0, 100.0]
    raw[2] = raw[2].model_copy(update={"lambda_": 0.70, "egt_c": 900.0})
    summary = summarize(
        raw,
        raw,
        pedals,
        CF1,
        knock_events=3,
        event_codes=["ramp_not_sustained", "ramp_not_sustained"],
        failure_event_id=None,
    )
    assert summary.peak_whp == pytest.approx(160.0 / HP_KW)
    assert summary.peak_whp_rpm == 2050.0
    assert summary.peak_torque_engine_nm == pytest.approx(320.0)
    assert summary.peak_power_crank_kw == pytest.approx(160.0 / 0.85)
    assert summary.lambda_min == pytest.approx(0.85)  # o ponto a 50 % de pedal é ignorado
    assert summary.egt_max_c == 900.0
    assert summary.knock_events == 3
    assert summary.event_codes == ["ramp_not_sustained"]
    assert summary.correction_factor == 1.0


def test_summary_of_empty_curve() -> None:
    summary = summarize([], [], [], CF1, knock_events=0, event_codes=[], forensic_report_url="/x")
    assert summary.peak_whp == 0.0
    assert summary.forensic_report_url == "/x"


def test_curve_sha256_is_canonical_with_six_decimals() -> None:
    raw = _curve([100.0, 150.0])
    text = canonical_curve_json(raw)
    data = json.loads(text)
    assert list(data[0]) == sorted(data[0])
    assert "lambda" in data[0]
    assert curve_sha256(raw) == hashlib.sha256(text.encode()).hexdigest()
    jitter = [p.model_copy(update={"power_wheel_kw": p.power_wheel_kw + 1e-9}) for p in raw]
    assert curve_sha256(jitter) == curve_sha256(raw)
    changed = [p.model_copy(update={"power_wheel_kw": p.power_wheel_kw + 1e-5}) for p in raw]
    assert curve_sha256(changed) != curve_sha256(raw)
    assert curve_sha256([raw, raw]) != curve_sha256(raw)


def test_peak_spread() -> None:
    assert peak_spread_pct([200.0, 204.0, 202.0]) == pytest.approx(100.0 * 4.0 / 202.0)
    assert peak_spread_pct([200.0]) == 0.0
    assert peak_spread_pct([0.0, 0.0]) == 0.0


def test_mean_accumulator_cell_point() -> None:
    acc = MeanAccumulator()
    acc.add(sample(3000.0, 100.0))
    acc.add(sample(3010.0, 110.0))
    point = acc.point(1.0, cell_index=2, stable=True)
    assert point.cell_index == 2 and point.stable is True
    assert point.rpm == pytest.approx(3005.0)
    assert acc.mean("pedal_pct") == 100.0
