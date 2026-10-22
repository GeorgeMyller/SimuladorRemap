"""Laudo forense: cadeia causal, avisos, recomendações, textos e baseline (T135; RF-22 a RF-26,
RF-29 a RF-31)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from kfm_helpers import (
    RUN,
    T0,
    Driver,
    ModelFactory,
    StateOverrides,
    dyno_run,
    lucas_report,
    make_ecu,
    make_event,
    run_lucas,
)

from simremap.damage.errors import DamageError
from simremap.damage.forensic import (
    build_forensic_report,
    build_minimal_report,
    canonical_json,
    report_sha256,
)
from simremap.damage.forensic.recommend import TableGrid, compute_calibration_diff
from simremap.damage.model import DamageModel

BASELINE_RUN = "01JAB0000000000000000000BB"
FORMULA_MARKS = ("=", "τ", "I_LW", "^", "Σ", "exp(", "θ")


def fixed_overrides(over: dict[str, Any]) -> StateOverrides:
    """Sobrescritas constantes no tempo (fecha ``over`` por valor, não pela variável do laço)."""
    return lambda _t: over


@pytest.fixture
def lucas_model(make_model: ModelFactory) -> DamageModel:
    model = make_model()
    run_lucas(model)
    assert model.engine_locked
    return model


class TestCausalChain:
    def test_lucas_chain_order(self, lucas_model: DamageModel) -> None:
        report = lucas_report(lucas_model)
        chain = report.causal_chain
        assert 3 <= len(chain) <= 12
        assert [c.order for c in chain] == list(range(1, len(chain) + 1))
        times = [c.t_sim_s for c in chain]
        assert times == sorted(times)
        assert report.failure_event is not None
        assert chain[-1].kind == "failure" and chain[-1].t_sim_s == report.failure_event.t_sim_s
        assert all(t <= report.failure_event.t_sim_s for t in times)
        kinds = [c.kind for c in chain]
        expected = ["calibration", "operating_point", "combustion", "ecu_response", "combustion"]
        assert kinds[: len(expected)] == expected
        assert "damage" in kinds
        moderate, severe = (c for c in chain if c.kind == "combustion")
        assert moderate.t_sim_s == pytest.approx(1.0, abs=0.03)
        assert severe.t_sim_s == pytest.approx(2.0, abs=0.03) and severe.cylinder == 3
        assert chain[0].variable == "boost_target_kpa" and chain[0].value == 280.0
        assert report.primary_mode is not None and report.primary_mode.value == "piston_failure"

    def test_calibration_link_from_baseline_diff(self, lucas_model: DamageModel) -> None:
        diff = _lucas_diff()
        report = lucas_report(lucas_model, baseline=dyno_run(BASELINE_RUN, "completed"), diff=diff)
        variables = [c.variable for c in report.causal_chain if c.kind == "calibration"]
        assert variables == ["boost_target", "ignition_base"]
        assert report.calibration_diff == diff

    def test_other_families(self, make_model: ModelFactory) -> None:
        cases = {
            "turbine_creep": ({"egt_collector_c": 1010.0}, 0.0, "egt_collector_c"),
            "rod_overload": ({"torque_nm": 440.0}, 5000.0, "torque_nm"),
            "turbo_overspeed_burst": ({"turbo_rpm": 236_000.0}, 0.0, "turbo_rpm"),
            "valve_piston_contact": ({}, 7800.0, "rpm"),
        }
        for mechanism, (over, rpm, variable) in cases.items():
            model = make_model()
            model.set_run(RUN)
            Driver(model, rpm, state_overrides=fixed_overrides(over)).advance(
                30.0, until_locked=True
            )
            report = build_forensic_report(
                model.freeze_trace(), dyno_run(), None, None, "failure", created_at=T0
            )
            assert report.failure_event is not None
            assert report.failure_event.mechanism.value == mechanism
            assert 3 <= len(report.causal_chain) or mechanism.startswith(("turbo_", "valve"))
            ops = [c for c in report.causal_chain if c.kind == "operating_point"]
            assert ops and ops[0].variable.startswith(variable[:3])

    def test_preignition_chain(self, make_model: ModelFactory) -> None:
        model = make_model()
        model.set_run(RUN)
        thr = model.hot_spot_threshold_c
        Driver(
            model,
            5000.0,
            event_factory=lambda c, t, r: make_event(c, t, r, p_max_kpa=10_000.0, imep_kpa=900.0),
            state_overrides=lambda _t: {"hot_spot_temp_c": thr + 100.0, "iat_c": 65.0},
        ).advance(5.0, until_locked=True)
        report = build_forensic_report(
            model.freeze_trace(), dyno_run(), None, None, "failure", created_at=T0
        )
        variables = [c.variable for c in report.causal_chain]
        assert "p_preignition_kpa" in variables and "iat_c" in variables
        rules = {r.rule_id for r in report.recommendations}
        assert "R-PI-01" in rules
        signals = {w.signal for w in report.early_warnings}
        assert {"iat_high", "hot_spot_near_threshold"} <= signals


class TestWarnings:
    def test_knock_retard_rising_lead_time(self, make_model: ModelFactory) -> None:
        probe = make_model()
        run_lucas(probe, ecu=lambda _t: make_ecu())
        t_f = next(f for f in probe.failures if f.catastrophic).t_sim_s
        step_t = round(t_f - 3.0, 3)
        model = make_model()
        run_lucas(model, ecu=lambda t: make_ecu(retard=[3.0 if t >= step_t else 0.0, 0, 0, 0]))
        report = lucas_report(model)
        rising = next(w for w in report.early_warnings if w.signal == "knock_retard_rising")
        assert rising.lead_time_s == pytest.approx(3.0, abs=0.02)
        assert rising.cylinder == 1

    def test_lucas_warnings(self, lucas_model: DamageModel) -> None:
        report = lucas_report(lucas_model)
        signals = {w.signal for w in report.early_warnings}
        assert {"first_moderate_knock", "knock_retard_saturated", "component_health_low"} <= signals
        assert max(w.lead_time_s for w in report.early_warnings) >= 1.0
        assert all(w.lead_time_s >= 0.0 for w in report.early_warnings)

    def test_load_warnings(self, make_model: ModelFactory) -> None:
        model = make_model()
        model.set_run(RUN)
        Driver(
            model,
            5000.0,
            state_overrides=lambda _t: {
                "torque_nm": 440.0,
                "egt_collector_c": 930.0,
                "turbo_rpm": 205_000.0,
                "lambda_collector": 0.92,
            },
        ).advance(20.0, until_locked=True)
        report = build_forensic_report(
            model.freeze_trace(), dyno_run(), None, None, "failure", created_at=T0
        )
        signals = {w.signal for w in report.early_warnings}
        assert {
            "rod_torque_near_limit",
            "egt_near_limit",
            "turbo_speed_near_limit",
            "lean_under_load",
        } <= signals
        rules = {r.rule_id for r in report.recommendations}
        assert {"R-ROD-01", "R-LAMBDA-01"} <= rules


def _grid(value: float) -> TableGrid:
    rpm = (1000.0, 3000.0, 5000.0, 7000.0)
    load = (50.0, 150.0, 250.0)
    return TableGrid(rpm, load, tuple(tuple(value for _ in rpm) for _ in load))


def _lucas_diff() -> Any:
    tables = {
        "boost_target": [(_grid(280.0), _grid(180.0))],
        "ignition_base": [(_grid(26.0), _grid(18.0))],
        "lambda_target": [(_grid(0.86), _grid(0.86))],
        "ignition_trim_cyl": [(_grid(0.0), _grid(0.0)) for _ in range(4)],
    }
    return compute_calibration_diff(
        BASELINE_RUN, "b" * 64, tables, (2000.0, 6300.0), (100.0, 280.0)
    )


class TestRecommendations:
    def test_lucas_rules(self, lucas_model: DamageModel) -> None:
        report = lucas_report(lucas_model)
        by_rule = {r.rule_id: r for r in report.recommendations}
        knock = by_rule["R-KNOCK-01"]
        assert knock.table_id == "ignition_trim_cyl" and knock.cylinders == [2, 3]
        assert (knock.value_min, knock.value_max) == (2.0, 4.0)
        assert knock.region is not None and "rpm 5000" in knock.region
        lam = by_rule["R-LAMBDA-01"]
        assert lam.table_id == "lambda_target" and (lam.value_min, lam.value_max) == (0.78, 0.82)
        assert "R-BOOST-01" in by_rule  # 280 kPa > 180 + 50 com knock
        assert len(report.recommendations) <= 8

    def test_calibration_diff_against_baseline(self) -> None:
        diff = _lucas_diff()
        deltas = {d.table_id: d for d in diff.deltas}
        assert deltas["boost_target"].max_delta == pytest.approx(100.0, abs=1.0)
        assert deltas["ignition_base"].max_delta == pytest.approx(8.0, abs=0.1)
        assert deltas["lambda_target"].max_delta == 0.0
        assert deltas["boost_target"].at_rpm in (3000.0, 5000.0)

    def test_no_baseline_means_no_diff(self, lucas_model: DamageModel) -> None:
        report = lucas_report(lucas_model, diff=_lucas_diff())
        assert report.calibration_diff is None

    def test_axes_must_match(self) -> None:
        other = TableGrid((1.0, 2.0), (1.0, 2.0), ((0.0, 0.0), (0.0, 0.0)))
        with pytest.raises(ValueError, match="eixos"):
            compute_calibration_diff(
                BASELINE_RUN, "b" * 64, {"boost_target": [(other, _grid(1.0))]}, (0, 1), (0, 1)
            )


class TestTexts:
    def test_three_audiences(self, lucas_model: DamageModel) -> None:
        report = lucas_report(lucas_model)
        assert set(report.texts) == {"beginner", "intermediate", "instructor"}
        beginner = report.texts["beginner"]
        body = beginner.title + beginner.summary + beginner.explanation
        assert not any(mark in body for mark in FORMULA_MARKS)
        assert "lambda para 0,78–0,82" in beginner.explanation
        assert beginner.questions == []
        instructor = report.texts["instructor"]
        assert "I_LW" in instructor.explanation and "θ_k" in instructor.explanation
        assert "MAPO" in instructor.explanation and "800 kPa" in instructor.explanation
        assert 2 <= len(instructor.questions) <= 5
        assert "cilindro 2" in instructor.questions[0] or "cilindro 3" in instructor.questions[0]
        assert "R-KNOCK-01" in report.texts["intermediate"].explanation


class TestIntegrity:
    def test_sha_is_deterministic_and_size_bounded(self, make_model: ModelFactory) -> None:
        reports = []
        for created in (T0, datetime(2027, 1, 1, tzinfo=UTC)):
            model = make_model()
            run_lucas(model)
            reports.append(lucas_report(model, created_at=created))
        first, second = reports
        assert first.report_sha256 == second.report_sha256
        assert first.report_id == second.report_id
        assert report_sha256(first) == first.report_sha256
        raw = first.model_dump(mode="json")
        assert len(canonical_json(raw)) <= 64 * 1024
        assert len(json.dumps(raw).encode()) <= 64 * 1024
        assert len(first.lw_trace) <= 200 and first.lw_trace

    def test_windows_and_truncation(
        self, lucas_model: DamageModel, make_model: ModelFactory
    ) -> None:
        report = lucas_report(lucas_model)
        assert report.buffer_truncated  # falha antes de 10 s de buffer
        assert [w.name for w in report.time_windows] == ["before", "warning", "collapse"]
        long_model = make_model()
        long_model.set_run(RUN)
        Driver(long_model, 3000.0, state_overrides=lambda _t: {"egt_collector_c": 1010.0}).advance(
            30.0, until_locked=True
        )
        long_report = build_forensic_report(
            long_model.freeze_trace(), dyno_run(), None, None, "failure", created_at=T0
        )
        assert not long_report.buffer_truncated
        before = long_report.time_windows[0]
        assert before.t_end_s - before.t_start_s == pytest.approx(7.0)
        assert before.stats["egt_collector_c"].max == 1010.0

    def test_failure_report_requires_failure(self, make_model: ModelFactory) -> None:
        model = make_model()
        Driver(model, 3000.0).advance(0.5)
        with pytest.raises(DamageError):
            build_forensic_report(model.freeze_trace(), dyno_run(), None, None, "failure")


class TestNearMiss:
    def test_damage_off_virtual_failure(self, make_model: ModelFactory) -> None:
        model = make_model(damage_enabled=False)
        run_lucas(model, seconds=10.0)
        assert not model.engine_locked
        report = lucas_report(model, kind="near_miss")
        assert report.report_kind == "near_miss" and report.simulated_only
        assert report.failure_event is not None and report.failure_event.simulated_only
        assert not report.failure_event.catastrophic
        damaged = {c.component_id for c in report.damaged_components}
        assert "piston:3" in damaged

    def test_protection_abort_without_failure(self, make_model: ModelFactory) -> None:
        model = make_model()
        run_lucas(model, seconds=2.5)
        assert not model.engine_locked
        report = build_forensic_report(
            model.freeze_trace(),
            dyno_run(state="aborted", abort_reason="severe_knock_protection"),
            None,
            None,
            "near_miss",
            created_at=T0,
        )
        assert report.failure_event is None and report.primary_mode is None
        assert report.causal_chain[-1].kind == "warning"
        assert report.texts["beginner"].title.startswith("Quase falha")

    def test_minimal_report(self, lucas_model: DamageModel) -> None:
        report = build_minimal_report(lucas_model.freeze_trace(), dyno_run(), "failure")
        assert len(report.causal_chain) == 1 and report.causal_chain[0].kind == "failure"
        assert report_sha256(report) == report.report_sha256
        near = build_minimal_report(lucas_model.freeze_trace(), dyno_run(), "near_miss")
        assert near.causal_chain[0].kind == "warning"
