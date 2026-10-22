"""Determinismo do dano e limite de ``event.knock`` (T137; RF-28, RF-32; D-17; D-BUS-02)."""

from __future__ import annotations

from typing import Any

import pytest
from kfm_helpers import RUN, SPEC_CONFIG, Driver, ModelFactory, make_event, make_state

from simremap.damage.digest import DAMAGE_SPAWN_KEY, SUBSTREAM_NAMES, damage_streams
from simremap.damage.errors import DamageError
from simremap.damage.model import DamageModel

THR = SPEC_CONFIG.preignition_threshold_for("e27")


def busy_events(c: int, t: float, rpm: float) -> Any:
    return make_event(c, t, rpm, knock=c in (2, 3), theta_onset=10.0, p_k=3000.0 + 500.0 * c)


def busy_overrides(t: float) -> dict[str, Any]:
    return {
        "hot_spot_temp_c": [THR - 20.0, THR, THR - 40.0, THR - 10.0],
        "torque_nm": 405.0 + 20.0 * (t > 1.0),
        "egt_collector_c": 960.0,
    }


def run_busy(model: DamageModel, seconds: float, fps: int | None = None) -> str:
    driver = Driver(model, 5500.0, event_factory=busy_events, state_overrides=busy_overrides)
    frame_every = None if fps is None else round(1000 / fps)
    for state in driver.run(seconds):
        if frame_every and state.tick % frame_every == 0:
            model.spectrum_frame(state.t_sim_s)
    return model.damage_digest()


class TestDigest:
    def test_20_runs_same_digest(self, make_model: ModelFactory) -> None:
        digests = {run_busy(make_model(seed=42), 2.0) for _ in range(20)}
        assert len(digests) == 1
        assert run_busy(make_model(seed=43), 2.0) not in digests

    def test_ui_frame_rate_does_not_change_digest(self, make_model: ModelFactory) -> None:
        assert run_busy(make_model(), 1.0, fps=50) == run_busy(make_model(), 1.0, fps=20)
        assert run_busy(make_model(), 1.0, fps=None) == run_busy(make_model(), 1.0, fps=50)

    def test_substreams_are_damage_owned(self) -> None:
        assert DAMAGE_SPAWN_KEY == (1,)
        assert SUBSTREAM_NAMES == ("preignition", "lspi", "knock_noise", "rod_weights", "spectrum")
        streams = damage_streams(42)
        draws = [getattr(streams, n).random() for n in SUBSTREAM_NAMES]
        assert len(set(draws)) == 5
        assert damage_streams(42).preignition.random() == draws[0]

    def test_rod_weights_fixed_per_seed(self, make_model: ModelFactory) -> None:
        assert make_model(seed=7).rod_weights == make_model(seed=7).rod_weights
        assert make_model(seed=7).rod_weights != make_model(seed=8).rod_weights


class TestSnapshot:
    def test_round_trip_continues_identically(self, make_model: ModelFactory) -> None:
        original = make_model()
        original.set_run(RUN)
        run_busy(original, 1.0)
        blob = original.snapshot()
        restored = make_model(seed=999)
        restored.load_snapshot(blob)
        assert restored.damage_digest() == original.damage_digest()
        assert restored.rod_weights == original.rod_weights
        assert restored.failures == original.failures
        tail = [make_state(1001 + k, (1001 + k) / 1000, 5500.0) for k in range(200)]
        for state in tail:
            a = original.step(state, 0.001)
            b = restored.step(state, 0.001)
            assert a.components == b.components
        assert restored.damage_digest() == original.damage_digest()

    def test_locked_snapshot_restores_frozen_state(self, make_model: ModelFactory) -> None:
        model = make_model()
        model.step(make_state(1, 0.001, 0.0, turbo_rpm=240_000.0), 0.001)
        other = make_model()
        other.load_snapshot(model.snapshot())
        assert other.engine_locked
        assert other.step(make_state(2, 0.002, 0.0), 0.001).engine_locked

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda b: b[:-8],
            lambda b: b"XX" + b[2:],
            lambda b: b[:20],
            lambda b: b[:-1] + bytes([b[-1] ^ 0xFF]),
        ],
    )
    def test_invalid_snapshot(self, make_model: ModelFactory, mutate: Any) -> None:
        model = make_model()
        with pytest.raises(DamageError) as info:
            model.load_snapshot(mutate(model.snapshot()))
        assert info.value.error_code == "DAMAGE_SNAPSHOT_INVALID"

    def test_snapshot_of_other_vehicle(self, make_model: ModelFactory, v8_vehicle: Any) -> None:
        with pytest.raises(DamageError, match="outro veículo"):
            make_model(vehicle=v8_vehicle).load_snapshot(make_model().snapshot())


class TestKnockEventRate:
    def test_severe_every_cycle_gives_10_events_per_second(self, make_model: ModelFactory) -> None:
        model = make_model(damage_enabled=False)
        driver = Driver(
            model,
            6000.0,
            event_factory=lambda c, t, r: make_event(c, t, r, knock=c == 3, theta_onset=10.0),
        )
        events = []
        for _ in driver.run(3.0):
            events.extend(model.knock_events)
        per_second = [sum(1 for e in events if k <= e.t_sim_s < k + 1) for k in range(3)]
        assert per_second == [10, 10, 10]
        assert {e.cylinder for e in events} == {3}
        payload = events[0].payload(threshold=0.15)
        assert payload["knock_class"] == "severe" and payload["simulated_only"] is True
        assert 0.0 <= payload["intensity"] <= 1.0
        assert payload["intensity_raw"] == pytest.approx(8.0)
        assert payload["p_max_bar"] == pytest.approx(90.0)

    def test_none_class_never_published(self, make_model: ModelFactory) -> None:
        model = make_model()
        for _ in Driver(model, 6000.0).run(0.5):
            assert model.knock_events == []

    def test_each_failure_is_published_once(self, make_model: ModelFactory) -> None:
        model = make_model()
        seen = []
        for state in Driver(
            model, 6000.0, event_factory=lambda c, t, r: make_event(c, t, r, knock=c == 3)
        ).run(10.0, until_locked=True):
            seen.extend(state.new_failures)
        assert seen == model.failures
        assert len({f.failure_event_id for f in seen}) == len(seen)
