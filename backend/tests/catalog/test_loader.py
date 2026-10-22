"""Loader do catálogo (RF-01, RF-02, RF-03, RF-07, RF-10, RF-19, RF-20, RF-24, RF-25, RF-27)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from simremap.catalog.errors import CATALOG_EXIT_CODE, CatalogInvalid
from simremap.catalog.loader import (
    CANONICAL_VEHICLE_IDS,
    MAX_FILE_BYTES,
    clear_calibration_validators,
    load_catalog_data,
    register_calibration_validator,
    registered_calibration_validators,
)

HATCH = "vehicles/hatch-20t-gdi/vehicle.json"
HATCH_CURVE = "vehicles/hatch-20t-gdi/reference-curves/stock-e27.json"
HATCH_CAL = "vehicles/hatch-20t-gdi/calibrations/oem-stage.json"


def _codes(exc: pytest.ExceptionInfo[CatalogInvalid]) -> list[str]:
    return [issue.code for issue in exc.value.issues]


def _issue(exc: pytest.ExceptionInfo[CatalogInvalid], code: str) -> Any:
    return next(issue for issue in exc.value.issues if issue.code == code)


class TestHappyPath:
    def test_loads_package_data(self, real_catalog: Any) -> None:
        assert tuple(real_catalog.vehicles) == CANONICAL_VEHICLE_IDS
        assert list(real_catalog.fuels) == ["e27", "e100", "podium", "e0"]
        assert real_catalog.catalog_version == "1.1.0"  # T406: afinação física
        assert len(real_catalog.catalog_sha256) == 64
        assert real_catalog.load_ms < 500.0  # RNF-01 / G-01

    def test_sha_is_deterministic(self, catalog_copy: Any, real_catalog: Any) -> None:
        again = catalog_copy.load()
        assert again.catalog_sha256 == real_catalog.catalog_sha256
        assert again.benchmark_sha256 == real_catalog.benchmark_sha256
        for vid, entry in again.vehicles.items():
            assert entry.data_sha256 == real_catalog.vehicles[vid].data_sha256

    def test_key_order_does_not_change_hash(self, catalog_copy: Any, real_catalog: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.update(dict(reversed(list(d.items())))))
        data = catalog_copy.read(HATCH)
        reordered = dict(reversed(list(data.items())))
        catalog_copy.write(HATCH, reordered)
        catalog_copy.rehash()
        again = catalog_copy.load()
        hatch = again.vehicles["hatch-20t-gdi"].data_sha256
        assert hatch == real_catalog.vehicles["hatch-20t-gdi"].data_sha256

    def test_value_change_changes_hash(self, catalog_copy: Any, real_catalog: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.update(driveline_inertia_kg_m2=2.5))
        again = catalog_copy.load()
        assert again.catalog_sha256 != real_catalog.catalog_sha256
        assert (
            again.vehicles["hatch-20t-gdi"].data_sha256
            != real_catalog.vehicles["hatch-20t-gdi"].data_sha256
        )
        assert (
            again.vehicles["coupe-30t-i6"].data_sha256
            == real_catalog.vehicles["coupe-30t-i6"].data_sha256
        )


class TestManifest:
    def test_missing_engine_field(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.pop("engine"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "SCHEMA_INVALID")
        assert issue.file == HATCH
        assert issue.pointer == "/engine"
        assert exc.value.exit_code == CATALOG_EXIT_CODE
        assert exc.value.error_code == "CATALOG_INVALID"

    def test_file_not_in_manifest(self, catalog_copy: Any) -> None:
        extra = catalog_copy.root / "vehicles" / "hatch-20t-gdi" / "reference-curves" / "x.json"
        extra.write_text("{}", encoding="utf-8")
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_NOT_IN_MANIFEST"]

    def test_file_missing(self, catalog_copy: Any) -> None:
        (catalog_copy.root / "fuels" / "e0.json").unlink()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_MISSING"]

    def test_file_changed_without_rehash(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / HATCH_CURVE
        path.write_text(path.read_text(encoding="utf-8").replace("350.0", "351.0", 1))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "FILE_HASH_MISMATCH")
        assert issue.file == HATCH_CURVE

    def test_manifest_missing(self, catalog_copy: Any) -> None:
        (catalog_copy.root / "manifest.json").unlink()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_MISSING"]

    @pytest.mark.parametrize(
        "manifest",
        [
            {"catalog_version": "1.0", "files": [{"path": "fuels/e0.json", "sha256": "0" * 64}]},
            {"catalog_version": "1.0.0", "files": []},
            {"catalog_version": "1.0.0", "files": [{"path": "fuels/e0.json", "sha256": "x"}]},
        ],
    )
    def test_manifest_schema(self, catalog_copy: Any, manifest: dict[str, Any]) -> None:
        catalog_copy.write("manifest.json", manifest)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert set(_codes(exc)) == {"MANIFEST_INVALID"}

    def test_manifest_duplicate_and_dotdot(self, catalog_copy: Any) -> None:
        data = catalog_copy.read("manifest.json")
        data["files"].append(dict(data["files"][0]))
        data["files"].append({"path": "fuels/../x.json", "sha256": "0" * 64})
        catalog_copy.write("manifest.json", data)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert set(_codes(exc)) == {"MANIFEST_INVALID", "PATH_OUTSIDE_CATALOG"}

    def test_unknown_layout(self, catalog_copy: Any) -> None:
        (catalog_copy.root / "extra").mkdir()
        (catalog_copy.root / "extra" / "notes.json").write_text("{}", encoding="utf-8")
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["CATALOG_LAYOUT_INVALID"]

    def test_dotfiles_ignored(self, catalog_copy: Any) -> None:
        (catalog_copy.root / ".DS_Store").write_bytes(b"\x00\x01")
        catalog_copy.load()

    def test_directory_unavailable(self, tmp_path: Path) -> None:
        with pytest.raises(CatalogInvalid) as exc:
            load_catalog_data(tmp_path / "nao-existe")
        assert _codes(exc) == ["CATALOG_DIR_UNAVAILABLE"]


class TestFileLimits:
    def test_symlink_outside(self, catalog_copy: Any, tmp_path: Path) -> None:
        outside = tmp_path / "segredo.json"
        outside.write_text("{}", encoding="utf-8")
        os.symlink(outside, catalog_copy.root / "vehicles" / "passwd.json")
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "PATH_OUTSIDE_CATALOG").file == "vehicles/passwd.json"

    def test_symlink_dir_inside_refused(self, catalog_copy: Any) -> None:
        os.symlink(catalog_copy.root / "fuels", catalog_copy.root / "vehicles" / "alias")
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "CATALOG_LAYOUT_INVALID" in _codes(exc)

    def test_symlink_file_inside_is_followed(self, catalog_copy: Any) -> None:
        target = catalog_copy.root / "fuels" / "e0.json"
        moved = catalog_copy.root / "vehicles" / "hatch-20t-gdi" / "e0-real.json"
        target.rename(moved)
        os.symlink(moved, target)
        with pytest.raises(CatalogInvalid) as exc:  # o destino real não está no manifesto
            catalog_copy.load()
        assert _codes(exc) == ["FILE_NOT_IN_MANIFEST"]

    def test_file_too_large(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / HATCH_CURVE
        path.write_bytes(path.read_bytes() + b" " * (MAX_FILE_BYTES + 1))
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_TOO_LARGE"]

    def test_not_utf8(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / "fuels" / "e0.json"
        path.write_bytes(path.read_text(encoding="utf-8").encode("utf-16"))
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_ENCODING_INVALID"]

    def test_bom_refused(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / "fuels" / "e0.json"
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["FILE_ENCODING_INVALID"]

    def test_malformed_json_line_and_column(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / "fuels" / "e0.json"
        path.write_text('{\n  "fuel_id": "e0",,\n}\n', encoding="utf-8")
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "JSON_INVALID")
        assert "linha 2" in issue.message


class TestCrossValidation:
    def test_displacement_pointer(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d["engine"].update(displacement_cc=2100))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "SCHEMA_INVALID").pointer == "/engine/displacement_cc"

    def test_grid_axis_not_monotonic(self, catalog_copy: Any) -> None:
        def edit(d: dict[str, Any]) -> None:
            d["engine"]["true_ve"]["x_values"][2] = d["engine"]["true_ve"]["x_values"][1]

        catalog_copy.edit(HATCH, edit)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "GRID_AXIS_NOT_MONOTONIC").pointer == "/engine/true_ve"

    def test_grid_shape(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d["engine"]["true_ve"]["z_values"].pop())
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "GRID_SHAPE_MISMATCH" in _codes(exc)

    def test_grid_value_out_of_range(self, catalog_copy: Any) -> None:
        catalog_copy.edit(
            HATCH, lambda d: d["engine"]["true_ve"]["z_values"][0].__setitem__(0, 1.4)
        )
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "GRID_VALUE_OUT_OF_RANGE").pointer == "/engine/true_ve"

    def test_grid_field_bound(self, catalog_copy: Any) -> None:
        catalog_copy.edit(
            HATCH, lambda d: d["turbo"]["turbine_efficiency"]["x_values"].__setitem__(0, "a")
        )
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["SCHEMA_INVALID"]

    def test_vehicle_id_mismatch(self, catalog_copy: Any) -> None:
        def edit(d: dict[str, Any]) -> None:
            d["vehicle_id"] = "foo-baz"
            d["stock_calibration_id"] = "stock-foo-baz-oem-stage"
            d["reference_command_schedule"]["vehicle_id"] = "foo-baz"
            d["factory_calibrations"][0]["calibration_id"] = "stock-foo-baz-oem-stage"

        catalog_copy.edit(HATCH, edit)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "VEHICLE_ID_MISMATCH" in _codes(exc)

    def test_extra_vehicle_refused(self, catalog_copy: Any) -> None:
        src = catalog_copy.root / "vehicles" / "hatch-20t-gdi"
        dst = catalog_copy.root / "vehicles" / "foo-bar"
        import shutil

        shutil.copytree(src, dst)
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        codes = _codes(exc)
        assert "CATALOG_VEHICLES_MISMATCH" in codes
        assert "VEHICLE_ID_MISMATCH" in codes
        loaded = None
        with pytest.raises(CatalogInvalid):
            loaded = catalog_copy.load(require_canonical=False)
        assert loaded is None

    def test_trademark_in_display_name(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.update(display_name="Hatch EA888"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "TRADEMARK_IN_DISPLAY_TEXT")
        assert issue.pointer == "/display_name"
        assert "ea888" in issue.message

    def test_trademark_in_fuel_and_curve_source(self, catalog_copy: Any) -> None:
        catalog_copy.edit("fuels/e0.json", lambda d: d.update(display_name="Gasolina Shelby"))
        catalog_copy.edit(HATCH_CURVE, lambda d: d.update(source="Folha medida num banco Bosch"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        files = {i.file for i in exc.value.issues if i.code == "TRADEMARK_IN_DISPLAY_TEXT"}
        assert files == {"fuels/e0.json", HATCH_CURVE}

    def test_fuel_id_must_match_file(self, catalog_copy: Any) -> None:
        catalog_copy.edit("fuels/e0.json", lambda d: d.update(fuel_id="podium"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "CATALOG_LAYOUT_INVALID" in _codes(exc)

    def test_provenance_pointer_invalid(self, catalog_copy: Any) -> None:
        catalog_copy.edit(
            HATCH, lambda d: d["provenance"].update({"/engine/nao_existe": {"kind": "estimate"}})
        )
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["PROVENANCE_POINTER_INVALID"]

    def test_stock_fuel_not_allowed(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.update(stock_fuel_id="e100"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "SCHEMA_INVALID" in _codes(exc)


class TestCurves:
    def test_missing_curve_file(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d["reference_curve_ids"].append("stock-e0"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "FILE_MISSING").pointer == "/reference_curve_ids/1"

    def test_unlisted_curve(self, catalog_copy: Any) -> None:
        data = catalog_copy.read(HATCH_CURVE)
        data["curve_id"] = "stock-e0"
        data["fuel_id"] = "e0"
        catalog_copy.write("vehicles/hatch-20t-gdi/reference-curves/stock-e0.json", data)
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["CATALOG_LAYOUT_INVALID"]

    def test_curve_point_missing_value(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH_CURVE, lambda d: d["points"][3].update(egt_c=None))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "REFERENCE_POINT_MISSING_VALUE").pointer == "/points/3/egt_c"

    def test_curve_inconsistent(self, catalog_copy: Any) -> None:
        def edit(d: dict[str, Any]) -> None:
            point = next(p for p in d["points"] if p["rpm"] == 6000)
            assert point["power_wheel_kw"] == pytest.approx(164.1, abs=0.05)
            point["power_wheel_kw"] = 170.0

        catalog_copy.edit(HATCH_CURVE, edit)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "REFERENCE_CURVE_INCONSISTENT")
        assert "6000" in issue.message

    def test_curve_step_300(self, catalog_copy: Any) -> None:
        def edit(d: dict[str, Any]) -> None:
            for i, point in enumerate(d["points"]):
                point["rpm"] = 2000 + 300 * i

        catalog_copy.edit(HATCH_CURVE, edit)
        with pytest.raises(CatalogInvalid):
            catalog_copy.load()

    def test_curve_without_license(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH_CURVE, lambda d: d.pop("license"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "SCHEMA_INVALID").pointer == "/license"

    def test_curve_short_of_rev_limit(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH_CURVE, lambda d: d.update(points=d["points"][:-2]))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert "REFERENCE_CURVE_INVALID" in _codes(exc)

    def test_curve_identity_checks(self, catalog_copy: Any) -> None:
        catalog_copy.edit(
            HATCH_CURVE,
            lambda d: d.update(curve_id="outra", vehicle_id="coupe-30t-i6", fuel_id="e100"),
        )
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        pointers = {i.pointer for i in exc.value.issues if i.code == "REFERENCE_CURVE_INVALID"}
        assert {"/curve_id", "/vehicle_id", "/fuel_id"} <= pointers


class TestCalibrations:
    def test_calibration_byte_change(self, catalog_copy: Any) -> None:
        path = catalog_copy.root / HATCH_CAL
        path.write_bytes(path.read_bytes() + b"\n")
        rel_manifest = catalog_copy.read("manifest.json")
        from simremap.catalog.canonical import sha256_bytes

        for entry in rel_manifest["files"]:
            if entry["path"] == HATCH_CAL:
                entry["sha256"] = sha256_bytes(path.read_bytes())
        catalog_copy.write("manifest.json", rel_manifest)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        issue = _issue(exc, "FILE_HASH_MISMATCH")
        assert issue.pointer == "/factory_calibrations/0/sha256"

    def test_calibration_identity(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH_CAL, lambda d: d["metadata"].update(source="user"))
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _issue(exc, "CALIBRATION_INVALID").pointer == "/metadata/source"

    def test_calibration_not_object(self, catalog_copy: Any) -> None:
        catalog_copy.write(HATCH_CAL, [1, 2])
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["CALIBRATION_INVALID"]

    def test_unreferenced_calibration(self, catalog_copy: Any) -> None:
        catalog_copy.write("vehicles/hatch-20t-gdi/calibrations/ft-pro.json", {})
        catalog_copy.rehash()
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["CATALOG_LAYOUT_INVALID"]

    def test_validator_registered_and_called(self, catalog_copy: Any) -> None:
        seen: list[str] = []

        def validator(payload: dict[str, object]) -> None:
            seen.append(str(payload["calibration_id"]))

        register_calibration_validator(validator)
        register_calibration_validator(validator)
        assert registered_calibration_validators() == (validator,)
        catalog_copy.load()
        assert sorted(seen) == sorted(
            [
                "stock-hatch-20t-gdi-oem-stage",
                "stock-coupe-30t-i6-oem-stage",
                "stock-classic-20t-swap-oem-stage",
                "stock-classic-20t-swap-ft-pro",
                "stock-muscle-v8-sc-oem-stage",
            ]
        )
        clear_calibration_validators()
        assert registered_calibration_validators() == ()

    def test_validator_code_propagates(self, catalog_copy: Any) -> None:
        class FakeEcuError(ValueError):
            def __init__(self, code: str) -> None:
                super().__init__(code)
                self.code = code

        def validator(payload: dict[str, object]) -> None:
            if payload["vehicle_id"] == "hatch-20t-gdi":
                raise FakeEcuError("TABLE_AXIS_NOT_MONOTONIC")

        register_calibration_validator(validator)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert _codes(exc) == ["TABLE_AXIS_NOT_MONOTONIC"]
        assert exc.value.issues[0].file == HATCH_CAL

    def test_validator_pydantic_error_code(self, catalog_copy: Any) -> None:
        from pydantic import BaseModel, field_validator

        class Coded(ValueError):
            code = "TABLE_VALUE_NOT_FINITE"

        class Probe(BaseModel):
            x: int

            @field_validator("x")
            @classmethod
            def _bad(cls, value: int) -> int:
                raise Coded("x")

        def validator(payload: dict[str, object]) -> None:
            Probe(x=1)

        register_calibration_validator(validator)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert set(_codes(exc)) == {"TABLE_VALUE_NOT_FINITE"}

    def test_validator_plain_value_error(self, catalog_copy: Any) -> None:
        def validator(payload: dict[str, object]) -> None:
            raise ValueError("recusada")

        register_calibration_validator(validator)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert set(_codes(exc)) == {"CALIBRATION_INVALID"}

    def test_validator_internal_failure(self, catalog_copy: Any) -> None:
        def validator(payload: dict[str, object]) -> None:
            raise RuntimeError("bug")

        register_calibration_validator(validator)
        with pytest.raises(CatalogInvalid) as exc:
            catalog_copy.load()
        assert set(_codes(exc)) == {"CALIBRATION_VALIDATOR_ERROR"}


class TestCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - interpretador do próprio venv
            [sys.executable, "-m", "simremap.catalog", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_cli_ok(self, catalog_copy: Any) -> None:
        result = self._run("--catalog-dir", str(catalog_copy.root))
        assert result.returncode == 0, result.stderr
        assert "catalog_sha256" in result.stdout

    def test_cli_exit_4(self, catalog_copy: Any) -> None:
        catalog_copy.edit(HATCH, lambda d: d.pop("engine"))
        result = self._run("--catalog-dir", str(catalog_copy.root))
        assert result.returncode == CATALOG_EXIT_CODE
        assert "CATALOG_INVALID" in result.stderr
        assert "/engine" in result.stderr

    def test_main_inprocess(self, catalog_copy: Any, capsys: pytest.CaptureFixture[str]) -> None:
        from simremap.catalog.__main__ import main

        assert main(["--catalog-dir", str(catalog_copy.root)]) == 0
        catalog_copy.edit(HATCH, lambda d: d.pop("engine"))
        assert main(["--catalog-dir", str(catalog_copy.root)]) == CATALOG_EXIT_CODE
        assert "SCHEMA_INVALID" in capsys.readouterr().err
