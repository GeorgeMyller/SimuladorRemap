"""Combustível: speed-density, modos, lambda alvo, compensações, malha fechada e trims.

Fontes: RF-06 a RF-10, RF-12; T140.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from simremap.ecu.hooks import NullProfileHooks
from simremap.ecu.runtime import EcuRuntime
from simremap.ecu.strategies.fuel import speed_density_air_g

DT = 0.001


def _rf06_tables(tb: Any) -> dict[str, Any]:
    tables: dict[str, Any] = tb.base_tables()
    tables["lambda_target"] = tb.t3("lambda_target", "lambda_target", "λ", 0.80)
    return tables


def test_rf06_speed_density_reference_pulse(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """RF-06: pulso de referência de 14,67 ms ± 0,5 %.

    VE 90 %, MAP 200 kPa, V_cyl 0,000496 m³, IAT 40 °C, λ 0,80, AFR 13,2, 550 cc/min.
    """
    rt = runtime_factory(content_factory(_rf06_tables(tb)))
    out = rt.step(sensors(map_kpa=200.0, iat_c=40.0, rpm=3000.0, tps_pct=50.0), DT)
    expected = 14.67
    for pw in out.commands.injector_pw_ms:
        assert pw == pytest.approx(expected, rel=0.005)
    # Equação de referência (Apêndice B) com erro < 0,5 % (G-03).
    m_air = 0.90 * 200_000 * 0.000496 / (287.05 * 313.15) * 1000  # g
    pw_ref = m_air / (0.80 * 13.2) / (550 * 0.745 / 60000) + 0.9
    assert out.commands.injector_pw_ms[0] == pytest.approx(pw_ref, rel=1e-9)
    assert out.status.fuel_mass_mg[0] == pytest.approx(m_air / (0.80 * 13.2) * 1000, rel=1e-9)
    assert out.status.lambda_target == pytest.approx(0.80)
    assert out.status.inj_duty_pct == pytest.approx(pw_ref / (120000 / 3000) * 100)


def test_speed_density_charge_temperature_blend() -> None:
    cold = speed_density_air_g(100, 100, 0.0005, 20, 90, 0.0)
    blended = speed_density_air_g(100, 100, 0.0005, 20, 90, 0.5)
    assert blended < cold
    assert cold == pytest.approx(100_000 * 0.0005 / (287.05 * 293.15) * 1000)


def test_direct_pulse_mode(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["inj_base_ms"] = tb.t3("inj_base_ms", "inj_base_ms", "ms", 5.0)
    rt = runtime_factory(content_factory(tables, fuel_model={"mode": "direct_pulse_ms"}))
    out = rt.step(sensors(), DT)
    assert out.commands.injector_pw_ms[0] == pytest.approx(5.0 + 0.9)


class AirHook(NullProfileHooks):
    def __init__(self, air_mg: float | None) -> None:
        super().__init__("oem-stage")
        self.air_mg = air_mg

    def air_charge_mg(self, sensors: object, compiled: object) -> float | None:
        return self.air_mg


def test_profile_air_model_uses_hook(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    content = content_factory(fuel_model={"mode": "profile_air_model"})
    rt = runtime_factory(content, hooks=AirHook(500.0))
    out = rt.step(sensors(), DT)
    assert out.status.fuel_mass_mg[0] == pytest.approx(500.0 / (0.85 * 13.2))
    # None ⇒ speed-density com a tabela ve.
    fallback = runtime_factory(content, hooks=AirHook(None)).step(sensors(), DT)
    sd = runtime_factory(content_factory()).step(sensors(), DT)
    assert fallback.status.fuel_mass_mg[0] == pytest.approx(sd.status.fuel_mass_mg[0])


def test_lambda_target_table_drives_fuel(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rich = _rf06_tables(tb)
    lean = _rf06_tables(tb)
    lean["lambda_target"] = tb.t3("lambda_target", "lambda_target", "λ", 1.0)
    a = runtime_factory(content_factory(rich)).step(sensors(), DT).status
    b = runtime_factory(content_factory(lean)).step(sensors(), DT).status
    assert a.fuel_mass_mg[0] / b.fuel_mass_mg[0] == pytest.approx(1.0 / 0.8)
    assert a.lambda_target == 0.8 and b.lambda_target == 1.0


def test_ect_and_iat_compensations(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    base = runtime_factory(content_factory(tables)).step(sensors(), DT).status.fuel_mass_mg[0]
    tables["fuel_corr_ect"] = tb.t2(
        "fuel_corr_ect", "fuel_corr_ect", "%", 10.0, x=[0, 100], xq="ect_c"
    )
    tables["fuel_corr_iat"] = tb.t2(
        "fuel_corr_iat", "fuel_corr_iat", "%", -5.0, x=[0, 100], xq="iat_c"
    )
    comp = runtime_factory(content_factory(tables)).step(sensors(), DT).status.fuel_mass_mg[0]
    assert comp / base == pytest.approx(1.10 * 0.95)


def test_accel_enrichment_decays_with_tau(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """dTPS/dt = 500 %/s ⇒ enriquecimento da tabela, 63 % de queda em 0,2 s ± 1 tick.

    A taxa usa a mediana de 3 amostras do TPS (B1): o degrau de 1 % no tick 1 chega no
    tick 2, 2 ms depois do valor retido (1 % / 2 ms = 500 %/s)."""
    tables = tb.base_tables()
    tables["accel_enrich"] = tb.t2(
        "accel_enrich",
        "accel_enrich",
        "%",
        [0.0, 20.0, 40.0],
        x=[0, 500, 1000],
        xq="tps_rate_pct_s",
    )
    rt: EcuRuntime = runtime_factory(content_factory(tables))
    base = rt.step(sensors(tps_pct=50.0), DT).status.fuel_mass_mg[0]
    rt.step(sensors(t_sim_s=DT, tick=1, tps_pct=51.0), DT)
    out = rt.step(sensors(t_sim_s=2 * DT, tick=2, tps_pct=51.0), DT)
    peak = rt.fuel.accel_enrich
    assert peak == pytest.approx(0.20)
    assert out.status.fuel_mass_mg[0] / base == pytest.approx(1.20)
    values = []
    for i in range(3, 3 + 201):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=51.0), DT)
        values.append(rt.fuel.accel_enrich)
    target = peak * (1 - 0.632)
    tick = next(i for i, v in enumerate(values, start=1) if v <= target)
    assert abs(tick - 200) <= 1


def test_cranking_uses_cranking_fuel(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["cranking_fuel"] = tb.t2(
        "cranking_fuel", "cranking_fuel", "ms", [12.0, 4.0], x=[-20, 80], xq="ect_c"
    )
    rt = runtime_factory(content_factory(tables, fuel_model={"cranking_ign_deg": 8.0}))
    out = rt.step(sensors(rpm=250.0, ect_c=30.0), DT)
    assert out.commands.injector_pw_ms == [pytest.approx(8.0)] * 4
    assert out.commands.ignition_advance_deg == [8.0] * 4
    stopped = rt.step(sensors(rpm=0.0, t_sim_s=DT, tick=1), DT)
    assert stopped.commands.injector_pw_ms == [0.0] * 4


def test_afterstart_enrichment_decays(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["afterstart_enrich"] = tb.t2(
        "afterstart_enrich", "afterstart_enrich", "%", 30.0, x=[-20, 80], xq="ect_c"
    )
    rt = runtime_factory(content_factory(tables, fuel_model={"afterstart_decay_s": 1.0}))
    plain = runtime_factory(content_factory()).step(sensors(), DT).status.fuel_mass_mg[0]
    first = rt.step(sensors(), DT).status.fuel_mass_mg[0]
    assert first / plain == pytest.approx(1.30)
    mid = rt.step(sensors(t_sim_s=0.5, tick=500), DT).status.fuel_mass_mg[0]
    assert mid / plain == pytest.approx(1.15)
    end = rt.step(sensors(t_sim_s=1.5, tick=1500), DT).status.fuel_mass_mg[0]
    assert end == pytest.approx(plain)


def test_rf12_cylinder_fuel_trim(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["fuel_trim_2"] = tb.t3("fuel_trim_2", "fuel_trim_cyl", "%", 4.0, cylinder=2)
    out = runtime_factory(content_factory(tables)).step(sensors(), DT)
    mass = out.status.fuel_mass_mg
    assert mass[1] / mass[0] == pytest.approx(1.04, abs=0.001)
    assert mass[0] == mass[2] == mass[3]


def test_dead_time_by_battery_and_rail_pressure(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["inj_dead_time"] = tb.t2(
        "inj_dead_time", "inj_dead_time", "ms", [1.5, 0.5], x=[8, 16], xq="battery_v"
    )
    rt = runtime_factory(content_factory(tables))
    out = rt.step(sensors(battery_v=12.0), DT)
    inj = out.status.fuel_mass_mg[0] / 1000 / (550 * 0.745 / 60000)
    assert out.commands.injector_pw_ms[0] == pytest.approx(inj + 1.0)
    high = runtime_factory(content_factory(tables)).step(
        sensors(battery_v=12.0, fuel_pressure_kpa=1200.0), DT
    )
    assert high.commands.injector_pw_ms[0] - 1.0 == pytest.approx(inj / 2.0)
    no_rail = runtime_factory(content_factory(tables), hw=tb.hardware(4, use_rail_pressure=False))
    flat = no_rail.step(sensors(battery_v=12.0, fuel_pressure_kpa=1200.0), DT)
    assert flat.commands.injector_pw_ms[0] == pytest.approx(inj + 1.0)


def test_ec06_duty_above_100_is_clipped(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["ve"] = tb.t3("ve", "ve", "%", 150.0)
    rt = runtime_factory(content_factory(tables), hw=tb.hardware(4, injector_flow_cc_min=200.0))
    out = rt.step(sensors(rpm=8000.0, map_kpa=400.0), DT)
    period = 120000 / 8000
    assert out.commands.injector_pw_ms[0] == pytest.approx(period)
    assert out.status.inj_duty_pct == pytest.approx(100.0)
    assert [e.kind for e in out.events].count("inj_duty_high") == 1
    again = rt.step(sensors(rpm=8000.0, map_kpa=400.0, t_sim_s=DT, tick=1), DT)
    assert not [e for e in again.events if e.kind == "inj_duty_high"]


def test_duty_warning_without_limiting(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = runtime_factory(content_factory())
    out = rt.step(sensors(rpm=6000.0, map_kpa=260.0), DT)
    assert 85.0 < out.status.inj_duty_pct < 100.0
    warn = [e for e in out.events if e.kind == "inj_duty_high"]
    assert len(warn) == 1 and warn[0].detail == "aviso"


# --------------------------------------------------------------------------- malha fechada


def _closed_loop_content(content_factory: Any, **cfg: Any) -> Any:
    return content_factory(
        strategies={"closed_loop": {"kind": "closed_loop", "delay_after_start_s": 0.0, **cfg}}
    )


def _run_plant(
    rt: EcuRuntime,
    sensors: Any,
    seconds: float,
    injector_factor: float,
    *,
    start_tick: int = 0,
    ect_c: float = 90.0,
    state: dict[str, Any] | None = None,
) -> list[tuple[float, float, float]]:
    """Planta simples: λ real = m_ar / (fator · m_comb · AFR), atraso 60 ms e τ 0,1 s."""
    st: dict[str, Any] = state if state is not None else {"lam": 0.85, "delay": deque([0.85] * 60)}
    log: list[tuple[float, float, float]] = []
    for i in range(start_tick, start_tick + int(seconds / DT)):
        out = rt.step(sensors(t_sim_s=i * DT, tick=i, ect_c=ect_c, lambda_measured=st["lam"]), DT)
        fuel_g = out.status.fuel_mass_mg[0] / 1000.0
        lam_real = rt.fuel.air_g / (injector_factor * fuel_g * 13.2)
        st["delay"].append(lam_real)
        delayed = st["delay"].popleft()
        st["lam"] += (delayed - st["lam"]) * DT / 0.1
        log.append((i * DT, st["lam"], out.status.stft_pct))
    return log


def test_rf09_closed_loop_converges_with_smaller_injector(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory))
    log = _run_plant(rt, sensors, 4.0, 0.9)
    target = 0.85
    after_3s = [lam for t, lam, _ in log if t >= 3.0]
    assert all(abs(lam / target - 1) <= 0.01 for lam in after_3s)
    assert max(abs(stft) for _, _, stft in log) <= 25.0
    assert rt.closed_loop.active
    assert log[-1][2] == pytest.approx(100 * (1 / 0.9 - 1), abs=0.3)


def test_rf09_trim_limited_to_25pct(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory))
    log = _run_plant(rt, sensors, 3.0, 0.6)
    assert max(stft for _, _, stft in log) == pytest.approx(25.0)
    assert all(stft <= 25.0 for _, _, stft in log)
    assert abs(rt.closed_loop.integ) <= 0.25 + 1e-9


def test_rf09_cold_engine_trim_zero(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory))
    log = _run_plant(rt, sensors, 1.0, 0.9, ect_c=50.0)
    assert all(stft == 0.0 for _, _, stft in log)
    assert not rt.closed_loop.active


def test_closed_loop_activation_conditions(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(
        content_factory(
            strategies={"closed_loop": {"kind": "closed_loop", "delay_after_start_s": 1.0}}
        )
    )
    out = rt.step(sensors(lambda_measured=1.0), DT)
    assert not out.status.closed_loop_active  # ainda dentro do atraso após partida
    out = rt.step(sensors(t_sim_s=1.5, tick=1500, lambda_measured=1.0), DT)
    assert out.status.closed_loop_active and out.status.stft_pct > 0
    out = rt.step(sensors(t_sim_s=1.6, tick=1600, lambda_measured=1.0, map_kpa=450.0), DT)
    assert not out.status.closed_loop_active and out.status.stft_pct == 0.0
    assert "closed_loop" not in out.status.active_strategies


def test_ec05_invalid_wideband_freezes_open_loop(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory))
    _run_plant(rt, sensors, 0.5, 0.9)
    bad = sensors(t_sim_s=0.6, tick=600).model_copy(update={"lambda_measured": float("nan")})
    out = rt.step(bad, DT)
    assert not out.status.closed_loop_active
    assert out.status.stft_pct == 0.0


def test_closed_loop_limit_event(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory, kp=5.0))
    out = rt.step(sensors(lambda_measured=1.5), DT)
    assert [e.kind for e in out.events] == ["closed_loop_limit"]


def test_closed_loop_holds_trim_during_fuel_cut(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    content = content_factory(
        strategies={
            "closed_loop": {"kind": "closed_loop", "delay_after_start_s": 0.0},
            "rev_limiter": {"kind": "rev_limiter", "hard_rpm": 5000.0},
        }
    )
    rt = runtime_factory(content)
    rt.step(sensors(lambda_measured=0.9), DT)
    rt.step(sensors(t_sim_s=DT, tick=1, rpm=5100.0, lambda_measured=0.9), DT)  # corte começa
    trim = rt.closed_loop.stft
    out = rt.step(sensors(t_sim_s=2 * DT, tick=2, rpm=5100.0, lambda_measured=2.0), DT)
    assert not out.status.closed_loop_active
    assert rt.closed_loop.stft == trim


def test_rf10_ltft_absorbs_stable_stft(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(_closed_loop_content(content_factory, ltft_enabled=True))
    state: dict[str, Any] = {"lam": 0.85, "delay": deque([0.85] * 60)}
    _run_plant(rt, sensors, 10.0, 1 / 1.08, state=state)
    ltft_10 = rt.closed_loop.ltft_value * 100
    assert 4.0 <= ltft_10 <= 5.1  # 0,5 %/s
    total = rt.closed_loop.trim_total * 100
    assert total == pytest.approx(8.0, abs=0.3)
    _run_plant(rt, sensors, 10.0, 1 / 1.08, start_tick=10_000, state=state)
    assert rt.closed_loop.ltft_value * 100 == pytest.approx(8.0, abs=0.3)
    assert abs(rt.closed_loop.stft * 100) <= 0.3
    out = rt.step(sensors(t_sim_s=20.0, tick=20_000, lambda_measured=state["lam"]), DT)
    assert out.status.ltft_pct == pytest.approx(rt.closed_loop.ltft_value * 100)
    rt.reset_session()
    assert rt.closed_loop.ltft_value == 0.0  # LTFT reinicia por sessão (OQ-05)


def test_rf10_ltft_limit_and_disabled(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(
        _closed_loop_content(content_factory, ltft_enabled=True, ltft_limit_pct=2.0)
    )
    _run_plant(rt, sensors, 8.0, 1 / 1.08)
    assert rt.closed_loop.ltft_value * 100 == pytest.approx(2.0)
    off = runtime_factory(_closed_loop_content(content_factory))
    _run_plant(off, sensors, 3.0, 1 / 1.08)
    assert off.closed_loop.ltft_value == 0.0
    assert all(v == 0.0 for v in off.closed_loop.ltft)


def test_tps_noise_does_not_trigger_accel_enrichment(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """Ruído do TPS (±0,3 %, abaixo da banda morta) não gera enriquecimento de aceleração."""
    tables = tb.base_tables()
    tables["accel_enrich"] = tb.t2(
        "accel_enrich", "accel_enrich", "%", [0.0, 20.0, 40.0], x=[0, 500, 1000],
        xq="tps_rate_pct_s",
    )  # fmt: skip
    rt: EcuRuntime = runtime_factory(content_factory(tables))
    noise = [0.0, 0.3, -0.2, 0.25, -0.3, 0.1, -0.1, 0.3, -0.25, 0.2]
    for i, n in enumerate(noise * 20):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=50.0 + n), DT)
        assert rt.fuel.accel_enrich == 0.0


def test_slow_tps_ramp_uses_time_since_last_change(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """Rampa de 100 %/s (0,1 % por tick): a taxa vem do tempo desde a última mudança retida."""
    tables = tb.base_tables()
    tables["accel_enrich"] = tb.t2(
        "accel_enrich", "accel_enrich", "%", [0.0, 20.0, 40.0], x=[0, 500, 1000],
        xq="tps_rate_pct_s",
    )  # fmt: skip
    rt: EcuRuntime = runtime_factory(content_factory(tables))
    peaks = []
    for i in range(60):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=20.0 + 0.1 * i), DT)
        peaks.append(rt.fuel.accel_enrich)
    # 100 %/s ⇒ 4 % pela tabela (nunca os 20 % de um degrau de 0,5 % num tick)
    assert max(peaks) == pytest.approx(0.04, abs=0.01)


def _ae_table(tb: Any) -> dict[str, Any]:
    tables: dict[str, Any] = tb.base_tables()
    tables["accel_enrich"] = tb.t2(
        "accel_enrich", "accel_enrich", "%", [0.0, 20.0, 40.0], x=[0, 500, 1000],
        xq="tps_rate_pct_s",
    )  # fmt: skip
    return tables


@pytest.mark.parametrize(("level", "outlier"), [(100.0, -0.53), (60.0, -0.45), (60.0, 0.45)])
def test_single_tps_outlier_does_not_trigger_accel_enrichment(
    content_factory: Any,
    runtime_factory: Any,
    sensors: Any,
    tb: Any,
    level: float,
    outlier: float,
) -> None:
    """B1 (003 T032): uma amostra isolada do TPS além da banda morta (cauda de 4–5σ do
    ruído, ou a borboleta a 100 % com o ruído recortado) e o regresso ao valor real no tick
    seguinte não são uma pisada: sem enriquecimento de aceleração (antes: +36 % e λ 0,63)."""
    rt: EcuRuntime = runtime_factory(content_factory(_ae_table(tb)))
    trace = [level] * 50 + [min(level + outlier, 100.0)] + [level] * 50
    for i, tps in enumerate(trace):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=tps), DT)
        assert rt.fuel.accel_enrich == 0.0, (i, tps, rt.ctx.tps_rate_pct_s)


def test_real_tip_in_still_triggers_accel_enrichment(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """Pisada real depois de regime (1 % por tick = 1000 %/s, com o ruído do sensor):
    o enriquecimento chega aos 40 % da tabela com no máximo 1 tick de atraso."""
    rt: EcuRuntime = runtime_factory(content_factory(_ae_table(tb)))
    noise = [0.05, -0.1, 0.08, -0.03, 0.1, -0.07]
    trace = [30.0 + noise[i % 6] for i in range(100)]
    trace += [31.0 + i + noise[i % 6] for i in range(20)]
    peaks = []
    for i, tps in enumerate(trace):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=tps), DT)
        peaks.append(rt.fuel.accel_enrich)
    assert max(peaks[:100]) == 0.0
    assert peaks[103] >= 0.35
    assert max(peaks) == pytest.approx(0.40, abs=0.02)
