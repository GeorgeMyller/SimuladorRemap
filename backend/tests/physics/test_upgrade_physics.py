"""Efeitos físicos das peças da oficina (002 RF-14 a RF-16; T025).

- ``exhaust_backpressure_scale`` (downpipe) reduz a pressão do coletor de escape e a EGT;
- ``fuel_pump_capacity_scale`` (bomba) multiplica o teto da falha ``fuel_pump_weak`` e não
  tem efeito sem falha;
- turbina upgraded: mais inércia/área ⇒ demora mais a atingir 80 % da rotação de série em
  baixa e o compressor passa mais vazão no topo;
- intercooler esportivo: IAT menor na mesma condição.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.upgrades import UpgradePackage, apply_upgrades
from simremap.physics.contracts import PhysicsFault
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig
from simremap.physics.turbo import CompressorMap, rad_s_to_rpm


def _steady(
    make_engine: Callable[..., PhysicsEngine],
    run_steady: Callable[..., Any],
    vehicle: VehicleSpec,
    rpm: float,
    **config: Any,
) -> Any:
    engine = make_engine(vehicle, noise_enabled=False, sim_hz=500, **config)
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    return run_steady(engine, driver, rpm, 5.0)


def test_downpipe_lowers_backpressure_and_egt(
    hatch: VehicleSpec,
    make_engine: Callable[..., PhysicsEngine],
    run_steady: Callable[..., Any],
) -> None:
    stock = _steady(make_engine, run_steady, hatch, 5000.0)
    free = _steady(make_engine, run_steady, hatch, 5000.0, exhaust_backpressure_scale=0.6)
    assert free.last.exhaust_manifold_kpa < stock.last.exhaust_manifold_kpa - 3.0
    assert free.egt_collector_c < stock.egt_collector_c - 10.0


def test_pump_scale_raises_weak_pump_ceiling(
    hatch: VehicleSpec,
    make_engine: Callable[..., PhysicsEngine],
    run_steady: Callable[..., Any],
) -> None:
    weak = [PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=40.0)]
    base = _steady(make_engine, run_steady, hatch, 5000.0)
    starved = _steady(make_engine, run_steady, hatch, 5000.0, faults=weak)
    pumped = _steady(
        make_engine, run_steady, hatch, 5000.0, faults=weak, fuel_pump_capacity_scale=1.8
    )
    no_fault = _steady(make_engine, run_steady, hatch, 5000.0, fuel_pump_capacity_scale=1.8)
    assert starved.lambda_collector > base.lambda_collector + 0.05  # bomba fraca empobrece
    assert pumped.lambda_collector < starved.lambda_collector - 0.03
    assert no_fault.lambda_collector == pytest.approx(base.lambda_collector, abs=1e-9)


def _spool_time(engine: PhysicsEngine, vehicle: VehicleSpec, threshold_rpm: float) -> float:
    dt = engine.resolved.dt
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=2500.0)
    engine.crank(2500.0)
    state = None
    for k in range(round(6.0 / dt)):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
        if rad_s_to_rpm(engine.vars.turbo_omega) >= threshold_rpm:
            return k * dt
    return float("inf")


def test_upgraded_turbo_lags_low_and_flows_more_high(
    hatch: VehicleSpec, make_engine: Callable[..., PhysicsEngine]
) -> None:
    upgraded = apply_upgrades(hatch, UpgradePackage(turbo="upgraded")).vehicle
    probe = make_engine(hatch, noise_enabled=False, sim_hz=500)
    _spool_time(probe, hatch, float("inf"))
    target = 0.8 * rad_s_to_rpm(probe.vars.turbo_omega)
    t_stock = _spool_time(make_engine(hatch, noise_enabled=False, sim_hz=500), hatch, target)
    t_big = _spool_time(make_engine(upgraded, noise_enabled=False, sim_hz=500), upgraded, target)
    assert t_stock < t_big
    assert hatch.turbo is not None and upgraded.turbo is not None
    stock_map = CompressorMap(hatch.turbo.compressor)
    big_map = CompressorMap(upgraded.turbo.compressor)
    n_max = hatch.turbo.compressor.n_max_rpm
    flow = stock_map.operate(1.5, n_max, 101.325, 298.15).mass_flow_kg_s
    assert big_map.operate(1.5, n_max, 101.325, 298.15).mass_flow_kg_s > flow


def test_sport_intercooler_lowers_iat(
    hatch: VehicleSpec,
    make_engine: Callable[..., PhysicsEngine],
    run_steady: Callable[..., Any],
) -> None:
    sport = apply_upgrades(hatch, UpgradePackage(intercooler="sport")).vehicle
    stock = _steady(make_engine, run_steady, hatch, 5000.0)
    cooled = _steady(make_engine, run_steady, sport, 5000.0)
    assert cooled.last.iat_c < stock.last.iat_c - 2.0
