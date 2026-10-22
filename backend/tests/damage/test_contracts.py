"""Contratos e configuração do modelo de dano (T045 a T047; damage RF-10 a RF-25)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from kfm_helpers import spec_config
from pydantic import ValidationError

from simremap.damage.config import (
    DAMAGE_CONFIG_VERSION,
    DAMAGE_FEATURES,
    DEFAULT_DAMAGE_CONFIG,
    DamageConfig,
)
from simremap.damage.contracts import (
    CausalLink,
    ChannelStats,
    ComponentHealth,
    DamageState,
    EarlyWarning,
    EngineHealth,
    EngineRestoreRequest,
    FailureEvent,
    FailureMechanism,
    FailureMode,
    ForensicReport,
    KnockClass,
    KnockObservation,
    KnockSignal,
    Recommendation,
    TimeWindow,
    classify_knock,
    integrity_pct,
)

ULID = "01JAB0000000000000000000AB"
RUN = "01JAB0000000000000000000CD"
SESSION = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"
SHA = "d" * 64


def hatch_components() -> list[ComponentHealth]:
    comps = [
        ComponentHealth(component_id=f"{kind}:{k}", kind=kind, cylinder=k)
        for k in range(1, 5)
        for kind in ("piston", "rod", "valves")
    ]
    comps += [
        ComponentHealth(component_id="head_gasket", kind="head_gasket"),
        ComponentHealth(component_id="bearings", kind="bearings"),
        ComponentHealth(component_id="turbo:turbine", kind="turbine"),
    ]
    return comps


def failure(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "failure_event_id": ULID,
        "session_id": SESSION,
        "run_id": RUN,
        "tick": 13118,
        "t_sim_s": 13.118,
        "cylinder": 3,
        "component_id": "piston:3",
        "mode": "piston_failure",
        "mechanism": "knock_erosion",
        "catastrophic": True,
        "health_after": 0.0,
        "causal_variables": {"knock_intensity": 1.0},
    }
    data.update(over)
    return data


def observation(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "cylinder": 1,
        "t_sim_s": 1.0,
        "rpm": 6000.0,
        "lw_integral_end": 1.2,
        "theta_onset_deg_atdc": 14.0,
        "burned_fraction_onset": 0.6,
        "autoignited_fraction": 0.2,
        "mapo_kpa": 640.0,
        "intensity": 6.4,
        "knock_energy_j": 387.0,
        "knock_class": "severe",
        "in_sensor_window": True,
    }
    data.update(over)
    return data


def report(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "report_id": ULID,
        "report_kind": "failure",
        "run_id": RUN,
        "session_id": SESSION,
        "vehicle_id": "hatch-20t-gdi",
        "fuel_id": "e27",
        "calibration_hash": SHA,
        "seed": 1,
        "sim_hz": 1000,
        "failure_event": failure(),
        "primary_mode": "piston_failure",
        "damaged_components": [],
        "causal_chain": [
            {
                "order": 1,
                "t_sim_s": 10.0,
                "kind": "calibration",
                "variable": "boost_target_kpa",
                "value": 260.0,
                "unit": "kPa",
                "description": "boost acima da base",
            },
            {
                "order": 2,
                "t_sim_s": 13.118,
                "kind": "failure",
                "variable": "health",
                "value": 0.0,
                "unit": "-",
                "description": "falha do pistão",
            },
        ],
        "time_windows": [
            {
                "name": "before",
                "t_start_s": 3.1,
                "t_end_s": 10.1,
                "stats": {"rpm": {"min": 3000, "max": 6000, "mean": 4500, "unit": "rpm"}},
            }
        ],
        "early_warnings": [],
        "recommendations": [],
        "texts": {"beginner": {"title": "t", "summary": "s", "explanation": "e"}},
        "generator_version": "1.0.0",
        "report_sha256": SHA,
        "created_at": "2026-10-18T10:00:00Z",
    }
    data.update(over)
    return data


class TestComponentHealth:
    def test_hatch_has_15_components(self) -> None:
        comps = hatch_components()
        assert len(comps) == 15
        assert all(c.health == 1.0 and c.virtual_health == 1.0 for c in comps)

    @pytest.mark.parametrize(
        "data",
        [
            {"component_id": "piston:9", "kind": "piston", "cylinder": 9},
            {"component_id": "piston:1", "kind": "rod", "cylinder": 1},
            {"component_id": "piston:1", "kind": "piston", "cylinder": 2},
            {"component_id": "piston:1", "kind": "piston"},
            {"component_id": "bearings", "kind": "bearings", "cylinder": 1},
            {"component_id": "turbine", "kind": "turbine"},
            {"component_id": "bearings", "kind": "bearings", "health": 1.1},
            {"component_id": "bearings", "kind": "bearings", "damage_by_cause": {"magic": 0.1}},
            {"component_id": "bearings", "kind": "bearings", "damage_by_cause": {"knock": -0.1}},
        ],
    )
    def test_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ComponentHealth.model_validate(data)


class TestKnock:
    @pytest.mark.parametrize(
        ("intensity", "klass"),
        [
            (0.0, KnockClass.NONE),
            (0.29, KnockClass.NONE),
            (0.3, KnockClass.LIGHT),
            (1.0, KnockClass.MODERATE),
            (2.99, KnockClass.MODERATE),
            (3.0, KnockClass.SEVERE),
        ],
    )
    def test_classify(self, intensity: float, klass: KnockClass) -> None:
        assert classify_knock(intensity) == klass

    def test_observation(self) -> None:
        obs = KnockObservation.model_validate(observation())
        assert obs.preignition == "none"
        assert KnockObservation.model_validate_json(obs.model_dump_json()) == obs
        with pytest.raises(ValidationError, match="incoerente"):
            KnockObservation.model_validate(observation(knock_class="light"))
        with pytest.raises(ValidationError):
            KnockObservation.model_validate(observation(preignition="other"))


class TestFailureAndState:
    def test_failure_event(self) -> None:
        ev = FailureEvent.model_validate(failure())
        assert ev.simulated_only is False
        assert FailureEvent.model_validate_json(ev.model_dump_json()) == ev
        assert len(FailureMode.values()) == 6
        assert len(FailureMechanism.values()) == 13

    @pytest.mark.parametrize(
        "over",
        [
            {"mode": "meltdown"},
            {"mechanism": "rust"},
            {"health_after": 1.5},
            {"component_id": "piston:2"},
            {"tick": -1},
            {"failure_event_id": "short"},
        ],
    )
    def test_failure_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            FailureEvent.model_validate(failure(**over))

    def test_failure_outside_run(self) -> None:
        ev = FailureEvent.model_validate(
            failure(run_id=None, cylinder=None, component_id="bearings", mode="rod_failure")
        )
        assert ev.run_id is None

    def test_damage_state(self) -> None:
        state = DamageState(
            t_sim_s=1.0,
            tick=1000,
            damage_enabled=True,
            engine_locked=False,
            components=hatch_components(),
            knock_last=[KnockObservation.model_validate(observation()), None, None, None],
            knock_signal=KnockSignal.silent(4),
            piston_temp_eff_c=[300.0] * 4,
        )
        assert DamageState.model_validate_json(state.model_dump_json()) == state
        data = state.model_dump()
        with pytest.raises(ValidationError, match="n_cyl"):
            DamageState.model_validate(data | {"piston_temp_eff_c": [300.0] * 3})
        with pytest.raises(ValidationError, match="cilindro"):
            DamageState.model_validate(data | {"knock_last": [None, observation(), None, None]})
        with pytest.raises(ValidationError, match="duplicado"):
            DamageState.model_validate(data | {"components": data["components"] * 2})


class TestEngineHealth:
    def test_build_intact(self) -> None:
        health = EngineHealth.build(
            session_id=SESSION,
            vehicle_id="hatch-20t-gdi",
            t_sim_s=0.0,
            damage_enabled=True,
            engine_locked=False,
            components=hatch_components(),
        )
        assert health.integrity_pct == 100.0
        assert health.intact
        assert EngineHealth.model_validate_json(health.model_dump_json()) == health

    def test_build_damaged(self) -> None:
        comps = hatch_components()
        comps[0] = comps[0].model_copy(update={"health": 0.4567})
        health = EngineHealth.build(
            session_id=SESSION,
            vehicle_id="hatch-20t-gdi",
            t_sim_s=2.0,
            damage_enabled=True,
            engine_locked=True,
            components=comps,
            restore_count=2,
        )
        assert health.min_health == 0.4567
        assert health.integrity_pct == 45.6
        assert not health.intact
        assert integrity_pct(0.999) == 99.9

    def test_incoherent(self) -> None:
        good = EngineHealth.build(
            session_id=SESSION,
            vehicle_id="hatch-20t-gdi",
            t_sim_s=0.0,
            damage_enabled=True,
            engine_locked=False,
            components=hatch_components(),
        ).model_dump()
        for over in ({"min_health": 0.5}, {"integrity_pct": 99.0}, {"intact": False}):
            with pytest.raises(ValidationError):
                EngineHealth.model_validate(good | over)

    def test_restore_request(self) -> None:
        assert EngineRestoreRequest().note is None
        with pytest.raises(ValidationError):
            EngineRestoreRequest(note="x" * 121)


class TestForensic:
    def test_report_round_trip(self) -> None:
        rep = ForensicReport.model_validate(report())
        assert rep.created_at == datetime(2026, 10, 18, 10, tzinfo=UTC)
        assert ForensicReport.model_validate_json(rep.model_dump_json()) == rep

    def test_near_miss_without_event(self) -> None:
        rep = ForensicReport.model_validate(
            report(report_kind="near_miss", failure_event=None, primary_mode=None)
        )
        assert rep.failure_event is None

    @pytest.mark.parametrize(
        "over",
        [
            {"failure_event": None, "primary_mode": None},
            {"primary_mode": "rod_failure"},
            {"causal_chain": []},
            {"generator_version": "v1"},
            {"texts": {"expert": {"title": "t", "summary": "s", "explanation": "e"}}},
            {"created_at": "2026-10-18T10:00:00"},
        ],
    )
    def test_report_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ForensicReport.model_validate(report(**over))

    def test_chain_rules(self) -> None:
        chain = report()["causal_chain"]
        late = [chain[0] | {"t_sim_s": 20.0, "order": 1}, chain[1] | {"order": 2}]
        with pytest.raises(ValidationError, match="crescente"):
            ForensicReport.model_validate(report(causal_chain=late))
        gap = [chain[0], chain[1] | {"order": 3}]
        with pytest.raises(ValidationError, match="lacunas"):
            ForensicReport.model_validate(report(causal_chain=gap))
        after = [chain[0], chain[1] | {"t_sim_s": 14.0}]
        with pytest.raises(ValidationError, match="posterior"):
            ForensicReport.model_validate(report(causal_chain=after))
        with pytest.raises(ValidationError):
            ForensicReport.model_validate(report(causal_chain=[chain[0]] * 13))

    def test_parts(self) -> None:
        rec = Recommendation(
            rule_id="R-KNOCK-01",
            action="retirar 2–4°",
            table_id="ignition_trim_cyl",
            cylinders=[3],
            value_min=2.0,
            value_max=4.0,
            unit="°",
            rationale="knock severo no cilindro 3",
        )
        assert Recommendation.model_validate_json(rec.model_dump_json()) == rec
        with pytest.raises(ValidationError):
            Recommendation.model_validate(rec.model_dump() | {"rule_id": "knock-1"})
        with pytest.raises(ValidationError):
            Recommendation.model_validate(rec.model_dump() | {"value_min": 5.0})
        EarlyWarning(
            signal="knock_retard_rising",
            t_sim_s=10.1,
            lead_time_s=3.0,
            value=4.0,
            threshold=2.0,
            unit="°",
        )
        with pytest.raises(ValidationError):
            ChannelStats(min=2.0, max=1.0, mean=1.5, unit="-")
        with pytest.raises(ValidationError):
            TimeWindow(name="warning", t_start_s=5.0, t_end_s=4.0, stats={})
        with pytest.raises(ValidationError):
            CausalLink(
                order=0, t_sim_s=0, kind="damage", variable="x", value=1, unit="-", description=""
            )


class TestDamageConfig:
    def test_defaults_match_spec(self) -> None:
        cfg = DEFAULT_DAMAGE_CONFIG
        assert cfg.config_version == DAMAGE_CONFIG_VERSION
        assert cfg.features == DAMAGE_FEATURES
        assert (cfg.i_safe, cfg.c_knock, cfg.head_gasket_knock_share) == (1.0, 1.5e-4, 0.30)
        assert (cfg.k_lean_c, cfg.lambda_lean_ref, cfg.lean_map_min_kpa) == (600.0, 0.88, 150.0)
        assert (cfg.rod_instant_ratio, cfg.rod_weight_range) == (1.30, (0.9, 1.1))
        assert (cfg.valve_contact_ratio, cfg.turbo_burst_ratio) == (1.08, 1.12)
        assert cfg.preignition_threshold_for("e27") == 840.0
        assert cfg.enabled("forensic")

    def test_integration_calibration_1_2_0(self) -> None:
        """Calibração do laço física + ECU de série (T295, integração física × dano)."""
        cfg = DEFAULT_DAMAGE_CONFIG
        assert DAMAGE_CONFIG_VERSION == "1.2.0"
        assert cfg.knock_tau_multiplier == 4.25
        assert (cfg.lspi_imep_min_kpa, cfg.lspi_p_base, cfg.lspi_p_max) == (2700.0, 1e-5, 2e-4)
        assert (cfg.valve_thermal_tau_s, cfg.turbine_thermal_tau_s) == (5.0, 6.0)
        assert cfg.preignition_threshold_c == {
            "e27": 840.0,
            "e0": 820.0,
            "podium": 880.0,
            "e100": 860.0,
        }

    def test_sensor_gains(self) -> None:
        assert DEFAULT_DAMAGE_CONFIG.sensor_gains(4) == [0.85, 1.0, 1.0, 0.85]
        assert DEFAULT_DAMAGE_CONFIG.sensor_gains(1) == [1.0]
        custom = spec_config(knock_sensor_gain=[1.0, 0.9])
        assert custom.sensor_gains(2) == [1.0, 0.9]
        with pytest.raises(ValueError, match="n_cyl"):
            custom.sensor_gains(4)
        with pytest.raises(ValueError, match="n_cyl"):
            DEFAULT_DAMAGE_CONFIG.sensor_gains(9)

    def test_features_subset(self) -> None:
        cfg = spec_config(features=("knock", "signal"))
        assert cfg.enabled("knock")
        assert not cfg.enabled("thermal")

    @pytest.mark.parametrize(
        "over",
        [
            {"knock_window_start_deg_atdc": 20.0, "knock_window_end_deg_atdc": 15.0},
            {"rod_weight_range": (1.1, 0.9)},
            {"preignition_threshold_c": {"e27": 800.0}},
            {"preignition_threshold_c": {"e27": 1, "e0": 1, "podium": 1, "e100": 1, "e85": 1}},
            {"features": ("knock", "knock")},
            {"features": ("teleport",)},
            {"config_version": "1"},
            {"knock_sensor_gain": [1.0] * 9},
            {"c_mapo": 0.0},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DamageConfig.model_validate(over)

    def test_round_trip(self) -> None:
        cfg = spec_config(i_safe=1.2)
        assert DamageConfig.model_validate_json(cfg.model_dump_json()) == cfg
