"""Cenários builtin de diagnóstico com defeito oculto (002 T044; RF-23, RF-24; D-14).

1. Contrato: os 4 ``defect-*`` carregam, exigem diagnóstico e geram o ``PhysicsFault`` certo;
   ``boost_leak`` exige ``leak_area_mm2``; o hash dos desafios antigos não muda.
2. Tentativa: a sessão criada pelo ``AttemptService`` leva o defeito em ``physics_faults``.
3. Física real (catálogo, ECU de série ``oem-stage``, ``baseline_pull`` em 4.ª, sem ruído):
   bomba fraca pobre acima de 5.500 rpm e normal abaixo de 5.000 rpm; assinaturas dos
   outros 3 defeitos contra o motor saudável.
"""

from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dyno"))

from dyno_helpers import catalog_fuels, make_task, run_to_result

from simremap.damage.config import DamageConfig
from simremap.dyno.contracts import RunState
from simremap.dyno.runner import DynoSimTask
from simremap.physics.contracts import EngineState, PhysicsFault
from simremap.scenarios.catalog import BUILTIN_IDS, builtin_documents
from simremap.scenarios.contracts import DefectKind, Evaluation, HiddenDefect, Scenario

VEHICLE_ID = "hatch-20t-gdi"
EXPECTED: dict[str, dict[str, Any]] = {
    "defect-fuel-pump": {"kind": "fuel_pump_weak", "fuel_pump_max_lph": 84.0},
    "defect-boost-leak": {"kind": "boost_leak", "leak_area_mm2": 150.0},
    "defect-lean-injector": {
        "kind": "injector_clogged",
        "cylinder": 3,
        "injector_flow_factor": 0.85,
    },
    "defect-wastegate-stuck": {"kind": "wastegate_stuck", "stuck_position_pct": 80.0},
}


def _scenario(sid: str) -> Scenario:
    doc = builtin_documents()[sid]
    doc["initial_calibration"]["content_hash"] = "a" * 64
    return Scenario.model_validate(doc)


# --------------------------------------------------------------------------- contrato


@pytest.mark.parametrize("sid", sorted(EXPECTED))
def test_defect_scenario_maps_to_physics_fault(sid: str) -> None:
    scenario = _scenario(sid)
    assert sid in BUILTIN_IDS
    assert scenario.kind == "base" and scenario.builtin
    assert scenario.vehicle_id == VEHICLE_ID and scenario.fuel_id == "e27"
    assert scenario.criteria.require_defect_diagnosis
    assert scenario.criteria.has_defect_diagnosis
    assert scenario.for_student().hidden_defect is None
    assert scenario.hidden_defect is not None
    fault = scenario.hidden_defect.to_physics_fault()
    dumped = fault.model_dump(exclude_none=True)
    assert dumped == {**EXPECTED[sid], "start_t_sim_s": 0.0}
    assert len(scenario.hints) == 3


def test_boost_leak_params() -> None:
    with pytest.raises(ValidationError, match="leak_area_mm2 obrigatório"):
        HiddenDefect(kind=DefectKind.BOOST_LEAK)
    with pytest.raises(ValidationError, match="não aceita leak_area_mm2"):
        HiddenDefect(kind=DefectKind.FUEL_PUMP_WEAK, fuel_pump_max_lph=80.0, leak_area_mm2=20.0)
    for area in (4.0, 201.0):
        with pytest.raises(ValidationError):
            HiddenDefect(kind=DefectKind.BOOST_LEAK, leak_area_mm2=area)
    fault = HiddenDefect(kind=DefectKind.BOOST_LEAK, leak_area_mm2=40.0, start_t_sim_s=2.0)
    assert fault.to_physics_fault() == PhysicsFault(
        kind="boost_leak", leak_area_mm2=40.0, start_t_sim_s=2.0
    )


def test_legacy_defect_hash_is_stable() -> None:
    """``leak_area_mm2`` vazio fica fora dos hashes (desafios e avaliações anteriores à 002)."""
    defect = _scenario("defect-fuel-pump").hidden_defect
    assert "leak_area_mm2" not in _scenario("defect-fuel-pump").evaluable_content()["hidden_defect"]
    evaluation = Evaluation(
        evaluation_id=str(uuid.uuid4()),
        attempt_id=str(uuid.uuid4()),
        submission_index=1,
        status="completed",
        evaluator_version="1.0.0",
        passed=True,
        total_score=100.0,
        revealed_defect=defect,
    )
    assert "leak_area_mm2" not in evaluation.hashable_content()["revealed_defect"]
    leak = _scenario("defect-boost-leak").evaluable_content()
    assert leak["hidden_defect"]["leak_area_mm2"] == 150.0


# --------------------------------------------------------------------------- tentativa


async def test_catalog_loads_seven_builtins(scn: Any) -> None:
    resp = await scn.client.get("/api/v1/scenarios", params={"kind": "base"})
    assert resp.status_code == 200
    rows = {s["scenario_id"]: s for s in resp.json()}
    assert sorted(rows) == sorted(BUILTIN_IDS) and len(rows) == 7
    for sid in EXPECTED:
        assert rows[sid]["has_hidden_defect"] is True
        assert rows[sid]["available"] is True


async def test_real_station_loads_seven_builtins(settings_factory: Any) -> None:
    """Catálogo real e série semeada: os 7 carregam com o hash da rota do clone (RF-02)."""
    from asgi_lifespan import LifespanManager

    from simremap.api.main import create_app
    from simremap.ecu.calibration import compute_content_hash, parse_content

    app = create_app(settings_factory())
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60):
        catalog = app.state.scenarios.catalog
        rows = await catalog.repo.list_scenarios("base")
        assert sorted(s.scenario_id for s in rows) == sorted(BUILTIN_IDS)
        stock = await catalog.calibrations.stock(VEHICLE_ID, "oem-stage")
        expected = compute_content_hash(parse_content(stock.content))
        for scenario in rows:
            if scenario.scenario_id in EXPECTED:
                assert scenario.initial_calibration.content_hash == expected
                assert catalog.available(scenario)


@pytest.mark.parametrize("sid", sorted(EXPECTED))
async def test_attempt_session_gets_defect(scn: Any, sid: str) -> None:
    headers = await scn.profile("diag_aluno")
    student = (await scn.client.get(f"/api/v1/scenarios/{sid}", headers=headers)).json()
    assert student["hidden_defect"] is None and student["has_hidden_defect"] is True
    attempt = await scn.start(sid, headers)
    assert attempt["state"] == "in_progress"
    session = scn.sim.sessions[attempt["session_id"]].view
    faults = [f.model_dump(exclude_none=True) for f in session.physics_faults]
    assert faults == [{**EXPECTED[sid], "start_t_sim_s": 0.0}]


# --------------------------------------------------------------------------- física real


@cache
def _catalog_inputs() -> tuple[Any, Any]:
    from simremap.catalog.service import load_catalog
    from simremap.ecu.calibration import parse_content

    service = load_catalog()
    vehicle = service.get_vehicle(VEHICLE_ID)
    payload = service.get_factory_calibration_payload(VEHICLE_ID, "oem-stage")
    content = parse_content({**payload, "vehicle_id": VEHICLE_ID, "profile_id": "oem-stage"})
    return vehicle, content


class PullProfile:
    """Médias por faixa de 250 rpm da fase ``pull`` de uma ``baseline_pull`` real."""

    def __init__(self) -> None:
        self.bins: dict[int, list[EngineState]] = defaultdict(list)
        self.fuel_kpa: dict[int, list[float]] = defaultdict(list)

    def sample(self, task: DynoSimTask) -> None:
        state = task.last_state
        run = task.run
        if state is None or run is None or not task.run_active or run.phase != "pull":
            return
        assert task.parts is not None
        rpm_bin = int(state.rpm // 250) * 250
        self.bins[rpm_bin].append(state)
        self.fuel_kpa[rpm_bin].append(task.parts.physics.read_sensors().fuel_pressure_kpa)

    def mean(self, lo: float, hi: float, value: Any) -> dict[int, float]:
        return {
            b: sum(value(s) for s in states) / len(states)
            for b, states in sorted(self.bins.items())
            if lo <= b < hi and states
        }

    def lam(self, lo: float, hi: float) -> dict[int, float]:
        return self.mean(lo, hi, lambda s: s.lambda_collector)

    def fuel_pressure(self, lo: float, hi: float) -> dict[int, float]:
        return {b: sum(v) / len(v) for b, v in sorted(self.fuel_kpa.items()) if lo <= b < hi and v}


@cache
def _pull(defect_sid: str | None) -> PullProfile:
    vehicle, content = _catalog_inputs()
    faults = [] if defect_sid is None else [_fault(defect_sid)]
    task = make_task(
        vehicle=vehicle,
        fuel=catalog_fuels()["e27"],
        calibration=content,
        calibration_id=f"stock-{VEHICLE_ID}-oem-stage",
        profile_hooks="registry",
        damage_config=DamageConfig(),
        physics_faults=faults,
        physics_noise=False,
    )
    profile = PullProfile()
    out = run_to_result(task, {"run_type": "baseline_pull", "gear": 4}, on_tick=profile.sample)
    assert out.run.state == RunState.COMPLETED, out.run.state
    return profile


def _fault(sid: str) -> PhysicsFault:
    defect = _scenario(sid).hidden_defect
    assert defect is not None
    return defect.to_physics_fault()


def test_fuel_pump_lean_only_above_5500_rpm() -> None:
    """RF-24: abaixo de 5.000 rpm a mistura e a pressão de rail ficam iguais às do motor
    saudável (λ dentro da janela 0,75–0,98); acima de 5.500 rpm a pressão cai a < 50 % e o λ
    passa de 0,90 (fora da janela 0,75–0,90 do cenário)."""
    healthy, weak = _pull(None), _pull("defect-fuel-pump")
    nominal = max(healthy.fuel_pressure(2000, 7000).values())
    for rpm_bin, lam in weak.lam(3000, 5000).items():
        assert lam == pytest.approx(healthy.lam(3000, 5000)[rpm_bin], abs=0.005), rpm_bin
        assert 0.75 <= lam <= 0.98, rpm_bin
    assert min(weak.fuel_pressure(3000, 5000).values()) >= 0.95 * nominal
    high = weak.lam(5500, 7000)
    assert max(high.values()) > 0.90
    lean_bin = max(high, key=lambda b: high[b])
    assert high[lean_bin] >= healthy.lam(5500, 7000)[lean_bin] + 0.05
    assert min(weak.fuel_pressure(5500, 7000).values()) < 0.5 * nominal


def test_boost_leak_spins_turbo_and_enriches() -> None:
    """Mesma pressão no coletor; turbo mais rápido, mistura mais rica e EGT mais alta."""
    healthy, leak = _pull(None), _pull("defect-boost-leak")
    for rpm_bin, map_kpa in leak.mean(4000, 6500, lambda s: s.map_kpa).items():
        assert map_kpa == pytest.approx(
            healthy.mean(4000, 6500, lambda s: s.map_kpa)[rpm_bin], abs=3.0
        )
    turbo_h = healthy.mean(4000, 6500, lambda s: s.turbo_rpm)
    for rpm_bin, turbo in leak.mean(4000, 6500, lambda s: s.turbo_rpm).items():
        assert turbo >= 1.04 * turbo_h[rpm_bin], rpm_bin
    lam_h = healthy.lam(4000, 6500)
    assert all(lam < lam_h[b] - 0.004 for b, lam in leak.lam(4000, 6500).items())
    egt_h = healthy.mean(5000, 6500, lambda s: s.egt_collector_c)
    assert all(
        egt > egt_h[b] + 10 for b, egt in leak.mean(5000, 6500, lambda s: s.egt_collector_c).items()
    )


def test_lean_injector_shows_on_cylinder_egt() -> None:
    """Cilindro 3 pobre: EGT individual ≥ 40 °C acima dos outros em plena carga alta."""
    clogged = _pull("defect-lean-injector")
    for rpm_bin, states in clogged.bins.items():
        if not 4750 <= rpm_bin < 6500:
            continue
        egt = [sum(s.egt_c[c] for s in states) / len(states) for c in range(4)]
        others = max(egt[0], egt[1], egt[3])
        assert egt[2] >= others + 40.0, (rpm_bin, egt)
        lam3 = sum(s.lambda_cyl[2] or 0.0 for s in states) / len(states)
        lam1 = sum(s.lambda_cyl[0] or 0.0 for s in states) / len(states)
        assert lam3 == pytest.approx(lam1 / 0.85, rel=0.02)


def test_wastegate_stuck_open_kills_boost() -> None:
    """Wastegate presa a 80 %: posição fixa e pressão muito abaixo da do motor saudável."""
    healthy, stuck = _pull(None), _pull("defect-wastegate-stuck")
    positions = {s.wastegate_position_pct for states in stuck.bins.values() for s in states}
    assert positions == {80.0}
    map_h = healthy.mean(3000, 6500, lambda s: s.map_kpa)
    for rpm_bin, map_kpa in stuck.mean(3000, 6500, lambda s: s.map_kpa).items():
        assert map_kpa <= 150.0 and map_kpa < map_h[rpm_bin] - 50.0, rpm_bin
