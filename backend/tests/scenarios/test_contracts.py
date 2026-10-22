"""Contratos dos cenários de treino (T069 a T071; scenarios RF-01, RF-03, RF-05, RF-07,
RF-12, RF-17, RF-18; D-REST-09; file-formats 5)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.scenarios.contracts import (
    Attempt,
    AttemptRun,
    AttemptState,
    ChallengeCriteria,
    Criterion,
    CriterionKind,
    Evaluation,
    HiddenDefect,
    Hint,
    HintUnlock,
    InitialCalibration,
    PackageExportRequest,
    PackageImportResult,
    PlayerProfile,
    PlayerProfileCreate,
    Role,
    Scenario,
    ScenarioConstraints,
    ScenarioStats,
    SignedPackage,
    SubmitRequest,
    derive_attempt_seed,
)

UUID = "6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70"
SHA = "2" * 64
NOW = datetime(2026, 10, 18, 10, tzinfo=UTC)


def criterion(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "criterion_id": "min-whp",
        "kind": "min_whp",
        "comparator": "ge",
        "threshold": 250.0,
    }
    data.update(over)
    return data


def scenario(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "scenario_id": "stage1-oem",
        "kind": "base",
        "title": "Stage 1 OEM",
        "briefing": "Aumente a potência sem knock.",
        "vehicle_id": "hatch-20t-gdi",
        "initial_calibration": {"source": "vehicle_stock", "content_hash": SHA},
        "fuel_id": "e27",
        "objectives": ["Ganhar 15 % de potência"],
        "criteria": {"criteria": [criterion()]},
    }
    data.update(over)
    return data


def attempt(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "attempt_id": UUID,
        "scenario_id": "stage1-oem",
        "scenario_sha256": SHA,
        "profile_id": UUID,
        "nickname": "lucas_01",
        "state": "in_progress",
        "calibration_id": UUID,
        "seed": derive_attempt_seed(UUID),
        "started_at": NOW.isoformat(),
    }
    data.update(over)
    return data


def evaluation(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "evaluation_id": UUID,
        "attempt_id": UUID,
        "submission_index": 1,
        "status": "completed",
        "evaluator_version": "1.0.0",
        "passed": True,
        "total_score": 87.5,
        "results": [
            {
                "criterion_id": "min-whp",
                "kind": "min_whp",
                "comparator": "ge",
                "measured": 260.0,
                "threshold": 250.0,
                "passed": True,
                "score": 100.0,
                "weight": 1.0,
                "mandatory": True,
                "evidence": [
                    {"run_id": "r1", "channel": "whp", "url": "/api/v1/runs/r1/log?format=json"}
                ],
            }
        ],
    }
    data.update(over)
    return data


class TestPlayerProfile:
    def test_create(self) -> None:
        create = PlayerProfileCreate(nickname="Lucas_01")
        assert create.role == Role.STUDENT
        profile = PlayerProfile(
            nickname="prof-marcos", role=Role.INSTRUCTOR, profile_id=UUID, created_at=NOW
        )
        assert PlayerProfile.model_validate_json(profile.model_dump_json()) == profile

    @pytest.mark.parametrize("nickname", ["ab", "a" * 25, "lucas silva", "lucas@x", "çao"])
    def test_nickname_rejections(self, nickname: str) -> None:
        with pytest.raises(ValidationError):
            PlayerProfileCreate(nickname=nickname)

    def test_no_extra_personal_fields(self) -> None:
        with pytest.raises(ValidationError):
            PlayerProfileCreate.model_validate({"nickname": "lucas", "email": "x@y.z"})


class TestHiddenDefect:
    @pytest.mark.parametrize(
        ("data", "fault_kind"),
        [
            ({"kind": "fuel_pump_weak", "fuel_pump_max_lph": 60}, "fuel_pump_weak"),
            (
                {"kind": "injector_clogged", "cylinder": 2, "injector_flow_factor": 0.6},
                "injector_clogged",
            ),
            ({"kind": "iat_sensor_bias", "sensor_bias_c": -20}, "sensor_bias"),
            ({"kind": "wastegate_stuck", "stuck_position_pct": 0}, "wastegate_stuck"),
        ],
    )
    def test_to_physics_fault(self, data: dict[str, Any], fault_kind: str) -> None:
        defect = HiddenDefect.model_validate(data | {"start_t_sim_s": 2.0})
        fault = defect.to_physics_fault()
        assert fault.kind == fault_kind
        assert fault.start_t_sim_s == 2.0
        if fault_kind == "sensor_bias":
            assert (fault.sensor_channel, fault.sensor_bias) == ("iat_c", -20)

    @pytest.mark.parametrize(
        "data",
        [
            {"kind": "fuel_pump_weak"},
            {"kind": "fuel_pump_weak", "fuel_pump_max_lph": 59},
            {"kind": "injector_clogged", "cylinder": 1, "injector_flow_factor": 0.4},
            {"kind": "iat_sensor_bias", "sensor_bias_c": 31},
            {"kind": "wastegate_stuck", "stuck_position_pct": 10, "cylinder": 1},
            {"kind": "boost_leak"},
        ],
    )
    def test_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            HiddenDefect.model_validate(data)


class TestScenario:
    def test_valid_round_trip(self) -> None:
        sc = Scenario.model_validate(scenario())
        assert sc.initial_profile_id == "oem-stage"
        assert sc.constraints.max_submissions == 5
        assert sc.ambient.pressure_kpa == 99.0
        assert Scenario.model_validate_json(sc.model_dump_json()) == sc
        content = sc.evaluable_content()
        assert "created_at" not in content
        assert "origin" not in content

    def test_sixteen_criterion_kinds(self) -> None:
        assert len(CriterionKind) == 16

    def test_student_view_hides_defect(self) -> None:
        sc = Scenario.model_validate(
            scenario(
                kind="challenge",
                scenario_id="challenge-pump",
                hidden_defect={"kind": "fuel_pump_weak", "fuel_pump_max_lph": 90},
                criteria={
                    "criteria": [
                        criterion(),
                        criterion(criterion_id="diag", kind="defect_diagnosis", comparator="bool"),
                    ]
                },
            )
        )
        assert sc.for_student().hidden_defect is None
        assert sc.hidden_defect is not None

    @pytest.mark.parametrize(
        ("over", "match"),
        [
            (
                {"criteria": {"criteria": [criterion(kind="defect_diagnosis", comparator="bool")]}},
                "hidden_defect",
            ),
            ({"criteria": {"criteria": [criterion()], "require_defect_diagnosis": True}}, "hidden"),
            ({"hints": [{"order": 2, "text": "dica"}]}, "hints.order"),
            ({"builtin": True}, "builtin"),
            ({"builtin": True, "origin": "builtin", "kind": "challenge"}, "builtin"),
            ({"scenario_id": "S1"}, "pattern"),
            ({"fuel_id": "e85"}, "fuel_id"),
            ({"objectives": []}, "objectives"),
            ({"constraints": {"allowed_final_profiles": ["ecu-x"]}}, "allowed_final_profiles"),
            ({"initial_calibration": {"source": "embedded", "content_hash": SHA}}, "payload"),
        ],
    )
    def test_rejections(self, over: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            Scenario.model_validate(scenario(**over))

    def test_builtin(self) -> None:
        sc = Scenario.model_validate(scenario(builtin=True, origin="builtin"))
        assert sc.builtin

    @pytest.mark.parametrize(
        ("over", "match"),
        [
            ({"threshold": None}, "threshold"),
            ({"comparator": "ge", "band": 1.0}, "band"),
            ({"kind": "min_knock_margin_deg", "threshold": 7.0}, "0,5 e 6"),
            ({"kind": "min_knock_margin_deg", "threshold": 0.4}, "0,5 e 6"),
            ({"weight": 0}, "greater"),
            ({"kind": "max_power"}, "kind"),
        ],
    )
    def test_criterion_rejections(self, over: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            Criterion.model_validate(criterion(**over))

    def test_criteria_and_parts(self) -> None:
        Criterion.model_validate(criterion(kind="min_knock_margin_deg", threshold=2.0))
        Criterion.model_validate(criterion(comparator="le", band=5.0, kind="max_egt_c"))
        with pytest.raises(ValidationError, match="duplicado"):
            ChallengeCriteria.model_validate({"criteria": [criterion(), criterion()]})
        assert HintUnlock().free
        assert not HintUnlock(after_event="engine_failed").free
        assert Hint(order=1, text="olhe o knock").unlock.free
        assert ScenarioConstraints().allowed_run_types == [
            "baseline_pull",
            "sweep_pull",
            "multi_pull",
        ]
        InitialCalibration(source="embedded", payload={"tables": {}}, content_hash=SHA)


class TestAttempt:
    def test_seed_derivation(self) -> None:
        expected = int(hashlib.sha256(UUID.encode()).hexdigest()[:15], 16)
        assert derive_attempt_seed(UUID) == expected
        assert 0 <= expected < 2**60

    def test_round_trip(self) -> None:
        att = Attempt.model_validate(
            attempt(
                runs=[
                    {
                        "run_id": "01JAB0000000000000000000AB",
                        "run_type": "baseline_pull",
                        "valid": True,
                    }
                ]
            )
        )
        assert att.replay_status == "not_run"
        assert att.runs[0].pull_index == 0
        assert att.state == AttemptState.IN_PROGRESS
        assert Attempt.model_validate_json(att.model_dump_json()) == att

    def test_imported_without_profile(self) -> None:
        att = Attempt.model_validate(attempt(origin="imported", profile_id=None))
        assert att.profile_id is None

    @pytest.mark.parametrize(
        "over",
        [
            {"profile_id": None},
            {"hints_revealed": [1, 1]},
            {"state": "queued"},
            {"submissions": -1},
            {"replay_status": "ok"},
            {"started_at": "2026-10-18T10:00:00"},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            Attempt.model_validate(attempt(**over))

    def test_attempt_run_and_submit(self) -> None:
        with pytest.raises(ValidationError):
            AttemptRun(run_id="r", run_type="sweep_pull", valid=True, invalid_reason="x")
        with pytest.raises(ValidationError):
            AttemptRun(run_id="r", run_type="sweep_pull", valid=False, pull_index=-1)
        req = SubmitRequest(calibration_id=UUID, declared_defect="none")
        assert req.run_ids is None
        with pytest.raises(ValidationError):
            SubmitRequest(calibration_id=UUID, run_ids=["r"] * 11)


class TestEvaluation:
    def test_completed(self) -> None:
        ev = Evaluation.model_validate(evaluation())
        assert ev.error_code is None
        assert Evaluation.model_validate_json(ev.model_dump_json()) == ev
        content = ev.hashable_content()
        assert "evaluation_id" not in content and "created_at" not in content

    def test_error_code(self) -> None:
        ev = Evaluation.model_validate(
            evaluation(status="error", passed=None, total_score=None, error_code="PROBE_FAILED")
        )
        assert ev.error_code == "PROBE_FAILED"

    @pytest.mark.parametrize(
        "over",
        [
            {"status": "error", "error_code": None},
            {"status": "error", "error_code": "OOPS"},
            {"error_code": "PROBE_FAILED"},
            {"passed": None},
            {"status": "pending"},
            {"total_score": 101.0},
            {"evaluator_version": "1"},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            Evaluation.model_validate(evaluation(**over))

    def test_pending(self) -> None:
        ev = Evaluation.model_validate(
            evaluation(status="pending", passed=None, total_score=None, results=[])
        )
        assert ev.status == "pending"


class TestPackages:
    def test_signed_package(self) -> None:
        pkg = SignedPackage.model_validate(
            {
                "kind": "challenge",
                "created_at": "2026-10-18T10:00:00Z",
                "producer": {"app_version": "1.0.0", "install_id": UUID, "nickname": "prof_marcos"},
                "payload": {"scenario": {"scenario_id": "challenge-400whp-e27"}},
                "sha256": SHA,
            }
        )
        assert pkg.format_version == 1
        assert pkg.hmac_sha256 is None
        assert pkg.supported
        assert set(pkg.hashable_content()) == {"format_version", "kind", "payload"}
        assert SignedPackage.model_validate_json(pkg.model_dump_json()) == pkg
        future = SignedPackage.model_validate(pkg.model_dump() | {"format_version": 2})
        assert not future.supported
        with pytest.raises(ValidationError):
            SignedPackage.model_validate(pkg.model_dump() | {"format_version": 0})
        with pytest.raises(ValidationError):
            SignedPackage.model_validate(pkg.model_dump() | {"sha256": "abc"})

    def test_export_request(self) -> None:
        PackageExportRequest(kind="challenge", scenario_id="stage1-oem")
        PackageExportRequest(kind="attempt", attempt_id=UUID)
        with pytest.raises(ValidationError):
            PackageExportRequest(kind="attempt", scenario_id="stage1-oem")
        with pytest.raises(ValidationError):
            PackageExportRequest(kind="challenge")

    def test_import_result(self) -> None:
        res = PackageImportResult(
            package_sha256=SHA,
            kind="attempt",
            scenario_id="stage1-oem",
            attempt_id=UUID,
            recomputed_evaluation=Evaluation.model_validate(evaluation()),
        )
        assert PackageImportResult.model_validate_json(res.model_dump_json()) == res


class TestStats:
    def test_stats(self) -> None:
        stats = ScenarioStats(
            scenario_id="stage1-oem",
            started=10,
            passed=8,
            failed_final=1,
            abandoned=1,
            completion_rate_pct=80.0,
            median_submissions_to_pass=2.0,
        )
        assert ScenarioStats.model_validate_json(stats.model_dump_json()) == stats
        empty = ScenarioStats(
            scenario_id="stage1-oem",
            started=0,
            passed=0,
            failed_final=0,
            abandoned=0,
            completion_rate_pct=None,
            median_submissions_to_pass=None,
        )
        assert empty.completion_rate_pct is None
        with pytest.raises(ValidationError):
            ScenarioStats.model_validate(stats.model_dump() | {"passed": 20})
        with pytest.raises(ValidationError):
            ScenarioStats.model_validate(empty.model_dump() | {"completion_rate_pct": 0.0})
