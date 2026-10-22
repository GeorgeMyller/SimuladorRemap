"""``tools/rehash.py``, ``gen_data.py``, ``gen_ve.py`` e JSON canónico (RF-24, RF-25)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from simremap.catalog.canonical import canonical_dumps, canonical_sha256, sha256_bytes
from simremap.catalog.settings import DEFAULT_CATALOG_DIR
from simremap.catalog.tools import gen_data, rehash
from simremap.catalog.tools.gen_ve import VE_PARAMS, rpm_axis, ve_grid, ve_value
from simremap.catalog.tools.jsonfmt import dumps_pretty


class TestCanonical:
    def test_rules(self) -> None:
        assert canonical_dumps({"b": 1.5, "a": [1, "ç"]}) == '{"a":[1,"ç"],"b":1.5}'.encode()
        assert canonical_sha256({"x": 0.1, "y": 2}) == canonical_sha256({"y": 2, "x": 0.1})
        assert canonical_sha256({"x": 0.1}) != canonical_sha256({"x": 0.10000000000000002})

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            canonical_dumps({"x": [math.nan]})


class TestRehash:
    def test_manifest_matches_package(self) -> None:
        current = json.loads((DEFAULT_CATALOG_DIR / "manifest.json").read_text("utf-8"))
        rebuilt = rehash.build_manifest(DEFAULT_CATALOG_DIR, current["catalog_version"])
        assert rebuilt == current
        assert [f["path"] for f in current["files"]] == sorted(f["path"] for f in current["files"])
        assert len(current["files"]) == 17

    def test_check_mode(self, catalog_copy: Any) -> None:
        assert rehash.main(["--catalog-dir", str(catalog_copy.root), "--check"]) == 0
        path = catalog_copy.root / "fuels" / "e0.json"
        path.write_text(path.read_text("utf-8").replace("Gasolina pura", "Gasolina sem etanol"))
        assert rehash.main(["--catalog-dir", str(catalog_copy.root), "--check"]) == 1
        assert rehash.main(["--catalog-dir", str(catalog_copy.root)]) == 0
        catalog_copy.load()

    def test_updates_calibration_refs(self, catalog_copy: Any) -> None:
        rel = "vehicles/hatch-20t-gdi/calibrations/oem-stage.json"
        path = catalog_copy.root / rel
        path.write_bytes(path.read_bytes() + b"\n")
        result = rehash.rehash(catalog_copy.root)
        assert result.updated_vehicle_files == ["vehicles/hatch-20t-gdi/vehicle.json"]
        assert result.written
        vehicle = catalog_copy.read("vehicles/hatch-20t-gdi/vehicle.json")
        assert vehicle["factory_calibrations"][0]["sha256"] == sha256_bytes(path.read_bytes())
        catalog_copy.load()

    def test_refuses_curve_change_without_version(self, catalog_copy: Any) -> None:
        rel = "vehicles/coupe-30t-i6/reference-curves/stock-e27.json"
        catalog_copy.edit(rel, lambda d: d["points"][0].update(egt_c=701.0), rehash_after=False)
        assert rehash.main(["--catalog-dir", str(catalog_copy.root)]) == 2
        assert rehash.main(["--catalog-dir", str(catalog_copy.root), "--version", "2.0.0"]) == 0
        assert catalog_copy.load().catalog_version == "2.0.0"

    def test_invalid_version(self, catalog_copy: Any) -> None:
        with pytest.raises(rehash.RehashError, match="SemVer"):
            rehash.rehash(catalog_copy.root, "v2")

    def test_noop_does_not_write(self, catalog_copy: Any) -> None:
        assert not rehash.rehash(catalog_copy.root).written

    def test_fresh_manifest(self, catalog_copy: Any) -> None:
        (catalog_copy.root / "manifest.json").unlink()
        result = rehash.rehash(catalog_copy.root)
        assert result.written and result.manifest["catalog_version"] == "1.0.0"


class TestGenerator:
    def test_regeneration_is_byte_identical(self, tmp_path: Path) -> None:
        """Os dados do pacote são exatamente a saída do gerador (sem edição manual)."""
        out = tmp_path / "gen"
        assert gen_data.main(["--catalog-dir", str(out)]) == 0
        produced = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.json"))
        packaged = sorted(p.relative_to(DEFAULT_CATALOG_DIR).as_posix()
                          for p in DEFAULT_CATALOG_DIR.rglob("*.json"))  # fmt: skip
        assert produced == packaged
        for rel in produced:
            assert (out / rel).read_bytes() == (DEFAULT_CATALOG_DIR / rel).read_bytes(), rel
        assert gen_data.main(["--catalog-dir", str(out)]) == 2  # recusa sem --force

    def test_checksum_and_hash_helpers(self) -> None:
        assert gen_data.oem_checksum("0" * 64) == gen_data.oem_checksum("0" * 64)
        assert len(gen_data.oem_checksum("a" * 64)) == 8
        cal = {"vehicle_id": "a-b", "profile_id": "oem-stage", "fuel_model": {}, "tables": {},
               "strategies": {}, "profile_params": {"x": 1.23456789}}  # fmt: skip
        rounded = dict(cal, profile_params={"x": 1.234568})
        assert gen_data.calibration_content_hash(cal) == canonical_sha256(rounded)


class TestGenVe:
    def test_axes(self) -> None:
        assert rpm_axis(6800.0)[-1] == 7000.0
        assert rpm_axis(7800.0)[-1] == 7800.0
        grid = ve_grid("classic-20t-swap", 7800.0)
        assert grid.y_values[-1] == 300.0 and grid.x_values[-1] == 7800.0

    def test_clip(self) -> None:
        params = VE_PARAMS["hatch-20t-gdi"]
        assert ve_value(params, 100_000.0, 100.0) == 0.20


def test_pretty_json_layout() -> None:
    text = dumps_pretty({"a": [1, 2], "b": {"c": [[1, 2], [3]]}, "d": [], "e": {}})
    assert text.endswith("\n")
    assert '"a": [1, 2]' in text and '"d": []' in text and '"e": {}' in text
    assert json.loads(text) == {"a": [1, 2], "b": {"c": [[1, 2], [3]]}, "d": [], "e": {}}
