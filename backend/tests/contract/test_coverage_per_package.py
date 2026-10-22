"""``scripts/coverage_per_package.py`` (T013; RF-19; D-25)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "coverage_per_package.py"


def _file(statements: int, covered: int, branches: int = 0, covered_branches: int = 0) -> Any:
    return {
        "summary": {
            "num_statements": statements,
            "covered_lines": covered,
            "num_branches": branches,
            "covered_branches": covered_branches,
        }
    }


def _run(tmp_path: Path, files: dict[str, Any], *args: str) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"files": files}), "utf-8")
    return subprocess.run(  # noqa: S603 - script do repositório com argumentos fixos
        [sys.executable, str(SCRIPT), "--coverage", str(report), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_passes_and_ignores_empty_packages(tmp_path: Path) -> None:
    files = {
        "src/simremap/core/a.py": _file(100, 90, 20, 18),
        "src/simremap/core/__init__.py": _file(0, 0),
        "src/simremap/physics/__init__.py": _file(2, 0),
        "src/simremap/__init__.py": _file(1, 1),
        "outro/modulo.py": _file(10, 0),
    }
    result = _run(tmp_path, files, "--min", "85", "--packages", "core", "physics", "dyno")
    assert result.returncode == 0, result.stderr
    assert "90.00%" in result.stdout
    assert "physics" in result.stdout and "ignorado" in result.stdout


def test_fails_listing_packages_below_minimum(tmp_path: Path) -> None:
    files = {
        "src/simremap/core/a.py": _file(100, 84),
        "src/simremap/db/b.py": _file(100, 99, 10, 1),
        "/abs/backend/src/simremap/api/c.py": _file(50, 20),
    }
    result = _run(tmp_path, files, "--min", "85", "--packages", "core", "db", "api")
    assert result.returncode == 1
    assert "core (84.00 %)" in result.stderr
    assert "api (40.00 %)" in result.stderr
    assert "db" not in result.stderr  # (99 + 1) / 110 = 90,9 %


def test_missing_report(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--coverage", str(tmp_path / "nada.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_aggregate_rejects_bad_report() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("cov_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cov_script"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("cov_script", None)
    try:
        module.aggregate({"x": 1})
    except ValueError as exc:
        assert "files" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("esperava ValueError")
