#!/usr/bin/env bash
# Portão de qualidade local (platform-foundation RF-19; equivalente a `make check`).
# Ordem: ruff check, ruff format --check, mypy --strict, bandit, pytest com cobertura,
# cobertura por pacote (≥ 85 %), eslint, tsc --noEmit, vitest run. Para no primeiro erro.
#
# Variáveis:
#   RUN       prefixo dos comandos do backend (padrão: "uv run --frozen")
#   NPM       binário do npm (padrão: npm)
#   COV_MIN   cobertura mínima por pacote (padrão: 85)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${RUN:-uv run --frozen}"
NPM="${NPM:-npm}"
COV_MIN="${COV_MIN:-85}"
PACKAGES="core physics damage catalog dyno ecu profiles telemetry scenarios api db"

step() { printf '\n==> %s\n' "$1"; }

cd "$ROOT/backend"
step "ruff check";            $RUN ruff check .
step "ruff format --check";   $RUN ruff format --check .
step "mypy --strict";         $RUN mypy --strict src tests
step "bandit";                $RUN bandit -c pyproject.toml -r src -ll -q
step "pytest + cobertura";    $RUN pytest -q --cov=simremap --cov-report=json:coverage.json --cov-report=term
step "coverage-per-package";  $RUN python ../scripts/coverage_per_package.py --min "$COV_MIN" \
                                --coverage coverage.json --packages $PACKAGES
step "paridade orval";        $RUN pytest -q -rs tests/contract/test_openapi_orval_parity.py
cd "$ROOT"
step "eslint";                "$NPM" --prefix frontend run lint
step "tsc --noEmit";          "$NPM" --prefix frontend exec -- tsc --noEmit -p .
step "vitest run";            "$NPM" --prefix frontend exec -- vitest run
printf '\n==> make check: ok\n'
