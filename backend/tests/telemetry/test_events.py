"""``event.knock``, ``event.limiter`` e ``event.failure`` (T167; tel RF-11 a RF-13; D-17;
D-WS-01 a D-WS-03; websocket-telemetry 3.3 a 3.5)."""

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Any

from tel_helpers import make_sampler_task, pump, start_run

from simremap.damage.config import DamageConfig
from simremap.damage.contracts import FailureEvent
from simremap.dyno.contracts import RunStatePayload
from simremap.telemetry.broadcaster import ConnectionQueue, KnockRateGuard, TelemetryStream
from simremap.telemetry.contracts import KnockEventPayload, LimiterEventPayload
from simremap.telemetry.logbook import Logbook, SessionMeta

META = SessionMeta("hatch-20t-gdi", "oem-stage", "e27", 7, "a" * 64)


def _knock(t: float, cylinder: int) -> dict[str, Any]:
    return {"type": "event.knock", "t_sim_s": t, "payload": {"cylinder": cylinder}}


def test_knock_rate_guard_10_per_second_per_cylinder() -> None:
    guard = KnockRateGuard()
    allowed = [guard.allow(_knock(i * 0.02, 1)) for i in range(50)]  # 50/s (1 por ciclo)
    assert sum(allowed) == 10 and guard.suppressed == 40
    # Mesmo ciclo, cilindros 2 e 3: 2 eventos com o mesmo t_sim_s.
    assert guard.allow(_knock(0.5, 2)) and guard.allow(_knock(0.5, 3))
    # Uma janela de 1 s depois, o cilindro 1 volta a publicar.
    assert guard.allow(_knock(1.21, 1))


async def test_failure_before_engine_failed_and_in_log() -> None:
    from dyno_helpers import modified_content

    task = make_sampler_task(calibration=modified_content(boost_kpa=280.0, ignition_offset_deg=8.0))
    book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0)
    stream = TelemetryStream(task.session.payload.session_id, book)
    queue = ConnectionQueue()
    stream.attach(queue)
    run_id = "01JAB0000000000000000000FA"
    start_run(task, {"run_type": "sweep_pull", "end_rpm": 6300}, run_id)
    pump(task, stream, 120_000, until=lambda e: e["type"] == "telemetry.log_end")
    order: list[dict[str, Any]] = []
    while (item := queue.pop()) is not None:
        if item["type"] != "telemetry.frame":
            order.append(item)
    kinds = [e["type"] for e in order]
    failures = [e for e in order if e["type"] == "event.failure"]
    assert failures, kinds
    catastrophic = [f for f in failures if f["payload"]["catastrophic"]]
    assert catastrophic
    FailureEvent.model_validate(catastrophic[-1]["payload"])  # sem renomear campos
    assert "mode" in catastrophic[-1]["payload"] and "component_id" in catastrophic[-1]["payload"]
    states = [e for e in order if e["type"] == "run.state"]
    final = states[-1]
    assert final["payload"]["state"] == "engine_failed"
    assert order.index(catastrophic[-1]) < order.index(final)
    assert catastrophic[-1]["seq"] < final["seq"]
    for state in states:
        RunStatePayload.model_validate(state["payload"])
    await book.wait_idle()
    assert run_id not in book.pending  # log fechado pelo telemetry.log_end


async def test_log_keeps_failure_events_and_terminal_state() -> None:
    from dyno_helpers import modified_content

    task = make_sampler_task(calibration=modified_content(boost_kpa=280.0, ignition_offset_deg=8.0))
    built: list[Any] = []
    book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0)
    original = book.build

    def capture(pending: Any) -> Any:
        data = original(pending)
        built.append(data)
        return data

    book.build = capture  # type: ignore[method-assign]
    stream = TelemetryStream(task.session.payload.session_id, book)
    run_id = "01JAB0000000000000000000FB"
    start_run(task, {"run_type": "sweep_pull", "end_rpm": 6300}, run_id)
    pump(task, stream, 120_000, until=lambda e: e["type"] == "telemetry.log_end")
    await book.wait_idle()
    assert built, "log não foi construído"
    header = built[0].header
    assert header.terminal_state == "engine_failed"
    types = [e.type for e in header.events]
    assert "event.failure" in types and types.count("run.state") >= 3
    failure = next(e for e in header.events if e.type == "event.failure")
    assert failure.payload["catastrophic"] is True
    assert 0 <= failure.index < header.n_samples


def test_limiter_transitions_from_real_loop() -> None:
    task = make_sampler_task()
    task.handle_command({"type": "operator.throttle", "throttle_pct": 100.0})
    events = pump(
        task,
        None,
        8000,
        until=lambda e: e["type"] == "event.limiter" and not e["payload"]["active"],
    )
    limiter = [e for e in events if e["type"] == "event.limiter"]
    assert limiter and limiter[0]["payload"]["active"] is True
    assert limiter[0]["payload"]["kind"] == "rev_limiter"
    assert limiter[0]["payload"]["phase"] in ("soft", "hard")
    for e in limiter:
        LimiterEventPayload.model_validate(e["payload"])
    states = [(e["payload"]["active"], e["payload"]["phase"]) for e in limiter]
    assert all(a != b for a, b in itertools.pairwise(states))  # 1 por transição
    # Ao soltar o acelerador, o limitador libera: 1 evento com active = false.
    task.handle_command({"type": "operator.throttle", "throttle_pct": 0.0})
    later = pump(
        task,
        None,
        20_000,
        until=lambda e: e["type"] == "event.limiter" and not e["payload"]["active"],
    )
    release = [e for e in later if e["type"] == "event.limiter"]
    assert release and release[-1]["payload"] == {**release[-1]["payload"], "active": False}
    assert release[-1]["payload"]["phase"] is None


def test_knock_events_from_real_damage_model_respect_rate() -> None:
    # Coeficiente literal da spec (A de Douaud-Eyzat sem o multiplicador calibrado 4,25 do
    # DamageConfig 1.2.0): a série do hatch da fixture detona, o que exercita o limite.
    task = make_sampler_task(damage_config=DamageConfig(knock_tau_multiplier=1.0))
    start_run(task, {"run_type": "sweep_pull", "end_rpm": 6000, "ramp_rate_rpm_s": 600})
    events = pump(task, None, 12_000)
    knocks = [e for e in events if e["type"] == "event.knock"]
    assert knocks, "com o coeficiente da spec a calibração de série deve detonar"
    per_window: dict[tuple[int, int], int] = defaultdict(int)
    for e in knocks:
        payload = KnockEventPayload.model_validate(e["payload"])
        assert payload.knock_class in ("light", "moderate", "severe")
        assert 0.0 <= payload.intensity <= 1.0
        per_window[(payload.cylinder, int(e["t_sim_s"]))] += 1
    assert max(per_window.values()) <= 10
