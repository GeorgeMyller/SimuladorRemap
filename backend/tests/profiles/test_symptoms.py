"""Sintomas dos erros de setup no ``ActuatorCommands`` do ``ProfiledEcu`` (T156; RF-20 a RF-26).

Casos S-01 a S-10 do Apêndice D. A massa de combustível "real" é calculada como a
física a calcularia com o hardware real (bico do catálogo, dead time real, combustível
do tanque) a partir do pulso entregue pelo adaptador; a confirmação no motor físico
completo (knock pelo knock-and-failure-model, ``EngineState.lambda_cyl``) fica para o E2E.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.ecu.tables import interp1
from simremap.physics.contracts import SensorReadings
from simremap.profiles.adapter import HardwareAdapter, ProfiledEcu, build_profiled_ecu
from simremap.profiles.contracts import BaseSetup, EcuProfileId, HardwareOverride, WizardInputs
from simremap.profiles.hardware import (
    load_vehicle_hardware,
    map_read_kpa,
    ntc_read_c,
    real_dead_time_row,
    real_hardware,
    wideband_read,
)
from simremap.profiles.wizard import generate_base_map

SensorFactory = Callable[..., SensorReadings]
CLASSIC = "classic-20t-swap"


@pytest.fixture
def classic(vehicle: Callable[[str], VehicleSpec]) -> VehicleSpec:
    return vehicle(CLASSIC)


@pytest.fixture
def make_ecu(
    classic: VehicleSpec, catalog: CatalogService, base_payload: Callable[..., dict[str, Any]]
) -> Callable[..., tuple[ProfiledEcu, BaseSetup]]:
    def make(
        *,
        override: HardwareOverride | None = None,
        state: str = "standalone_ready",
        lambda_wot: float | None = None,
        **base_over: Any,
    ) -> tuple[ProfiledEcu, BaseSetup]:
        dead_v, dead_ms = real_dead_time_row(classic)
        payload = base_payload(**base_over)
        if "injectors" not in base_over:
            payload["injectors"] = {
                "flow_cc_min": 2000.0,
                "dead_time_v": dead_v,
                "dead_time_ms": dead_ms,
            }
        base = BaseSetup.model_validate(payload)
        content = generate_base_map(
            EcuProfileId.FT_PRO, base, classic, WizardInputs(max_map_kpa=250.0)
        ).content
        if lambda_wot is not None:
            data = content.model_dump()
            lam = data["tables"]["lambda_target"]
            lam["values"] = [[lambda_wot] * len(r) for r in lam["values"]]
            content = type(content).model_validate(data)
        ecu = build_profiled_ecu(
            vehicle=classic,
            stock_fuel=catalog.get_fuel("e100"),
            profile_id="ft-pro",
            ecu_state=state,  # type: ignore[arg-type]
            base_setup=base,
            calibration=content,
            override=override,
        )
        return ecu, base

    return make


def settled(ecu: ProfiledEcu, s: SensorFactory, **over: Any) -> Any:
    """Dois ticks: o 2.º já sem enriquecimento pós-partida nem de aceleração."""
    ecu.step(s(t_sim_s=1.0, **over), 0.001)
    return ecu.step(s(t_sim_s=30.0, **over), 0.001)


def real_lambda(
    res: Any, *, afr_cfg: float, afr_real: float, rho_cfg: float, rho_real: float,
    flow_cat: float, dead_real: float,
) -> float:  # fmt: skip
    """λ real do cilindro 1 com a massa que o bico do catálogo entrega com o pulso físico."""
    air_mg = res.status.fuel_mass_mg[0] * res.status.lambda_target * afr_cfg
    q_real = flow_cat * rho_real / 60000.0  # g/ms
    m_real_mg = (res.commands.injector_pw_ms[0] - dead_real) * q_real * 1000.0
    del rho_cfg
    return float(air_mg / (m_real_mg * afr_real))


# --------------------------------------------------------------------------- PMS e sincronismo


def test_s01_tdc_error_shifts_real_advance(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-01 / RF-29: PMS real 8° acima do configurado ⇒ avanço real = comandado + 8,0."""
    ecu, _ = make_ecu(override=HardwareOverride(tdc_offset_shift_deg=8.0))
    res = settled(ecu, sensors, rpm=4000.0, map_kpa=200.0)
    for cmd, real in zip(
        res.status.ignition_advance_deg, res.commands.ignition_advance_deg, strict=True
    ):
        assert real == pytest.approx(cmd + 8.0, abs=0.01)
    assert res.profile_status.ign_real_minus_cmd_deg == pytest.approx(8.0)
    same, _ = make_ecu(
        trigger={"wheel": "60-2", "tdc_offset_deg": 82.0, "firing_order": [1, 3, 4, 2]}
    )
    res2 = settled(same, sensors, rpm=4000.0, map_kpa=200.0)
    assert res2.commands.ignition_advance_deg == pytest.approx(res.commands.ignition_advance_deg)


def test_timing_lock_reads_real_advance(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """RF-23: trava a 10° com erro de +8° ⇒ ``timing_light_deg`` = 18,0; sem erro = 10,0."""
    trig = {
        "wheel": "60-2",
        "tdc_offset_deg": 90.0,
        "firing_order": [1, 3, 4, 2],
        "timing_lock_deg": 10.0,
    }
    ecu, _ = make_ecu(trigger=trig, override=HardwareOverride(tdc_offset_shift_deg=8.0))
    res = settled(ecu, sensors, rpm=900.0, map_kpa=35.0, tps_pct=1.0, pedal_pct=1.0)
    assert res.profile_status.ign_cmd_deg == [10.0] * 4
    assert res.profile_status.timing_light_deg == pytest.approx(18.0)
    ok, _ = make_ecu(trigger=trig)
    res_ok = settled(ok, sensors, rpm=900.0, map_kpa=35.0, tps_pct=1.0, pedal_pct=1.0)
    assert res_ok.profile_status.timing_light_deg == pytest.approx(10.0, abs=0.1)
    stopped = ok.step(sensors(rpm=0.0, t_sim_s=31.0), 0.001)
    assert stopped.profile_status.timing_light_deg is None


def test_s04_tdc_error_out_of_range(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-04 / EC-07: erro de 35° ⇒ faísca cortada em todos os cilindros e evento com o valor."""
    ecu, _ = make_ecu(override=HardwareOverride(tdc_offset_shift_deg=35.0))
    first = ecu.step(sensors(), 0.001)
    assert all(first.commands.spark_cut)
    events = [e for e in first.profile_events if e.kind == "tdc_offset_out_of_range"]
    assert len(events) == 1 and events[0].value == pytest.approx(35.0)
    second = ecu.step(sensors(t_sim_s=1.001), 0.001)
    assert not [e for e in second.profile_events if e.kind == "tdc_offset_out_of_range"]


def test_s02_wrong_trigger_wheel(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-02: roda 36-1 declarada com 60-2 real ⇒ ``sync_ok = false`` e cortes totais."""
    ecu, _ = make_ecu(
        trigger={"wheel": "36-1", "tdc_offset_deg": 90.0, "firing_order": [1, 3, 4, 2]}
    )
    res = ecu.step(sensors(), 0.001)
    assert res.profile_status.sync_ok is False
    assert all(res.commands.spark_cut) and all(res.commands.fuel_cut)
    assert res.commands.injector_pw_ms == [0.0] * 4
    assert [e.kind for e in res.profile_events] == ["trigger_sync_lost"]
    ov, _ = make_ecu(override=HardwareOverride(trigger_wheel="36-1"))
    assert ov.step(sensors(), 0.001).profile_status.sync_ok is False


def test_s03_firing_order_mismatch(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-03: ordem 1-2-4-3 declarada com 1-3-4-2 real ⇒ cilindros 2 e 3 sem faísca e com injeção."""
    ecu, _ = make_ecu(
        trigger={"wheel": "60-2", "tdc_offset_deg": 90.0, "firing_order": [1, 2, 4, 3]}
    )
    res = ecu.step(sensors(), 0.001)
    assert res.commands.spark_cut == [False, True, True, False]
    assert res.commands.fuel_cut == [False] * 4
    assert res.commands.injector_pw_ms[1] > 0.0 and res.commands.injector_pw_ms[2] > 0.0
    assert sorted(
        e.cylinder or 0 for e in res.profile_events if e.kind == "firing_order_misfire"
    ) == [
        2,
        3,
    ]
    assert not ecu.step(sensors(t_sim_s=1.001), 0.001).profile_events


def test_ec08_ec09_phase_sensor(
    classic: VehicleSpec, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """EC-08: sequencial sem sensor de fase real ⇒ sem sincronismo; EC-09: borda a 360° ⇒ falha."""
    hw = load_vehicle_hardware(CLASSIC)
    assert hw is not None
    real = real_hardware(hw, classic)
    seq = {
        "wheel": "60-2",
        "tdc_offset_deg": 90.0,
        "firing_order": [1, 3, 4, 2],
        "phase_sensor": "cam_hall",
        "phase_edge_deg": real.phase_edge_deg,
        "injection_mode": "sequential",
        "ignition_mode": "sequential",
    }
    base = BaseSetup.model_validate(base_payload(trigger=seq))
    no_phase = replace(real, phase_sensor_present=False)
    ad = HardwareAdapter(
        profile_id="ft-pro", ecu_state="standalone_ready", declared=base, real=no_phase, n_cyl=4
    )
    assert not ad.sync_ok and ad.sync_detail == "phase_signal_missing"
    good = HardwareAdapter(
        profile_id="ft-pro", ecu_state="standalone_ready", declared=base, real=real, n_cyl=4
    )
    assert good.sync_ok and not good.spark_cut_all
    shifted = BaseSetup.model_validate(
        base_payload(trigger={**seq, "phase_edge_deg": (real.phase_edge_deg + 360.0) % 720.0})
    )
    bad = HardwareAdapter(
        profile_id="ft-pro", ecu_state="standalone_ready", declared=shifted, real=real, n_cyl=4
    )
    assert bad.sync_ok and bad.spark_cut_all and bad.cut_reason == "phase_edge_360"
    wasted = BaseSetup.model_validate(
        base_payload(
            trigger={**seq, "phase_edge_deg": (real.phase_edge_deg + 360.0) % 720.0,
                     "ignition_mode": "wasted_spark"}
        )
    )  # fmt: skip
    ok = HardwareAdapter(
        profile_id="ft-pro", ecu_state="standalone_ready", declared=wasted, real=real, n_cyl=4
    )
    assert not ok.spark_cut_all


# --------------------------------------------------------------------------- sensores


def test_s05_map_scale(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-05: MAP real 20–400 declarado 20–250 ⇒ 200 kPa reais lidos como 128,9 kPa."""
    assert map_read_kpa(200.0, (20.0, 400.0), (20.0, 250.0)) == pytest.approx(128.9, abs=0.5)
    assert map_read_kpa(450.0, (20.0, 400.0), (20.0, 250.0)) == 250.0  # EC-12: satura
    assert map_read_kpa(10.0, (20.0, 400.0), (20.0, 250.0)) == 20.0
    ecu, _ = make_ecu(sensors={"map": {"min_kpa": 20.0, "max_kpa": 250.0}, "wideband": {}})
    res = ecu.step(sensors(map_kpa=200.0), 0.001)
    assert res.profile_status.map_read_kpa == pytest.approx(128.9, abs=0.5)
    same, _ = make_ecu()
    s = sensors(map_kpa=200.123456789)
    assert same.adapter.transform_sensors(s) is s  # escalas iguais: idêntico bit a bit
    assert same.step(s, 0.001).profile_status.map_read_kpa == 200.123456789


def test_s09_ntc_curve(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-09: curva ``ntc_b`` declarada com termistor ``ntc_a`` ⇒ 60 °C lidos como 55,1 °C."""
    assert ntc_read_c(60.0, "ntc_a", "ntc_b") == pytest.approx(55.1, abs=0.5)
    assert ntc_read_c(60.0, "ntc_a", "ntc_a") == 60.0
    ecu, _ = make_ecu(sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0},
                               "iat": {"curve": "ntc_b"},
                               "ect": {"curve": "ntc_c"}, "wideband": {}})  # fmt: skip
    view = ecu.adapter.transform_sensors(sensors(iat_c=60.0, ect_c=90.0))
    assert view.iat_c == pytest.approx(55.1, abs=0.5)
    assert view.ect_c != 90.0


def test_s10_wideband_scale_and_closed_loop(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    """S-10: wideband 0,5–1,5 declarada 0,68–1,36 ⇒ λ 0,85 lido 0,918; malha leva λ real a 0,75."""
    assert wideband_read(0.85, (0.5, 1.5), (0.68, 1.36)) == pytest.approx(0.918, abs=0.002)
    ecu, _ = make_ecu(
        sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0},
                 "wideband": {"lambda_at_0v": 0.68, "lambda_at_5v": 1.36}},
        lambda_wot=0.85,
    )  # fmt: skip
    lam_real = 0.85
    res = None
    for k in range(2500):  # 25 s a 100 Hz: espera de 10 s + convergência do PI
        s = sensors(rpm=3000.0, map_kpa=90.0, tps_pct=30.0, pedal_pct=30.0,
                    lambda_measured=lam_real, t_sim_s=1.0 + 0.01 * k)  # fmt: skip
        res = ecu.step(s, 0.01)
        trim = res.status.stft_pct / 100.0
        lam_real = 0.85 / (1.0 + trim)
    assert res is not None
    assert lam_real == pytest.approx(0.75, rel=0.02)
    assert res.status.stft_pct == pytest.approx(13.3, abs=0.5)
    assert res.profile_status.lambda_read == pytest.approx(0.85, abs=0.01)


def test_wideband_absent_disables_reading(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]], sensors: SensorFactory
) -> None:
    ecu, _ = make_ecu(sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0}})
    res = ecu.step(sensors(), 0.001)
    assert res.profile_status.lambda_read is None
    assert res.status.closed_loop_active is False


# --------------------------------------------------------------------------- combustível


def test_s06_injector_flow_declared_wrong(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]],
    sensors: SensorFactory,
    classic: VehicleSpec,
    catalog: CatalogService,
) -> None:
    """S-06: bico real 1000 cc/min declarado 1250 cc/min, λ alvo 0,85 ⇒ λ real 1,0625 ± 2 %."""
    dead_v, dead_ms = real_dead_time_row(classic)
    inj = {"flow_cc_min": 1250.0, "dead_time_v": dead_v, "dead_time_ms": dead_ms}
    ecu, base = make_ecu(
        injectors=inj,
        sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0}},
        override=HardwareOverride(injector_flow_cc_min=1000.0),
        lambda_wot=0.85,
    )
    res = settled(ecu, sensors, rpm=3000.0, map_kpa=250.0)
    assert res.status.injector_pw_ms[0] >= 5.0
    e100 = catalog.get_fuel("e100")
    dead_real = interp1(dead_v, dead_ms, 14.0)
    assert base.fuel is not None
    lam = real_lambda(
        res, afr_cfg=base.fuel.afr_stoich, afr_real=e100.afr_stoich, rho_cfg=0.789,
        rho_real=e100.density_kg_m3 / 1000.0, flow_cat=2000.0, dead_real=dead_real,
    )  # fmt: skip
    assert lam == pytest.approx(1.0625, rel=0.02)


def test_s07_fuel_declared_wrong(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]],
    sensors: SensorFactory,
    classic: VehicleSpec,
    catalog: CatalogService,
) -> None:
    """S-07: AFR do E27 declarado (13,2) com E100 no tanque (9,0) ⇒ λ real 1,247 ± 2 %."""
    ecu, _ = make_ecu(
        fuel={"fuel_id": "e27", "afr_stoich": 13.2, "density_g_cc": 0.789},
        sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0}},
        lambda_wot=0.85,
    )
    res = settled(ecu, sensors, rpm=3000.0, map_kpa=250.0)
    dead_v, dead_ms = real_dead_time_row(classic)
    e100 = catalog.get_fuel("e100")
    lam = real_lambda(
        res, afr_cfg=13.2, afr_real=e100.afr_stoich, rho_cfg=0.789,
        rho_real=e100.density_kg_m3 / 1000.0, flow_cat=2000.0,
        dead_real=interp1(dead_v, dead_ms, 14.0),
    )  # fmt: skip
    assert lam == pytest.approx(1.247, rel=0.02)


def test_s08_dead_time_declared_low(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]],
    sensors: SensorFactory,
    classic: VehicleSpec,
    catalog: CatalogService,
) -> None:
    """S-08: dead time declarado 0,3 ms abaixo do real ⇒ o bico entrega menos em pulsos curtos."""
    dead_v, dead_ms = real_dead_time_row(classic)
    low = [max(v - 0.3, 0.0) for v in dead_ms]
    ecu, base8 = make_ecu(
        injectors={"flow_cc_min": 2000.0, "dead_time_v": dead_v, "dead_time_ms": low},
        sensors={"map": {"min_kpa": 20.0, "max_kpa": 400.0}},
    )
    res = settled(ecu, sensors, rpm=2000.0, map_kpa=60.0, tps_pct=10.0, pedal_pct=10.0)
    pw = res.commands.injector_pw_ms[0]
    dead_real = interp1(dead_v, dead_ms, 14.0)
    dead_cfg = interp1(dead_v, low, 14.0)
    e100 = catalog.get_fuel("e100")
    assert base8.fuel is not None
    lam = real_lambda(
        res, afr_cfg=base8.fuel.afr_stoich, afr_real=e100.afr_stoich, rho_cfg=0.789,
        rho_real=e100.density_kg_m3 / 1000.0, flow_cat=2000.0, dead_real=dead_real,
    )  # fmt: skip
    useful_ratio = (pw - dead_real) / (pw - dead_cfg)
    assert useful_ratio < 1.0
    assert lam == pytest.approx(res.status.lambda_target / useful_ratio, rel=0.02)
    # Pulso de 2,0 ms: 1,0 ms útil em vez de 1,3 ms ⇒ 77 %.
    assert (2.0 - 1.0) / (2.0 - 0.7) == pytest.approx(0.77, abs=0.005)


# --------------------------------------------------------------------------- arranque


def test_rf20_awaiting_setup_never_starts(
    make_ecu: Callable[..., tuple[ProfiledEcu, BaseSetup]],
    sensors: SensorFactory,
    classic: VehicleSpec,
    catalog: CatalogService,
) -> None:
    """RF-20: em ``awaiting_base_setup`` faísca e injeção cortadas em 10 000 ticks."""
    ecu, _ = make_ecu(state="awaiting_base_setup")
    events: list[str] = []
    for k in range(10_000):
        res = ecu.step(sensors(t_sim_s=k * 0.001, tick=k), 0.001)
        assert all(res.commands.fuel_cut) and all(res.commands.spark_cut)
        events += [e.kind for e in res.profile_events]
    assert events == ["no_start_setup_incomplete"]
    assert res.profile_status.ecu_state == "awaiting_base_setup"
    empty = build_profiled_ecu(
        vehicle=classic,
        stock_fuel=catalog.get_fuel("e100"),
        profile_id="ft-pro",
        ecu_state="standalone_ready",
        base_setup=None,
        calibration=None,
    )
    assert empty.runtime is None and empty.ecu_state == "awaiting_base_setup"
    res = empty.step(sensors(), 0.001)
    assert all(res.commands.fuel_cut) and res.status.calibration_hash == "0" * 64
