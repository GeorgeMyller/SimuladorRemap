"""Contrato da ordem do tick com estágios instrumentados.

T124; dyno RF-03, RF-26; simulation-bus 1.

Nota de layout: o ``actions.md`` aponta ``tests/contract/test_tick_order.py``; o escopo de
escrita deste componente é ``tests/dyno``, por isso o teste vive aqui.
"""

from __future__ import annotations

from typing import Any

import pytest
from dyno_helpers import (
    SESSION_ID,
    drain,
    make_task,
    modified_content,
    run_to_result,
    start_run,
)

from simremap.dyno.contracts import ProbeOverrides, RunState
from simremap.dyno.runner import DynoSimTask, apply_probe
from simremap.ecu.calibration import CONTENT_FIELDS, canonical_json, compute_content_hash


class _Proxy:
    def __init__(self, real: Any, calls: list[str]) -> None:
        self._real = real
        self._calls = calls

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class PhysicsProxy(_Proxy):
    def __init__(self, real: Any, calls: list[str]) -> None:
        super().__init__(real, calls)
        self.commands: list[Any] = []

    def read_sensors(self, *args: Any) -> Any:
        self._calls.append("sensors")
        return self._real.read_sensors(*args)

    def step(self, commands: Any, load: Any, dt: float) -> Any:
        self._calls.append("physics")
        self.commands.append(commands)
        return self._real.step(commands, load, dt)


class EcuProxy(_Proxy):
    def __init__(self, real: Any, calls: list[str]) -> None:
        super().__init__(real, calls)
        self.results: list[Any] = []
        self.hashes: list[str] = []

    @property
    def runtime(self) -> Any:
        return self._real.runtime

    def step(self, sensors: Any, dt: float) -> Any:
        self._calls.append("ecu")
        result = self._real.step(sensors, dt)
        self.results.append(result)
        self.hashes.append(self._real.runtime.compiled.content_hash)
        return result

    def set_knock_open_loop(self, enabled: bool) -> None:
        self._real.set_knock_open_loop(enabled)


class DamageProxy(_Proxy):
    def step(self, state: Any, dt: float, status: Any = None) -> Any:
        self._calls.append("damage")
        return self._real.step(state, dt, status)


class SamplerProxy(_Proxy):
    def on_tick(self, rec: Any) -> None:
        self._calls.append("telemetry")
        self._real.on_tick(rec)


def instrument(task: DynoSimTask) -> tuple[list[str], PhysicsProxy, EcuProxy]:
    calls: list[str] = []
    parts = task.session
    physics = PhysicsProxy(parts.physics, calls)
    ecu = EcuProxy(parts.ecu, calls)
    parts.physics = physics  # type: ignore[assignment]
    parts.ecu = ecu
    parts.damage = DamageProxy(parts.damage, calls)  # type: ignore[assignment]
    task._main_damage = parts.damage
    parts.sampler = SamplerProxy(parts.sampler, calls)
    return calls, physics, ecu


def test_rf03_order_over_10000_ticks() -> None:
    task = make_task()
    calls, _, _ = instrument(task)
    for _ in range(10_000):
        task.step()
    expected = ["sensors", "ecu", "physics", "damage", "telemetry"]
    assert len(calls) == 50_000
    for i in range(10_000):
        assert calls[5 * i : 5 * i + 5] == expected, i
    frames = [e for e in drain(task) if e["type"] == "telemetry.frame"]
    assert len(frames) == pytest.approx(500, abs=2)  # 50 FPS em 10 s
    indices = [f["payload"]["frame_index"] for f in frames]
    assert indices == sorted(indices) and len(set(indices)) == len(indices)
    assert all(f["payload"]["run_id"] is None for f in frames)


def test_rf26_probe_offset_after_ecu_arbitration_in_every_tick() -> None:
    task = make_task(attempt_id="3f1a2b3c-4d5e-4f60-8a7b-9c0d1e2f3a4b")
    _, physics, ecu = instrument(task)
    marks: list[int] = []

    def mark(t: DynoSimTask) -> None:
        marks.append(len(physics.commands) if t.run_active else -1)

    request = {
        "run_type": "sweep_pull",
        "end_rpm": 3500,
        "probe": {"ignition_offset_deg": 2.0, "knock_control_open_loop": True},
    }
    out = run_to_result(task, request, on_tick=mark)
    assert out.run.state == RunState.COMPLETED
    active = [m - 1 for m in marks if m > 0]
    assert len(active) > 1000
    for i in active:
        sent = physics.commands[i].ignition_advance_deg
        commanded = ecu.results[i].commands.ignition_advance_deg
        assert [s - c for s, c in zip(sent, commanded, strict=True)] == pytest.approx([2.0] * 4)
    # Depois da sonda: avanço igual ao da ECU, knock em malha fechada e dano normal de volta.
    task.step()
    assert (
        physics.commands[-1].ignition_advance_deg == ecu.results[-1].commands.ignition_advance_deg
    )
    assert ecu.runtime.knock.open_loop is False
    assert task.probe is None


def test_probe_uses_damage_off_and_restores_session_model() -> None:
    task = make_task()
    main = task.session.damage
    start_run(
        task,
        {"run_type": "sweep_pull", "end_rpm": 3500, "probe": {"ignition_offset_deg": -2.0}},
    )
    assert task.session.damage is not main
    assert task.session.damage.damage_enabled is False
    run_to_result(task)
    assert task.session.damage is main


def test_apply_probe_clamps_and_is_identity_for_zero() -> None:
    task = make_task()
    task.step()
    commands = task.session.ecu.step(task.session.physics.read_sensors(), task.dt).commands
    assert apply_probe(commands, ProbeOverrides()) is commands
    shifted = apply_probe(commands, ProbeOverrides(ignition_offset_deg=10.0))
    assert all(a <= 60.0 for a in shifted.ignition_advance_deg)


def _apply_command(request_id: str, ignition_offset: float) -> dict[str, object]:
    content = modified_content(ignition_offset_deg=ignition_offset)
    return {
        "type": "calibration.apply",
        "request_id": request_id,
        "session_id": SESSION_ID,
        "calibration_id": "cal-test",
        "version": 2,
        "content_hash": compute_content_hash(content),
        "mode": "full",
        "payload_json": canonical_json(
            content.model_dump(mode="json", include=set(CONTENT_FIELDS))
        ),
    }


def test_calibration_swap_happens_at_tick_boundary_without_mixing() -> None:
    task = make_task()
    _, _, ecu = instrument(task)
    for _ in range(100):
        task.step()
    drain(task)
    old_hash = ecu.hashes[-1]
    command = _apply_command("req-1", 3.0)
    task.handle_command(command)
    boundary_t = task.t_sim_s
    for _ in range(5):
        task.step()
    hashes = ecu.hashes[-6:]
    assert hashes[0] == old_hash
    assert all(h == command["content_hash"] for h in ecu.hashes[-5:])
    acks = [e for e in drain(task) if e["type"] == "ack"]
    assert len(acks) == 1
    ack = acks[0]["payload"]
    assert ack["request_id"] == "req-1" and ack["ok"] is True
    assert ack["applied_t_sim_s"] == pytest.approx(boundary_t)
    assert ack["content_hash"] == command["content_hash"]


def test_calibration_cancel_before_boundary_and_invalid_payload() -> None:
    task = make_task()
    _, _, ecu = instrument(task)
    task.step()
    old = ecu.hashes[-1]
    task.handle_command(_apply_command("req-2", 1.0))
    task.handle_command({"type": "calibration.cancel", "request_id": "req-2"})
    task.step()
    assert ecu.hashes[-1] == old
    acks = [e["payload"] for e in drain(task) if e["type"] == "ack"]
    assert acks == [
        {"command": "calibration.cancel", "request_id": "req-2", "ok": True, "cancelled": True}
    ]
    bad = _apply_command("req-3", 0.0)
    bad["payload_json"] = "{}"
    task.handle_command(bad)
    task.step()
    acks = [e["payload"] for e in drain(task) if e["type"] == "ack"]
    assert acks[0]["ok"] is False and acks[0]["code"] == "CALIBRATION_INVALID"
