"""Determinismo por hash, snapshot/restore e API banida (T106; RF-20, RF-25; D-07, D-08)."""

from __future__ import annotations

import ast
import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.physics.contracts import ActuatorCommands
from simremap.physics.engine import PhysicsEngine
from simremap.physics.errors import (
    ACTUATOR_COMMAND_INVALID,
    PHYSICS_SNAPSHOT_INVALID,
    PhysicsError,
)
from simremap.physics.reference import ReferenceDriver, RpmHoldRig, replay_digest

PHYSICS_SRC = Path(__file__).resolve().parents[2] / "src" / "simremap" / "physics"


def test_twenty_runs_thirty_seconds_identical_digest(
    hatch: VehicleSpec, fuels: dict[str, FuelSpec]
) -> None:
    """RF-20: 20 execuções de 30 s a 1000 Hz (processos separados) ⇒ 20 digests iguais."""
    vehicle_json = hatch.model_dump_json()
    fuel_json = fuels["e27"].model_dump_json()
    ctx = multiprocessing.get_context("spawn")
    workers = max(2, min(10, os.cpu_count() or 2))
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        futures = [
            pool.submit(
                replay_digest, vehicle_json, fuel_json, seed=2026, sim_hz=1000, seconds=30.0
            )
            for _ in range(20)
        ]
        digests = [f.result() for f in futures]
    assert len(digests) == 20
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64
    # Outra semente muda o digest (o ruído entra no estado canónico).
    other = replay_digest(vehicle_json, fuel_json, seed=2027, sim_hz=1000, seconds=1.0)
    same = replay_digest(vehicle_json, fuel_json, seed=2026, sim_hz=1000, seconds=1.0)
    assert other != same


def _drive(engine: PhysicsEngine, driver: ReferenceDriver, rig: RpmHoldRig, ticks: int) -> None:
    dt = engine.resolved.dt
    state = None
    for _ in range(ticks):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )


def test_snapshot_restore_continues_identically(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-25: restore(snapshot()) seguido de N ticks ⇒ mesmo digest da continuação."""
    engine = make_engine(hatch, seed=11)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=4000.0)
    engine.crank(4000.0)
    _drive(engine, driver, rig, 800)
    blob = engine.snapshot()
    integral, rig_int = driver.integral, rig.integral
    _drive(engine, driver, rig, 700)
    expected = engine.state_digest()

    clone = make_engine(hatch, seed=11)
    clone.restore(blob)
    driver2 = ReferenceDriver(clone, hatch.reference_command_schedule)
    driver2.integral = integral
    rig2 = RpmHoldRig(target_rpm=4000.0, integral=rig_int)
    _drive(clone, driver2, rig2, 700)
    assert clone.state_digest() == expected

    # O próprio motor também volta atrás.
    engine.restore(blob)
    assert engine.snapshot() == blob


def test_corrupted_snapshot_rejected_and_state_kept(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec, muscle: VehicleSpec
) -> None:
    """EC-11: hash, versão ou motor divergentes ⇒ PHYSICS_SNAPSHOT_INVALID, estado intacto."""
    engine = make_engine(hatch)
    engine.crank(1500.0)
    blob = engine.snapshot()
    before = engine.state_digest()
    corrupted = bytearray(blob)
    corrupted[-3] ^= 0xFF
    bad_blobs = [
        bytes(corrupted),
        b"not a snapshot",
        blob.replace(b'"schema_version":1', b'"schema_version":9'),
        blob[:20],
        make_engine(muscle).snapshot(),
    ]
    for bad in bad_blobs:
        with pytest.raises(PhysicsError) as exc:
            engine.restore(bad)
        assert exc.value.code == PHYSICS_SNAPSHOT_INVALID
        assert engine.state_digest() == before


def test_invalid_commands_do_not_touch_state(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """EC-01: listas com tamanho errado ou valores fora do limite ⇒ ACTUATOR_COMMAND_INVALID."""
    engine = make_engine(hatch)
    engine.crank(2000.0)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    good = driver.commands(None, engine.resolved.dt)
    before = engine.state_digest()
    wrong_len = ActuatorCommands(
        t_sim_s=0.0,
        injector_pw_ms=[1.0] * 6,
        ignition_advance_deg=[10.0] * 6,
        fuel_cut=[False] * 6,
        spark_cut=[False] * 6,
        throttle_pct=10.0,
    )
    bads = [
        wrong_len,
        good.model_copy(update={"injector_pw_ms": [80.0] * 4}),
        good.model_copy(update={"ignition_advance_deg": [90.0] * 4}),
        good.model_copy(update={"throttle_pct": 120.0}),
        good.model_copy(update={"vvt_intake_target_deg": float("nan")}),
        good.model_copy(update={"injection_end_deg_btdc": [0.0] * 3}),
    ]
    from simremap.physics.reference import free_load

    for bad in bads:
        with pytest.raises(PhysicsError) as exc:
            engine.step(bad, free_load(), engine.resolved.dt)
        assert exc.value.code == ACTUATOR_COMMAND_INVALID
        assert exc.value.error_status == 422
        assert engine.state_digest() == before


def test_physics_package_has_no_banned_api() -> None:
    """D-07: sem ``time``, ``random`` nem ``numpy.random`` global no pacote (lint ruff TID251)."""
    banned_modules = {"time", "random"}
    banned_np = {
        "seed",
        "rand",
        "randn",
        "randint",
        "random",
        "normal",
        "uniform",
        "choice",
        "default_rng",
        "RandomState",
        "shuffle",
        "permutation",
    }
    files = sorted(PHYSICS_SRC.glob("*.py"))
    assert len(files) >= 15
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_modules, path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned_modules, path
                if node.module == "numpy.random":
                    assert not {a.name for a in node.names} & banned_np, path
            elif isinstance(node, ast.Attribute) and node.attr in banned_np:
                inner = node.value
                if isinstance(inner, ast.Attribute) and inner.attr == "random":
                    pytest.fail(f"numpy.random.{node.attr} em {path.name}")
