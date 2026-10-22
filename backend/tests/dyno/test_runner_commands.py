"""Comandos do ``DynoSimTask`` e caminho de erro interno (simulation-bus 3.6; dyno RF-24, EC-14)."""

from __future__ import annotations

from typing import Any

import pytest
from dyno_helpers import RUN_ID, drain, make_task, run_to_result, start_run

from simremap.dyno.contracts import AbortReason, DynoLoad, RunState
from simremap.dyno.runner import DynoSimTask
from simremap.physics.contracts import ActuatorCommands, EngineState

SHORT = {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}


def acks(task: DynoSimTask) -> list[dict[str, Any]]:
    return [e["payload"] for e in drain(task) if e["type"] == "ack"]


def test_session_ready_and_hold_until_first_command() -> None:
    task = make_task()
    ready = [e for e in drain(task) if e["type"] == "session.ready"]
    assert ready and ready[0]["payload"]["ecu_state"] == "oem"
    assert len(ready[0]["payload"]["rod_weights"]) == 4
    t0 = task.t_sim_s
    assert t0 == pytest.approx(3.0)  # aquecimento de 3 s antes do tick 0 da sessão
    for _ in range(10):
        task.tick()
    assert task.t_sim_s == t0  # espera determinística
    task.handle_command({"type": "operator.throttle", "throttle_pct": 20.0})
    task.tick()
    assert task.t_sim_s > t0
    assert task.operator_pedal == 20.0


def test_rf24_throttle_locked_during_run_and_telemetry_config() -> None:
    task = make_task()
    start_run(task, SHORT)
    task.step()
    drain(task)
    task.handle_command({"type": "operator.throttle", "throttle_pct": 50.0})
    errors = [e["payload"] for e in drain(task) if e["type"] == "error"]
    assert errors and errors[0]["code"] == "THROTTLE_LOCKED_BY_RUN" and errors[0]["fatal"] is False
    assert task.operator_pedal == 0.0
    task.handle_command({"type": "telemetry.config", "fps": 40})
    assert task.session.sampler._pending_fps == 40  # type: ignore[attr-defined]


def test_command_acks_for_health_unknown_and_invalid() -> None:
    task = make_task()
    drain(task)
    task.handle_command({"type": "engine.health", "request_id": "h1", "include_failures": False})
    (health,) = acks(task)
    assert health["ok"] and health["health"]["intact"] is True
    assert health["health"]["failures"] == []
    task.handle_command({"type": "nope", "request_id": "u1"})
    assert acks(task)[0]["code"] == "COMMAND_UNKNOWN"
    task.handle_command({"type": "run.start", "run_id": RUN_ID, "request": {"run_type": "x"}})
    bad = acks(task)[0]
    assert bad["ok"] is False and bad["code"] == "COMMAND_FAILED"
    task.handle_command({"type": "ecu.info", "request_id": "i1"})
    info = acks(task)[0]
    assert info["profile_id"] == "oem-stage" and info["ecu_state"] == "oem"
    assert info["fuel_mismatch_suspected"] is False


def test_run_start_refusals_and_abort_of_other_run() -> None:
    task = make_task()
    start_run(task, SHORT)
    drain(task)
    start_run(task, SHORT, run_id="01JAB0000000000000000000BB")
    assert acks(task)[0]["code"] == "RUN_IN_PROGRESS"
    task.handle_command({"type": "run.abort", "run_id": "01JAB0000000000000000000BB"})
    assert acks(task)[0]["code"] == "RUN_NOT_ACTIVE"
    task.handle_command({"type": "engine.restore", "request_id": "r1"})
    assert acks(task)[0]["code"] == "RUN_IN_PROGRESS"
    task.handle_command({"type": "run.abort", "run_id": RUN_ID, "reason": "user_abort"})
    assert acks(task)[0]["ok"] is True
    out = run_to_result(task)
    assert out.run.abort_reason == AbortReason.USER_ABORT


def test_engine_destroyed_refusal_and_restore() -> None:
    from dyno_helpers import modified_content

    task = make_task(calibration=modified_content(boost_kpa=280.0, ignition_offset_deg=8.0))
    out = run_to_result(task, {"run_type": "sweep_pull", "end_rpm": 6300})
    assert out.run.state == RunState.ENGINE_FAILED
    assert out.result["engine_locked"] is True
    assert out.of_type("damage.trace")[0]["payload"]["kind"] == "failure"
    failures = out.of_type("event.failure")
    assert failures and failures[-1]["payload"]["catastrophic"] is True
    assert out.envelopes.index(failures[-1]) < out.envelopes.index(out.of_type("run.state")[-1])
    start_run(task, SHORT, run_id="01JAB0000000000000000000CC")
    assert acks(task)[0]["code"] == "ENGINE_DESTROYED"
    task.handle_command({"type": "engine.restore", "request_id": "r2"})
    restored = acks(task)[0]
    assert restored["ok"] and restored["health"]["engine_locked"] is False
    assert restored["health"]["restore_count"] == 1
    for _ in range(500):
        task.step()
    assert task.last_state is not None and task.last_state.rpm > 500.0  # motor repõe a marcha lenta


def test_ec14_exception_in_tick_aborts_run_and_loop_continues() -> None:
    task = make_task()
    start_run(task, SHORT)
    for _ in range(50):
        task.step()
    drain(task)
    physics = task.session.physics
    real_step = physics.step
    calls = {"n": 0}

    def boom(commands: ActuatorCommands, dyno_load: DynoLoad, dt: float) -> EngineState:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("falha de teste")
        return real_step(commands, dyno_load, dt)

    physics.step = boom  # type: ignore[method-assign]
    task.step()
    envelopes = drain(task)
    errors = [e["payload"] for e in envelopes if e["type"] == "error"]
    assert errors and errors[0]["code"] == "SIM_INTERNAL_ERROR"
    results = [e["payload"] for e in envelopes if e["type"] == "run.result"]
    assert results and results[0]["run"]["abort_reason"] == "internal_error"
    assert "internal_error" in results[0]["run"]["summary"]["event_codes"]
    assert task.run is None
    tick = task.tick_index
    task.step()
    assert task.tick_index == tick + 1


def test_teardown_closes_active_run_with_session_closed() -> None:
    task = make_task()
    start_run(task, SHORT)
    task.step()
    drain(task)
    task.teardown()
    results = [e["payload"] for e in drain(task) if e["type"] == "run.result"]
    assert results[0]["run"]["abort_reason"] == "session_closed"
    task.teardown()  # sem puxada: nada a fazer


def test_setup_required() -> None:
    task = DynoSimTask()
    with pytest.raises(RuntimeError):
        _ = task.session
    assert task.drain_outputs() == []


def test_profiled_ecu_stage_registry_and_swap() -> None:
    """``profile_hooks = "registry"``: ``ProfiledEcu`` do ecu-profiles e ``ecu.swap`` no laço."""
    from dyno_helpers import SESSION_ID, stock_content

    from simremap.dyno.assembly import ProfiledEcuStage, profiles_available
    from simremap.ecu.calibration import CONTENT_FIELDS, canonical_json, compute_content_hash

    assert profiles_available()
    task = make_task(profile_hooks="registry")
    stage = task.session.ecu
    assert isinstance(stage, ProfiledEcuStage)
    assert stage.profile_id == "oem-stage" and stage.ecu_state == "oem"
    assert stage.runtime is not None and stage.fuel_mismatch_suspected is False
    stage.set_knock_open_loop(True)
    assert stage.runtime.knock.open_loop is True
    stage.set_knock_open_loop(False)
    content = stock_content()
    task.handle_command(
        {
            "type": "calibration.apply",
            "request_id": "a1",
            "session_id": SESSION_ID,
            "calibration_id": "cal-x",
            "version": 3,
            "content_hash": compute_content_hash(content),
            "mode": "full",
            "payload_json": canonical_json(
                content.model_dump(mode="json", include=set(CONTENT_FIELDS))
            ),
        }
    )
    task.tick()  # na espera: aplicado na fronteira e confirmado sem avançar o tempo
    (ack,) = acks(task)
    assert ack["ok"] is True and ack["applied_t_sim_s"] == pytest.approx(task.t_sim_s)
    task.handle_command(
        {
            "type": "ecu.swap",
            "request_id": "s1",
            "session_id": SESSION_ID,
            "profile_id": "ft-pro",
            "previous_profile_id": "oem-stage",
            "ecu_state": "awaiting_base_setup",
        }
    )
    task.step()
    (swap,) = acks(task)
    assert swap["ok"] is True and swap["ecu_state"] == "awaiting_base_setup"
    assert task.session.ecu.profile_id == "ft-pro"
    assert task.session.ecu.runtime is None
    task.session.ecu.set_knock_open_loop(True)  # sem runtime: sem efeito
    task.handle_command({"type": "ecu.swap", "request_id": "s2", "ecu_state": "bad"})
    task.step()
    (bad,) = acks(task)
    assert bad["ok"] is False and bad["code"] == "CALIBRATION_INVALID"
    task.handle_command({"type": "ecu.swap.cancel", "request_id": "nada"})
    assert acks(task)[0]["cancelled"] is False
