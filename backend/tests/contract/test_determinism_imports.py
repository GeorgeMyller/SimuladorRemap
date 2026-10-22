"""Recusa ``time``/``random``/estado global do NumPy nos pacotes do laço (T089; D-07)."""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

import simremap

LOOP_PACKAGES = ("physics", "damage", "ecu", "profiles", "dyno", "telemetry")
BANNED_MODULES = frozenset({"time", "random"})
ALLOWED_NUMPY_RANDOM = frozenset({"Generator", "PCG64", "SeedSequence", "BitGenerator"})
SRC = Path(simremap.__file__).resolve().parent


def violations(source: str, filename: str = "<src>") -> list[str]:  # noqa: PLR0912
    """Lista as violações D-07 de um módulo (``import``, ``from ... import`` e atributos)."""
    tree = ast.parse(source, filename)
    found: list[str] = []
    numpy_aliases = {"numpy"}
    random_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BANNED_MODULES:
                    found.append(f"{filename}:{node.lineno}: import {alias.name}")
                if alias.name == "numpy":
                    numpy_aliases.add(alias.asname or "numpy")
                if alias.name == "numpy.random":
                    random_aliases.add(alias.asname or "numpy.random")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in BANNED_MODULES:
                found.append(f"{filename}:{node.lineno}: from {node.module} import ...")
            if node.module == "numpy.random":
                for alias in node.names:
                    if alias.name not in ALLOWED_NUMPY_RANDOM:
                        found.append(f"{filename}:{node.lineno}: numpy.random.{alias.name}")
            if node.module == "numpy":
                for alias in node.names:
                    if alias.name == "random":
                        random_aliases.add(alias.asname or "random")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        is_np_random = (
            isinstance(base, ast.Attribute)
            and base.attr == "random"
            and isinstance(base.value, ast.Name)
            and base.value.id in numpy_aliases
        ) or (isinstance(base, ast.Name) and base.id in random_aliases)
        if is_np_random and node.attr not in ALLOWED_NUMPY_RANDOM:
            found.append(f"{filename}:{node.lineno}: numpy.random.{node.attr}")
    return found


def _loop_files() -> list[Path]:
    files: list[Path] = []
    for package in LOOP_PACKAGES:
        files.extend(sorted((SRC / package).rglob("*.py")))
    return files


def test_loop_packages_exist() -> None:
    for package in LOOP_PACKAGES:
        assert (SRC / package / "__init__.py").is_file()


@pytest.mark.parametrize("path", _loop_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_wall_clock_or_global_rng(path: Path) -> None:
    assert violations(path.read_text("utf-8"), str(path.relative_to(SRC))) == []


@pytest.mark.parametrize("package", LOOP_PACKAGES)
def test_imported_loop_modules_do_not_bind_banned(package: str) -> None:
    pkg = importlib.import_module(f"simremap.{package}")
    for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg.__name__}."):
        try:
            module = importlib.import_module(info.name)
        except ImportError:  # módulo de outro componente ainda incompleto: o AST já cobre
            continue
        for banned in BANNED_MODULES:
            value = getattr(module, banned, None)
            assert getattr(value, "__name__", None) != banned, f"{info.name} liga {banned}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import time", 1),
        ("import random as r", 1),
        ("from time import perf_counter", 1),
        ("import numpy as np\nnp.random.rand(3)", 1),
        ("import numpy as np\nnp.random.default_rng(1)", 1),
        ("from numpy.random import seed", 1),
        ("from numpy import random as npr\nnpr.normal()", 1),
        ("import numpy.random as nr\nnr.uniform()", 1),
        ("import numpy as np\nnp.random.Generator(np.random.PCG64(1))", 0),
        ("from numpy.random import Generator, PCG64, SeedSequence", 0),
        ("import datetime\nimport numpy as np\nnp.zeros(3)", 0),
    ],
)
def test_checker_detects_banned_usage(source: str, expected: int) -> None:
    assert len(violations(source)) == expected
