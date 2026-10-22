"""Contratos da telemetria e do datalog (T059 a T061; tel RF-02, RF-04, RF-07, RF-11,
RF-12, RF-14, RF-19, RF-24; file-formats 4)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from simremap.dyno.contracts import RunState, RunStatePayload
from simremap.telemetry.contracts import (
    DEFAULT_CHANNELS,
    ComparisonBin,
    DataLog,
    DataLogHeader,
    DataLogSummary,
    FrameStats,
    KnockEventPayload,
    KnockSpectrum,
    LimiterEventPayload,
    LogCompareRequest,
    LogComparison,
    LogRef,
    PressureTrace,
    PullSegment,
    TelemetryChannel,
    TelemetryFrame,
    TelemetrySubscription,
    WsClientMessage,
    WsEnvelope,
    WsErrorPayload,
    channel_name,
    split_cylinder_channel,
)

SHA = "1" * 64


def channel(name: str = "rpm", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "base": name,
        "unit": "rpm",
        "kind": "scalar",
        "aggregation": "last",
        "decimals": 0,
        "source": "EngineState.rpm",
    }
    data.update(over)
    return data


def header(n: int = 3, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": "01JAB0000000000000000000AB",
        "session_id": "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c",
        "vehicle_id": "hatch-20t-gdi",
        "profile_id": "oem-stage",
        "calibration_hash": SHA,
        "fuel_id": "e27",
        "seed": 42,
        "sim_hz": 1000,
        "start_tick": 1000,
        "n_samples": n,
        "channels": [
            channel(),
            channel(
                "knock_intensity_cyl1",
                base="knock_intensity",
                cylinder=1,
                kind="per_cylinder",
                aggregation="max",
                unit="-",
                decimals=3,
                source="SensorReadings.knock_intensity[0]",
            ),
        ],
        "pulls": [{"pull_index": 1, "start_index": 0, "end_index": n, "state": "completed"}],
        "events": [{"index": 1, "type": "event.knock", "payload": {"cylinder": 1}}],
        "terminal_state": "completed",
    }
    data.update(over)
    return data


def datalog(n: int = 3, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "header": header(n),
        "t_sim_s": [1.0 + i / 1000 for i in range(n)],
        "data": {"rpm": [3000.0] * n, "knock_intensity_cyl1": [0.0, None, 0.1][:n]},
        "sha256": SHA,
    }
    data.update(over)
    return data


def summary(
    log_id: str = "01JAB0000000000000000000AB", vehicle: str = "hatch-20t-gdi"
) -> dict[str, Any]:
    return {
        "log_id": log_id,
        "run_id": None,
        "vehicle_id": vehicle,
        "sha256": SHA,
        "n_samples": 3,
        "sim_hz": 1000,
        "source": "simulated",
    }


def comparison_bin(rpm: int) -> dict[str, Any]:
    return {
        "rpm_bin": rpm,
        "torque_nm_a": 300.0,
        "torque_nm_b": 320.0,
        "delta_torque_nm": 20.0,
        "power_kw_a": 90.0,
        "power_kw_b": 96.0,
        "delta_power_kw": 6.0,
        "whp_a": 105.0,
        "whp_b": 112.0,
        "delta_whp": 7.0,
        "lambda_a": 0.82,
        "lambda_b": None,
        "delta_lambda": None,
        "egt_c_a": 880.0,
        "egt_c_b": 890.0,
        "delta_egt_c": 10.0,
        "knock_intensity_max_a": 0.1,
        "knock_intensity_max_b": 0.2,
        "n_a": 10,
        "n_b": 12,
    }


class TestChannels:
    def test_names(self) -> None:
        assert channel_name("egt_c", 3) == "egt_c_cyl3"
        assert channel_name("rpm") == "rpm"
        assert split_cylinder_channel("knock_intensity_cyl4") == ("knock_intensity", 4)
        assert split_cylinder_channel("egt_pre_turbo_c") == ("egt_pre_turbo_c", None)
        assert DEFAULT_CHANNELS == ("rpm", "map_kpa", "lambda", "torque_nm", "power_kw")

    def test_valid(self) -> None:
        ch = TelemetryChannel.model_validate(
            channel("fuel_cut", kind="flag", aggregation="any", unit="flag")
        )
        assert TelemetryChannel.model_validate_json(ch.model_dump_json()) == ch

    @pytest.mark.parametrize(
        "over",
        [
            {"name": "Rpm", "base": "Rpm"},
            {"name": "egt_c_cyl3", "base": "egt_c", "cylinder": 2, "kind": "per_cylinder"},
            {"name": "egt_c_cyl3", "base": "egt_c", "cylinder": 3},
            {"kind": "flag", "aggregation": "max"},
            {"min_value": 10.0, "max_value": 1.0},
            {"decimals": 5},
            {"aggregation": "avg"},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            TelemetryChannel.model_validate(channel(**over))


class TestEnvelope:
    def test_envelope_round_trip(self) -> None:
        env = WsEnvelope(type="event.limiter", seq=19010, t_sim_s=41.0, payload={"x": 1})
        assert env.v == 1
        assert WsEnvelope.model_validate_json(env.model_dump_json()) == env

    def test_wrap_run_state(self) -> None:
        payload = RunStatePayload(
            session_id="0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c",
            run_id=None,
            run_type=None,
            state=RunState.IDLE,
            previous_state=None,
        )
        env = WsEnvelope.wrap("run.state", 0, 0.0, payload)
        assert env.payload["state"] == "idle"

    @pytest.mark.parametrize(
        "data",
        [
            {"v": 2, "type": "error", "seq": 1, "t_sim_s": 0.0, "payload": {}},
            {"type": "pong", "seq": 1, "t_sim_s": 0.0, "payload": {}},
            {"type": "error", "seq": -1, "t_sim_s": 0.0, "payload": {}},
            {"type": "error", "seq": 1, "t_sim_s": -0.1, "payload": {}},
        ],
    )
    def test_envelope_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            WsEnvelope.model_validate(data)

    def test_client_message(self) -> None:
        msg = WsClientMessage(type="control.ping", payload={"nonce": "a1b2c3"})
        assert WsClientMessage.model_validate_json(msg.model_dump_json()) == msg
        assert WsClientMessage(type="control.throttle").payload == {}
        with pytest.raises(ValidationError, match="16 kB"):
            WsClientMessage(type="control.subscribe", payload={"x": "a" * 17000})
        with pytest.raises(ValidationError):
            WsClientMessage.model_validate({"type": "control.reset"})

    def test_subscription(self) -> None:
        sub = TelemetrySubscription(channels=["rpm", "knock_spectrum", "cyl_pressure_trace"])
        assert sub.fps == 50
        assert sub.wants_spectrum
        assert sub.trace_cylinder == 1
        assert sub.scalar_channels == ["rpm"]
        explicit = TelemetrySubscription(channels=["rpm"], pressure_trace={"cylinder": 2})
        assert explicit.trace_cylinder == 2
        assert not explicit.wants_spectrum
        assert TelemetrySubscription(channels=["rpm"]).trace_cylinder is None

    @pytest.mark.parametrize(
        "data",
        [
            {"channels": []},
            {"channels": ["rpm"] * 129},
            {"channels": ["rpm"], "fps": 29},
            {"channels": ["rpm"], "fps": 61},
            {"channels": ["rpm"], "pressure_trace": {"cylinder": 9}},
            {"channels": ["rpm"], "pressure_trace": {"cyl": 1}},
        ],
    )
    def test_subscription_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            TelemetrySubscription.model_validate(data)


class TestFrame:
    def test_frame(self) -> None:
        frame = TelemetryFrame(
            session_id="c3f1a2",
            run_id=None,
            frame_index=1871,
            window_ticks=20,
            channels={"rpm": 5012.0, "turbo_rpm": None, "fuel_cut": 0},
            knock_spectrum=KnockSpectrum(
                bins_hz=[i * 78.125 for i in range(256)],
                magnitude_db=[-60.0] * 256,
                resonance_hz=[6720.0, 11147.0, 13987.0, 15334.0],
            ),
            cyl_pressure_trace=PressureTrace(
                cylinder=2, crank_deg=[-10, 0, 10], p_bar=[20, 80, 60]
            ),
            stats=FrameStats(
                fps_actual=50.0, dropped_frames=0, dropped_events=0, real_time_factor=1.0, tick=1
            ),
        )
        assert TelemetryFrame.model_validate_json(frame.model_dump_json()) == frame
        data = frame.model_dump()
        with pytest.raises(ValidationError):
            TelemetryFrame.model_validate(data | {"window_ticks": 35})
        with pytest.raises(ValidationError):
            KnockSpectrum(bins_hz=[0.0], magnitude_db=[0.0], resonance_hz=[1.0] * 4)
        with pytest.raises(ValidationError):
            PressureTrace(cylinder=1, crank_deg=[0], p_bar=[1.0, 2.0])


class TestPayloads:
    def test_knock_payload(self) -> None:
        payload = KnockEventPayload(
            run_id="r-01J9Z",
            cylinder=3,
            knock_class="severe",
            intensity=0.98,
            intensity_raw=6.4,
            mapo_kpa=640.0,
            theta_onset_deg_atdc=14.0,
            retard_deg=8.0,
            rpm=5480.0,
            p_max_bar=118.6,
            threshold=0.15,
        )
        assert payload.simulated_only is False
        assert KnockEventPayload.model_validate_json(payload.model_dump_json()) == payload
        data = payload.model_dump()
        for over in ({"intensity": 6.4}, {"knock_class": "none"}, {"cylinder": 0}):
            with pytest.raises(ValidationError):
                KnockEventPayload.model_validate(data | over)

    def test_limiter_payload(self) -> None:
        payload = LimiterEventPayload(
            run_id=None, kind="rev_limiter", phase="hard", active=True, rpm=7004.0
        )
        assert LimiterEventPayload.model_validate_json(payload.model_dump_json()) == payload
        with pytest.raises(ValidationError):
            LimiterEventPayload(run_id=None, kind="launch", active=True, rpm=1.0)  # type: ignore[arg-type]

    def test_error_payload(self) -> None:
        gap = WsErrorPayload(
            code="WS_RESUME_GAP", title="Lacuna", oldest_available_seq=10, fatal=False
        )
        assert gap.oldest_available_seq == 10
        with pytest.raises(ValidationError):
            WsErrorPayload(code="ws_bad", title="x")
        with pytest.raises(ValidationError, match="WS_RESUME_GAP"):
            WsErrorPayload(code="WS_UNKNOWN_CHANNEL", title="x", oldest_available_seq=1)


class TestDataLog:
    def test_round_trip(self) -> None:
        log = DataLog.model_validate(datalog())
        assert log.source == "simulated"
        assert log.header.format_version == 1
        assert DataLog.model_validate_json(log.model_dump_json()) == log

    def test_imported_log_id(self) -> None:
        log = DataLog.model_validate(
            datalog(source="imported", log_id="imp-0123456789ab", created_at="2026-10-18T10:00:00Z")
        )
        assert log.log_id == "imp-0123456789ab"
        with pytest.raises(ValidationError, match="imp-"):
            DataLog.model_validate(datalog(source="imported", log_id="foo"))

    @pytest.mark.parametrize(
        "over",
        [
            {"t_sim_s": [1.0, 2.0]},
            {"data": {"rpm": [1.0] * 3}},
            {"data": {"knock_intensity_cyl1": [0.0] * 3, "rpm": [1.0] * 3}},
            {"data": {"rpm": [1.0] * 2, "knock_intensity_cyl1": [0.0] * 3}},
            {"sha256": "XYZ"},
        ],
    )
    def test_schema_invalid(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DataLog.model_validate(datalog(**over))

    @pytest.mark.parametrize(
        "over",
        [
            {"format_version": 2},
            {"channels": [channel(), channel()]},
            {"pulls": [{"pull_index": 1, "start_index": 0, "end_index": 9, "state": "completed"}]},
            {"events": [{"index": 3, "type": "event.knock", "payload": {}}]},
            {"terminal_state": "running"},
            {"sim_hz": 50},
        ],
    )
    def test_header_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DataLogHeader.model_validate(header(**over))

    def test_pull_segment(self) -> None:
        with pytest.raises(ValidationError):
            PullSegment(pull_index=1, start_index=5, end_index=2, state="completed")


class TestCompare:
    def test_log_ref(self) -> None:
        assert LogRef(run_id="01JAB0000000000000000000AB").log_id is None
        with pytest.raises(ValidationError):
            LogRef()
        with pytest.raises(ValidationError):
            LogRef(run_id="a", log_id="b")

    def test_request(self) -> None:
        req = LogCompareRequest(a=LogRef(run_id="a"), b=LogRef(log_id="imp-0123456789ab"))
        assert (req.bin_rpm, req.min_samples_per_bin) == (100, 5)
        with pytest.raises(ValidationError):
            LogCompareRequest.model_validate(req.model_dump() | {"bin_rpm": 40})

    def test_comparison(self) -> None:
        comp = LogComparison(
            a=DataLogSummary.model_validate(summary()),
            b=DataLogSummary.model_validate(summary("imp-0123456789ab", "coupe-30t-i6")),
            bin_rpm=100,
            vehicle_mismatch=True,
            bins=[ComparisonBin.model_validate(comparison_bin(r)) for r in (3000, 3100)],
            peak_torque_nm_a=300.0,
            peak_torque_nm_b=320.0,
            peak_whp_a=105.0,
            peak_whp_b=112.0,
            delta_peak_whp_pct=6.67,
            max_abs_delta={"torque_nm": 20.0},
            bins_only_in_a=0,
            bins_only_in_b=1,
        )
        assert LogComparison.model_validate_json(comp.model_dump_json()) == comp
        data = comp.model_dump()
        data["bins"] = list(reversed(data["bins"]))
        with pytest.raises(ValidationError, match="crescente"):
            LogComparison.model_validate(data)
