"""Paridade Python × Rust dos kernels da física (feature 003, T005; D-04, Q2).

Compara a referência Python de ``simremap.physics`` com ``simremap_rs.cycle`` em entradas
aleatórias com seed (tolerância relativa 1e-9 por grandeza, Q2):

- ``CycleKernel`` × ``CycleSolver.solve_uncached_py`` (ciclo Otto, Wiebe, fração queimada);
- funções soltas (``gamma_of_t``, ``internal_energy_per_kg``, ``burn_duration_deg``, ``fsum``);
- ``GasKernel`` × ``PhysicsEngine._gas_py`` (VE, borboleta, compressor/turbina e eixo do
  turbo, supercharger antes/depois da borboleta, aspirado, fuga, bypass e antilag);
- ``ThermalKernel`` × ``PhysicsEngine._thermal_py`` (ECT, óleo, EGT, pistão, ponto quente);
- trajetória completa ``PhysicsEngine(native=True)`` × ``PhysicsEngine(native=False)``.

Salta o módulo inteiro sem a extensão (``native()`` é ``None``).
"""

from __future__ import annotations

import copy
import importlib.util
import math
import random
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.core.native import native
from simremap.physics.combustion import FlameCoefficients, burn_duration_deg
from simremap.physics.contracts import PhysicsConfig, PhysicsFault
from simremap.physics.cycle_solver import (
    CycleSolver,
    gamma_of_t,
    internal_energy_per_kg,
    quantize_inputs,
)
from simremap.physics.engine import EngineVars, PhysicsEngine
from simremap.physics.geometry import CylinderGeometry
from simremap.physics.kernels import cycle_module
from simremap.physics.reference import ReferenceDriver, RpmHoldRig

pytestmark = pytest.mark.skipif(
    native() is None or cycle_module() is None,
    reason="extensão simremap_rs ausente ou desligada (SIMREMAP_NATIVE=off)",
)

REL = 1e-9
SEED = 20261019


def _physics_fixtures() -> Any:
    name = "cycle_parity_physics_fixtures"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[1] / "physics" / "conftest.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _vehicles() -> dict[str, VehicleSpec]:
    fx = _physics_fixtures()
    hatch = fx.build_hatch()
    muscle = fx.build_muscle()
    sc_post = muscle.model_copy(
        update={"engine": muscle.engine.model_copy(update={"throttle_location": "post_compressor"})}
    )
    return {
        "hatch": hatch,
        "coupe": fx.build_coupe(),
        "classic": fx.build_classic(),
        "muscle": muscle,
        "muscle-post": sc_post,
        "na": fx.build_na(hatch),
    }


VEHICLES = _vehicles()
FUELS: dict[str, FuelSpec] = _physics_fixtures().FUELS


def _close(a: Any, b: Any, where: str) -> None:
    if isinstance(a, list | tuple):
        assert isinstance(b, list | tuple), where
        assert len(a) == len(b), f"{where}: tamanhos {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _close(x, y, f"{where}[{i}]")
        return
    if isinstance(a, float) or isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return
        assert b == pytest.approx(a, rel=REL, abs=1e-300), f"{where}: {a!r} ≠ {b!r}"
        return
    assert a == b, f"{where}: {a!r} ≠ {b!r}"


def _fuel_for(vehicle: VehicleSpec) -> FuelSpec:
    return FUELS[vehicle.stock_fuel_id]


# ------------------------------------------------------------------ ciclo fechado
@pytest.mark.parametrize("name", ["hatch", "coupe", "classic", "muscle"])
def test_cycle_kernel_matches_python(name: str) -> None:
    vehicle = VEHICLES[name]
    geo = CylinderGeometry.from_engine(vehicle.engine)
    py = CycleSolver(geo, vehicle.engine, 5.0, 2.0, 0, native=False)
    rs = CycleSolver(geo, vehicle.engine, 5.0, 2.0, 0, native=True)
    assert rs.native and not py.native
    rng = random.Random(SEED)
    for fuel_id in ("e27", "e100"):
        fuel = FUELS.get(fuel_id) or _fuel_for(vehicle)
        index = py.register_fuel(fuel)
        assert rs.register_fuel(fuel) == index
        for _ in range(60):
            lam = 0.0 if rng.random() < 0.1 else rng.uniform(0.55, 1.6)
            _, inp = quantize_inputs(
                rng.uniform(700.0, 8000.0),
                rng.uniform(5e-5, 1.2e-3),
                lam,
                rng.uniform(0.0, 0.4),
                rng.uniform(290.0, 420.0),
                rng.uniform(-15.0, 50.0),
                -150 + rng.randint(-25, 25),
                130 + rng.randint(-20, 15),
                rng.uniform(340.0, 460.0),
                rng.random() > 0.15,
                index,
            )
            a = py.solve_uncached_py(inp)
            b = rs.solve_uncached(inp)
            for field in a.__slots__:
                _close(getattr(a, field), getattr(b, field), field)


def test_scalar_functions_match_python() -> None:
    cycle = cycle_module()
    assert cycle is not None
    rng = random.Random(SEED + 1)
    flame = FlameCoefficients(0.36, -0.55, 1.10)
    for _ in range(500):
        t = rng.uniform(-50.0, 4000.0)
        _close(gamma_of_t(t), cycle.gamma_of_t(t), "gamma_of_t")
        _close(internal_energy_per_kg(t), cycle.internal_energy_per_kg(t), "u(T)")
        args = (
            rng.uniform(50.0, 9000.0),
            rng.uniform(0.5, 1.7),
            rng.uniform(0.0, 0.4),
            rng.uniform(300.0, 1200.0),
            rng.uniform(50.0, 9000.0),
        )
        rpm, lam, x_r, t_u, p = args
        ref = burn_duration_deg(rpm, lam, flame, x_r, t_u, p, 50.0, 3500.0)
        got = cycle.burn_duration_deg(
            rpm, lam, flame.b_m, flame.b_phi, flame.phi_m, x_r, t_u, p, 50.0, 3500.0
        )
        _close(ref, got, "burn_duration_deg")
        values = [rng.uniform(-1.0, 1.0) * 10.0 ** rng.randint(-12, 12) for _ in range(9)]
        assert cycle.fsum(values) == math.fsum(values)
    assert cycle.fsum([]) == math.fsum([])
    assert cycle.fsum([1e100, 1.0, -1e100, 1e-30]) == math.fsum([1e100, 1.0, -1e100, 1e-30])


# ------------------------------------------------------------------ gás e fecho térmico
def _engine(vehicle: VehicleSpec, *, use: bool | None, **config: Any) -> PhysicsEngine:
    return PhysicsEngine(
        PhysicsConfig(**config), vehicle, _fuel_for(vehicle), initial_ect_c=90.0, native=use
    )


def _run(engine: PhysicsEngine, rpm: float, ticks: int) -> Iterator[None]:
    driver = ReferenceDriver(engine, engine.vehicle.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=rpm)
    engine.crank(rpm)
    dt = engine.resolved.dt
    state = None
    for _ in range(ticks):
        cmds = driver.commands(engine.read_sensors(), dt)
        state = engine.step(cmds, rig.load(state, engine.rpm, dt), dt)
        yield


def _snapshot(engine: PhysicsEngine) -> dict[str, Any]:
    return {f: copy.copy(getattr(engine.vars, f)) for f in EngineVars.__slots__}


def _restore(engine: PhysicsEngine, snap: dict[str, Any]) -> None:
    for f, value in snap.items():
        setattr(engine.vars, f, copy.copy(value))


THERMAL_FIELDS = (
    "ect_c",
    "oil_c",
    "egt_col_k",
    "tc_col_c",
    "egt_gas_k",
    "tc_egt_c",
    "piston_c",
    "hot_spot_c",
)

GAS_CASES = [
    ("hatch", {}),
    ("hatch", {"faults": [PhysicsFault(kind="boost_leak", leak_area_mm2=40.0)]}),
    ("coupe", {"sim_hz": 500}),
    ("classic", {}),
    ("muscle", {}),
    ("muscle-post", {}),
    ("na", {"faults": [PhysicsFault(kind="boost_leak", leak_area_mm2=20.0)]}),
]


@pytest.mark.parametrize(
    ("name", "config"), GAS_CASES, ids=[f"{n}-{i}" for i, (n, _) in enumerate(GAS_CASES)]
)
def test_gas_and_thermal_kernels_match_python(name: str, config: dict[str, Any]) -> None:
    vehicle = VEHICLES[name]
    engine = _engine(vehicle, use=True, **config)
    assert engine.native
    rng = random.Random(SEED + len(name))
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    checked = 0
    for k, _ in enumerate(_run(engine, rng.uniform(2500.0, 6500.0), 600)):
        if k % 20:
            continue
        cmd = driver.commands(engine.read_sensors(), engine.resolved.dt).model_copy(
            update={
                "bypass_open": rng.random() < 0.3,
                "antilag_air_pct": rng.choice([0.0, rng.uniform(1.0, 60.0)]),
                "throttle_pct": rng.uniform(0.0, 100.0),
            }
        )
        v = engine.vars
        v.throttle_pct = cmd.throttle_pct
        v.surge_s = rng.choice([-1.0, rng.uniform(0.0, 0.3)])
        snap = _snapshot(engine)
        t0 = v.tick / engine.resolved.sim_hz
        ref = engine._gas_py(cmd, engine.resolved.dt, t0)
        after = _snapshot(engine)
        _restore(engine, snap)
        got = engine._gas_native(cmd, t0)
        for f in ref.__slots__:
            _close(getattr(ref, f), getattr(got, f), f"diag.{f}")
        for f, value in after.items():
            _close(value, getattr(engine.vars, f), f"vars.{f}")
        # fecho térmico, a correr e parado
        for running in (True, False):
            _restore(engine, after)
            imep = rng.uniform(0.0, 3000.0)
            probe_py = engine._thermal_py(running, v.rpm, engine.resolved.dt, imep)
            th_py = _snapshot(engine)
            _restore(engine, after)
            assert engine._thermal_kernel is not None
            out = engine._thermal_kernel.step(
                running,
                engine.vars.rpm,
                engine.resolved.dt,
                imep,
                engine.vars.t_amb_k,
                engine.vars.fan_m_s,
                engine.vars.ect_c,
                engine.vars.oil_c,
                engine.vars.egt_col_k,
                engine.vars.tc_col_c,
                engine.vars.qwall_last,
                engine.vars.m_air_last,
                engine.vars.m_fuel_last,
                engine.vars.port_k_last,
                engine.vars.fire_last,
                engine.vars.egt_gas_k,
                engine.vars.tc_egt_c,
                engine.vars.piston_c,
                engine.vars.hot_spot_c,
            )
            for f, value in zip(THERMAL_FIELDS, out[:8], strict=True):
                _close(th_py[f], value, f"thermal.{f}")
            _close(probe_py, out[8], "thermal.egt_probe")
        _restore(engine, after)
        checked += 1
    assert checked >= 25


# ------------------------------------------------------------------ trajetória completa
@pytest.mark.parametrize("name", ["hatch", "coupe", "classic", "muscle", "na"])
def test_engine_trajectory_native_matches_python(name: str) -> None:
    vehicle = VEHICLES[name]
    a = _engine(vehicle, use=False, seed=7)
    b = _engine(vehicle, use=True, seed=7)
    assert b.native and not a.native and b.solver.native and not a.solver.native
    for _ in zip(_run(a, 5000.0, 1500), _run(b, 5000.0, 1500), strict=True):
        pass
    for f in EngineVars.__slots__:
        _close(getattr(a.vars, f), getattr(b.vars, f), f)
    assert a.solver.misses > 0


def test_native_selector_and_forced_python() -> None:
    vehicle = VEHICLES["hatch"]
    assert _engine(vehicle, use=None).native
    forced = _engine(vehicle, use=False)
    assert not forced.native and not forced.solver.native
