"""Contratos dos perfis de ECU (T054, T055; profiles RF-03, RF-17, RF-19, RF-28, RF-29)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from simremap.ecu.contracts import StrategyKind
from simremap.profiles.contracts import (
    BaseSetup,
    BaseSetupResult,
    BaseSetupUpdate,
    ChecklistItem,
    EcuProfileDescriptor,
    EcuProfileId,
    HardwareOverride,
    HardwareSheet,
    InjectorSetup,
    OemProtectionFlags,
    ProfileEvent,
    ProfileStatus,
    ProtectionLimits,
    SetupChecklist,
    SwapRequest,
    SwapResult,
    TriggerSetup,
    VehicleEcuHardware,
    WidebandSetup,
)

SESSION = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"


def descriptor(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "profile_id": "ft-pro",
        "name": "FT-Pro",
        "family": "standalone",
        "inspiration": "ECU standalone genérica",
        "descriptor_version": "1.0.0",
        "fuel_model_modes": ["speed_density_ve", "direct_pulse_ms"],
        "default_fuel_model_mode": "speed_density_ve",
        "tables": [
            {
                "kind": "ve",
                "required": True,
                "default_x": {"quantity": "rpm", "values": [1000, 7000]},
                "default_y": {"quantity": "map_kpa", "values": [30, 250]},
                "display_name": "Mapa principal",
                "live_tunable": True,
            },
            {
                "kind": "ignition_base",
                "required": True,
                "default_x": {"quantity": "rpm", "values": [1000, 7000]},
                "default_y": {"quantity": "map_kpa", "values": [30, 250]},
                "display_name": "Ignição",
                "live_tunable": False,
            },
        ],
        "strategies": [
            {"kind": kind.value, "level": "supported", "display_name": kind.value}
            for kind in StrategyKind
        ],
        "terminology": {"ve": "Mapa principal"},
        "display_units": {},
        "requires_base_setup": True,
        "base_setup_steps": ["trigger", "injectors", "fuel", "sensors", "protection", "review"],
        "navigation": [
            {
                "id": "fuel",
                "label": "Combustível",
                "items": [{"id": "fuel.ve", "label": "Mapa", "kind": "table", "target_id": "ve"}],
            }
        ],
        "live_tunable_table_ids": ["ve"],
        "load_axis_channel": "map_kpa",
        "accent_color": "#3366AA",
    }
    data.update(over)
    return data


def checklist_items(status: str = "ok") -> list[ChecklistItem]:
    return [
        ChecklistItem(id=item, required=True, status=status)  # type: ignore[arg-type]
        for item in (
            "trigger.wheel",
            "injectors.flow",
            "injectors.dead_time",
            "fuel.type",
            "sensors.map",
        )
    ]


def sheet() -> HardwareSheet:
    return HardwareSheet(
        trigger_wheel="60-2",
        phase_sensor_present=True,
        firing_order=[1, 3, 4, 2],
        injector_label_cc_min=550.0,
        tank_fuel_id="e27",
        map_sensor_label_kpa=(20.0, 300.0),
        tdc_offset_nominal_deg=84.0,
        n_cyl=4,
        displacement_cc=1984.0,
    )


def base_setup() -> BaseSetup:
    return BaseSetup(
        trigger=TriggerSetup(
            wheel="60-2",
            tdc_offset_deg=84.0,
            phase_sensor="cam_hall",
            injection_mode="sequential",
            firing_order=[1, 3, 4, 2],
        ),
        injectors=InjectorSetup(flow_cc_min=550.0, dead_time_ms=[1.2, 0.9, 0.7, 0.6, 0.55, 0.5]),
    )


class TestDescriptor:
    def test_valid_round_trip(self) -> None:
        desc = EcuProfileDescriptor.model_validate(descriptor())
        assert desc.feature_packages == ["base"]
        assert desc.display_units.mixture == "lambda"
        assert EcuProfileDescriptor.model_validate_json(desc.model_dump_json()) == desc

    def test_oem_profile(self) -> None:
        desc = EcuProfileDescriptor.model_validate(
            descriptor(
                profile_id="oem-stage",
                name="OEM-Stage",
                family="oem",
                requires_base_setup=False,
                base_setup_steps=[],
                load_axis_channel="load_pct",
            )
        )
        assert desc.profile_id == EcuProfileId.OEM_STAGE

    @pytest.mark.parametrize(
        ("over", "match"),
        [
            ({"default_fuel_model_mode": "profile_air_model"}, "default_fuel_model_mode"),
            ({"strategies": []}, "10 kinds"),
            ({"live_tunable_table_ids": ["ignition_base"]}, "live_tunable"),
            ({"family": "oem"}, "requires_base_setup"),
            ({"base_setup_steps": []}, "base_setup_steps"),
            ({"feature_packages": ["race"]}, "base"),
            ({"accent_color": "red"}, "pattern"),
            ({"descriptor_version": "1.0"}, "pattern"),
            ({"profile_id": "ecu-x"}, "profile_id"),
        ],
    )
    def test_rejections(self, over: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            EcuProfileDescriptor.model_validate(descriptor(**over))

    def test_duplicate_nav_item(self) -> None:
        nav = descriptor()["navigation"]
        nav[0]["items"].append(dict(nav[0]["items"][0]))
        with pytest.raises(ValidationError, match="duplicado"):
            EcuProfileDescriptor.model_validate(descriptor(navigation=nav))


class TestBaseSetup:
    def test_defaults(self) -> None:
        setup = BaseSetup()
        assert setup.trigger is None
        assert setup.protection.rev_limit_rpm == 7000.0
        assert setup.sensors.iat.curve == "ntc_a"
        full = base_setup()
        assert BaseSetup.model_validate_json(full.model_dump_json()) == full

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ({"wheel": "60-2", "tdc_offset_deg": 10, "firing_order": [1, 2, 2, 4]}, "FIRING_ORDER"),
            (
                {
                    "wheel": "60-2",
                    "tdc_offset_deg": 10,
                    "firing_order": [1, 3, 4, 2],
                    "ignition_mode": "sequential",
                },
                "PHASE_SENSOR",
            ),
            ({"wheel": "60-2", "tdc_offset_deg": 360, "firing_order": [1, 3, 4, 2]}, "less"),
        ],
    )
    def test_trigger_rejections(self, data: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            TriggerSetup.model_validate(data)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ({"flow_cc_min": 550, "dead_time_ms": [1.0]}, "at least 2"),
            ({"flow_cc_min": 550, "dead_time_ms": [1.0, 0.9]}, "DEAD_TIME_SHAPE"),
            (
                {"flow_cc_min": 550, "dead_time_v": [10, 8], "dead_time_ms": [1.0, 0.9]},
                "NOT_MONOTONIC",
            ),
            (
                {"flow_cc_min": 550, "dead_time_v": [8, 10], "dead_time_ms": [6.0, 0.9]},
                "OUT_OF_RANGE",
            ),
            (
                {
                    "flow_cc_min": 550,
                    "dead_time_v": [8, 10],
                    "dead_time_ms": [1.0, 0.9],
                    "flow_vs_dp_kpa": [200, 400],
                },
                "juntos",
            ),
            (
                {
                    "flow_cc_min": 550,
                    "dead_time_v": [8, 10],
                    "dead_time_ms": [1.0, 0.9],
                    "short_pulse_ms": [0.5, 1.0],
                    "short_pulse_adder_ms": [0.1],
                },
                "formas",
            ),
        ],
    )
    def test_injector_rejections(self, data: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            InjectorSetup.model_validate(data)

    def test_protection_and_wideband(self) -> None:
        with pytest.raises(ValidationError, match="OVERSPEED_BELOW_REV_LIMIT"):
            ProtectionLimits(rev_limit_rpm=7000.0, overspeed_rpm=7000.0)
        with pytest.raises(ValidationError):
            WidebandSetup(lambda_at_0v=1.0, lambda_at_5v=1.0)

    def test_update_request(self) -> None:
        upd = BaseSetupUpdate(base_setup=base_setup(), generate_base_map=True)
        assert upd.base_version is None
        assert upd.apply_limits_to_calibration
        with pytest.raises(ValidationError):
            BaseSetupUpdate.model_validate({"base_version": 0, "base_setup": {}})


class TestChecklistAndSwap:
    def test_minimum_valid(self) -> None:
        ok = SetupChecklist.from_items(checklist_items("ok"))
        assert ok.minimum_valid
        warn = SetupChecklist.from_items(checklist_items("warning"))
        assert warn.minimum_valid
        missing = SetupChecklist.from_items(checklist_items("ok")[:-1])
        assert not missing.minimum_valid
        with pytest.raises(ValidationError, match="incoerente"):
            SetupChecklist(items=checklist_items("missing"), minimum_valid=True)
        with pytest.raises(ValidationError, match="duplicado"):
            SetupChecklist.from_items(checklist_items() * 2)

    def test_swap(self) -> None:
        req = SwapRequest(target_profile_id=EcuProfileId.FT_PRO, confirm_snapshot=True)
        assert req.feature_package == "base"
        with pytest.raises(ValidationError):
            SwapRequest.model_validate({"target_profile_id": "ft-pro"})
        with pytest.raises(ValidationError):
            SwapRequest(
                target_profile_id=EcuProfileId.FT_PRO, confirm_snapshot=True, request_id="x" * 65
            )
        result = SwapResult(
            session_id=SESSION,
            previous_profile_id=EcuProfileId.OEM_STAGE,
            profile_id=EcuProfileId.FT_PRO,
            ecu_state="awaiting_base_setup",
            oem_snapshot={  # type: ignore[arg-type]
                "calibration_id": "stock-hatch-20t-gdi-oem-stage",
                "version": 1,
                "content_hash": "f" * 64,
            },
            base_setup_version=None,
            calibration_id=None,
            checklist=SetupChecklist.from_items([]),
            hardware_sheet=sheet(),
        )
        assert SwapResult.model_validate_json(result.model_dump_json()) == result

    def test_base_setup_result(self) -> None:
        res = BaseSetupResult(
            session_id=SESSION,
            profile_id=EcuProfileId.M1_RACE,
            editable=True,
            ecu_state="standalone_ready",
            base_setup_version=2,
            base_setup=base_setup(),
            setup_hash="0" * 64,
            checklist=SetupChecklist.from_items(checklist_items()),
            hardware_sheet=sheet(),
            calibration_id="6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70",
            calibration_version=1,
        )
        assert BaseSetupResult.model_validate_json(res.model_dump_json()) == res

    def test_hardware_sheet_firing_order(self) -> None:
        with pytest.raises(ValidationError):
            HardwareSheet.model_validate(sheet().model_dump() | {"firing_order": [1, 2, 3]})


class TestHardware:
    def test_vehicle_hardware(self) -> None:
        hw = VehicleEcuHardware(
            vehicle_id="hatch-20t-gdi",
            trigger_wheel="60-2",
            tdc_offset_true_deg=86.0,
            tdc_offset_nominal_deg=84.0,
            phase_sensor_present=True,
            phase_edge_true_deg=120.0,
            firing_order=[1, 3, 4, 2],
            map_sensor_kpa=(20.0, 300.0),
        )
        assert hw.swap_supported
        assert VehicleEcuHardware.model_validate_json(hw.model_dump_json()) == hw
        with pytest.raises(ValidationError):
            VehicleEcuHardware.model_validate(hw.model_dump() | {"map_sensor_kpa": (300, 20)})

    def test_override(self) -> None:
        ov = HardwareOverride(tdc_offset_shift_deg=-12.0, tank_fuel_id="e100")
        assert HardwareOverride.model_validate_json(ov.model_dump_json()) == ov
        with pytest.raises(ValidationError):
            HardwareOverride(tdc_offset_shift_deg=41.0)
        assert OemProtectionFlags().checksum_check


class TestTickOutputs:
    def test_status(self) -> None:
        st = ProfileStatus(
            t_sim_s=1.0,
            profile_id=EcuProfileId.OEM_STAGE,
            ecu_state="oem",
            sync_ok=True,
            ign_cmd_deg=[15.0] * 4,
            ign_real_minus_cmd_deg=0.0,
            timing_light_deg=15.0,
            map_read_kpa=180.0,
            lambda_read=0.82,
            oem_torque_request_nm=300.0,
            oem_torque_limiter_active="none",
        )
        assert ProfileStatus.model_validate_json(st.model_dump_json()) == st
        with pytest.raises(ValidationError, match="oem-stage"):
            ProfileStatus.model_validate(st.model_dump() | {"profile_id": "ft-pro"})

    def test_event(self) -> None:
        ev = ProfileEvent(t_sim_s=1.0, kind="trigger_sync_lost")
        assert ev.cylinder is None
        with pytest.raises(ValidationError):
            ProfileEvent(t_sim_s=1.0, kind="unknown")  # type: ignore[arg-type]
