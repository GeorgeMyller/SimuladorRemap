#!/usr/bin/env python3
"""Cobertura mínima por pacote ``simremap.<pacote>`` (platform-foundation RF-19; D-25; T013).

Lê o ``coverage.json`` do ``pytest --cov --cov-report=json`` e agrega, por pacote de topo
em ``simremap.*``, linhas e ramos cobertos (mesma fórmula do ``coverage``:
``(linhas + ramos cobertos) / (linhas + ramos)``). Falha com código 1 e lista os pacotes
abaixo do mínimo. Pacotes ainda vazios (só ``__init__.py`` ou sem instruções) são
ignorados.

Uso::

    python scripts/coverage_per_package.py --min 85 --packages core api db \\
        [--coverage backend/coverage.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_RE = re.compile(r"(?:^|/)simremap/([A-Za-z_][A-Za-z0-9_]*)/")
DEFAULT_PACKAGES = (
    "core",
    "physics",
    "damage",
    "catalog",
    "dyno",
    "ecu",
    "profiles",
    "telemetry",
    "scenarios",
    "api",
    "db",
)


@dataclass
class PackageCoverage:
    name: str
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    files: int = 0
    non_init_files: int = 0

    @property
    def total(self) -> int:
        return self.statements + self.branches

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 100.0
        return 100.0 * (self.covered + self.covered_branches) / self.total

    @property
    def empty(self) -> bool:
        return self.non_init_files == 0 or self.statements == 0


def aggregate(report: dict[str, object]) -> dict[str, PackageCoverage]:
    files = report.get("files")
    if not isinstance(files, dict):
        raise ValueError("coverage.json sem a chave 'files'")
    result: dict[str, PackageCoverage] = {}
    for path, data in files.items():
        match = PACKAGE_RE.search(str(path).replace("\\", "/"))
        if match is None or not isinstance(data, dict):
            continue
        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            continue
        pkg = result.setdefault(match.group(1), PackageCoverage(match.group(1)))
        pkg.files += 1
        if not str(path).endswith("__init__.py"):
            pkg.non_init_files += 1
        pkg.statements += int(summary.get("num_statements", 0))
        pkg.covered += int(summary.get("covered_lines", 0))
        pkg.branches += int(summary.get("num_branches", 0))
        pkg.covered_branches += int(summary.get("covered_branches", 0))
    return result


def check(
    report: dict[str, object], packages: list[str], minimum: float
) -> tuple[list[str], list[str]]:
    """Devolve (linhas do relatório, pacotes abaixo do mínimo)."""
    data = aggregate(report)
    lines = [f"{'pacote':<12} {'cobertura':>9}  {'instr.':>6}  {'ramos':>6}  estado"]
    failures: list[str] = []
    for name in packages:
        pkg = data.get(name)
        if pkg is None or pkg.empty:
            lines.append(f"{name:<12} {'-':>9}  {'-':>6}  {'-':>6}  ignorado (vazio)")
            continue
        ok = pkg.percent >= minimum
        state = "ok" if ok else f"ABAIXO de {minimum:g} %"
        lines.append(
            f"{name:<12} {pkg.percent:>8.2f}%  {pkg.statements:>6}  {pkg.branches:>6}  {state}"
        )
        if not ok:
            failures.append(f"{name} ({pkg.percent:.2f} %)")
    return lines, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min", type=float, default=85.0, dest="minimum")
    parser.add_argument("--packages", nargs="+", default=list(DEFAULT_PACKAGES))
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    args = parser.parse_args(argv)
    if not args.coverage.is_file():
        print(
            f"coverage-per-package: {args.coverage} não existe (rode pytest --cov)",
            file=sys.stderr,
        )
        return 2
    report = json.loads(args.coverage.read_text(encoding="utf-8"))
    lines, failures = check(report, args.packages, args.minimum)
    print("\n".join(lines))
    if failures:
        print(f"coverage-per-package: FALHOU: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"coverage-per-package: ok (mínimo {args.minimum:g} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
