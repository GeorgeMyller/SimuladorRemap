"""Sensores: ruído semeado por canal, atrasos de 1.ª ordem e knock (T103; RF-17, RF-26; D-20)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.random import PCG64, Generator, SeedSequence

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import KnockSignal, SensorNoiseConfig, SensorReadings
from simremap.physics.engine import PhysicsEngine
from simremap.physics.sensors import (
    KNOCK_SIGMA_V,
    NOISE_CHANNELS,
    PHYSICS_SPAWN_KEY,
    SensorNoise,
    clamp_lambda,
    knock_block,
    knock_index,
    knock_voltage,
    wideband_delay_s,
    wideband_update,
)


def test_knock_reference_points(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-26: intensidade 0 sem ruído ⇒ 0,05 V e 0,0; intensidade 10 ⇒ 5,0 V e 1,0."""
    engine = make_engine(hatch, noise_enabled=False)
    quiet = engine.read_sensors(KnockSignal.silent(4))
    assert quiet.knock_sensor_v == [pytest.approx(0.05)] * 4
    assert quiet.knock_intensity == [0.0] * 4
    loud = engine.read_sensors(KnockSignal(intensity=[10.0, 0.0, 1.0, 3.4]))
    assert loud.knock_sensor_v[0] == 5.0 and loud.knock_intensity[0] == 1.0
    assert loud.knock_sensor_v[2] == pytest.approx(1.55)
    assert loud.knock_intensity[2] == pytest.approx(1.5 / 4.95)
    assert loud.knock_sensor_v[3] == 5.0
    assert knock_voltage(0.0, -1.0) == 0.0 and knock_index(0.0) == 0.0


def test_knock_ranges_one_million_samples() -> None:
    """RF-26: em 10⁶ amostras com ruído, V ∈ [0, 5] e índice ∈ [0, 1] (mesmas fórmulas)."""
    children = SeedSequence(123, spawn_key=PHYSICS_SPAWN_KEY).spawn(len(NOISE_CHANNELS))
    rng = Generator(PCG64(children[NOISE_CHANNELS.index("knock")]))
    n = 1_000_000
    intensity = np.abs(rng.standard_normal(n)) * 2.0
    intensity[::97] = 0.0
    intensity[::89] = 50.0
    volts, index = knock_block(intensity, rng.standard_normal(n) * KNOCK_SIGMA_V)
    assert volts.min() >= 0.0 and volts.max() <= 5.0
    assert index.min() >= 0.0 and index.max() <= 1.0
    # A versão escalar coincide com a vetorizada.
    for i in range(0, n, 99_991):
        noise = float(volts[i] - 0.05 - 1.5 * intensity[i])
        if 0.0 < volts[i] < 5.0:
            assert knock_voltage(float(intensity[i]), noise) == pytest.approx(float(volts[i]))
            assert knock_index(float(volts[i])) == pytest.approx(float(index[i]))


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(min_value=0.0, max_value=1e3, allow_nan=False), min_size=4, max_size=4))
def test_read_sensors_always_valid(
    make_engine_session: PhysicsEngine, intensity: list[float]
) -> None:
    """Propriedade: qualquer KnockSignal produz leituras dentro dos limites do contrato."""
    readings = make_engine_session.read_sensors(KnockSignal(intensity=intensity))
    SensorReadings.model_validate(readings.model_dump())
    assert all(0.0 <= v <= 5.0 for v in readings.knock_sensor_v)
    assert all(0.0 <= v <= 1.0 for v in readings.knock_intensity)
    assert 0.5 <= readings.lambda_measured <= 2.0


@pytest.fixture(scope="module")
def make_engine_session(hatch: VehicleSpec, fuels: dict) -> PhysicsEngine:  # type: ignore[type-arg]
    from simremap.physics.contracts import PhysicsConfig

    engine = PhysicsEngine(PhysicsConfig(seed=5), hatch, fuels["e27"], initial_ect_c=90.0)
    engine.crank(3000.0)
    return engine


def test_noise_sigma_within_ten_percent() -> None:
    """RF-17: desvio-padrão medido em 10 000 amostras a ± 10 % do σ configurado."""
    noise = SensorNoise(42)
    cfg = SensorNoiseConfig()
    for channel, sigma in (
        ("map", cfg.map_sigma_kpa),
        ("lambda", cfg.lambda_sigma),
        ("egt", cfg.egt_sigma_c),
        ("rpm", cfg.rpm_sigma),
    ):
        samples = [noise.normal(channel, sigma) for _ in range(10_000)]
        assert statistics.pstdev(samples) == pytest.approx(sigma, rel=0.10)


def test_engine_readings_noise_sigma(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """O ruído aplicado pelo motor tem o σ configurado (MAP com o motor parado)."""
    engine = make_engine(hatch)
    maps = [engine.read_sensors().map_kpa for _ in range(10_000)]
    assert statistics.pstdev(maps) == pytest.approx(0.3, rel=0.10)


def test_noise_substreams_are_independent_per_channel() -> None:
    """Mudar o σ ou o consumo de um canal não altera a sequência de outro (D-BUS-02)."""
    a = SensorNoise(9)
    b = SensorNoise(9)
    for _ in range(100):
        b.normal("map", 5.0)  # consumo extra só no canal map
    seq_a = [a.normal("lambda", 1.0) for _ in range(50)]
    seq_b = [b.normal("lambda", 1.0) for _ in range(50)]
    assert seq_a == seq_b
    c = SensorNoise(10)
    assert [c.normal("lambda", 1.0) for _ in range(50)] != seq_a
    # Restauração do estado (snapshot).
    state = a.state()
    x = [a.normal("egt", 1.0) for _ in range(5)]
    a.set_state(state)
    assert [a.normal("egt", 1.0) for _ in range(5)] == x


def test_wideband_step_response() -> None:
    """RF-17: degrau 1,00 → 0,85 ⇒ 63 % do degrau em 0,1 s ± 10 % mais o atraso de transporte."""
    hz = 1000
    dt = 1 / hz
    rpm = 3000.0
    buf = [1.0] * 500
    idx = 0
    filt = 1.0
    t63 = None
    for k in range(2000):
        idx, filt = wideband_update(buf, idx, filt, 0.85, rpm, dt, hz, 0.1)
        if filt <= 1.0 - 0.63 * 0.15:
            t63 = (k + 1) * dt
            break
    assert t63 is not None
    delay = wideband_delay_s(rpm)
    assert delay == pytest.approx(0.02 + 120 / 3000)
    assert t63 - delay == pytest.approx(0.1, rel=0.10)


def test_wideband_saturation_and_thermocouple(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    assert clamp_lambda(3.0) == 2.0 and clamp_lambda(0.1) == 0.5 and clamp_lambda(math.nan) == 2.0
    engine = make_engine(hatch, noise_enabled=False)
    r = engine.read_sensors()
    assert r.lambda_measured == 2.0  # motor parado: ar puro
    assert r.egt_c == [pytest.approx(25.0)] * 4
    assert r.battery_v == pytest.approx(12.4)
    assert r.turbo_rpm == 0.0 and r.wastegate_position_pct == 0.0
    assert r.sync_ok and r.gear == 0


def test_sensor_readings_fields_from_dyno_load(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """D-BUS-03: entradas do condutor chegam aos sensores a partir do DynoLoad do tick anterior."""
    from simremap.dyno.contracts import AmbientConditions, DynoLoad
    from simremap.physics.reference import ReferenceDriver

    engine = make_engine(hatch, noise_enabled=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=10.0)
    load = DynoLoad(
        reflected_inertia_kg_m2=1.0,
        load_torque_crank_nm=0.0,
        gear=3,
        wheel_to_crank_ratio=5.4,
        pedal_pct=42.0,
        fan_air_speed_m_s=10.0,
        ambient=AmbientConditions(),
        vehicle_speed_kmh=61.0,
        clutch_pressed=True,
        launch_switch=True,
        shift_request=True,
        antilag_switch=True,
    )
    engine.crank(2000.0)
    engine.step(driver.commands(None, engine.resolved.dt), load, engine.resolved.dt)
    r = engine.read_sensors()
    assert (r.pedal_pct, r.gear, r.vehicle_speed_kmh) == (42.0, 3, 61.0)
    assert r.clutch_pressed and r.launch_switch and r.shift_request and r.antilag_switch
    assert r.oil_pressure_kpa > 0.0
    assert r.baro_kpa == pytest.approx(99.0)


def test_knock_ranges_engine_ticks(make_engine_session: PhysicsEngine) -> None:
    """RF-26: 10⁶ leituras reais com ruído e intensidades aleatórias ficam dentro dos limites."""
    rng = Generator(PCG64(SeedSequence(77)))
    intensities = (np.abs(rng.standard_normal((1_000_000, 4))) * 5.0).tolist()
    lo_v = hi_v = 0.05
    for row in intensities:
        r = make_engine_session.read_sensors(KnockSignal.model_construct(intensity=row))
        lo_v = min(lo_v, *r.knock_sensor_v)
        hi_v = max(hi_v, *r.knock_sensor_v)
        assert 0.0 <= min(r.knock_intensity) and max(r.knock_intensity) <= 1.0
    assert lo_v >= 0.0 and hi_v <= 5.0
    assert hi_v == 5.0  # saturação atingida
