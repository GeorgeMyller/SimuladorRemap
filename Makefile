# SimuladorRemap — alvos locais (platform-foundation RF-19; roadmap D-03, D-26).
#   make check     portão de qualidade (≤ 5 min): lint, tipos, segurança, testes, cobertura, frontend
#   make bench     desempenho (física, ECU, laço, worker e event loop) — fora de check
#   make accuracy  desvio contra Reference Benchmark Baseline v1 — fora de check
#   make e2e       jornadas backend/tests/e2e + Playwright frontend/e2e — fora de check
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV       ?= uv
RUN      ?= $(UV) run --frozen
NPM      ?= npm
COV_MIN  ?= 85
PACKAGES ?= core physics damage catalog dyno ecu profiles telemetry scenarios career api db
COMPOSE  ?= docker compose
VERSION  ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)
IMAGE    ?= simremap:$(VERSION)
PLATFORMS ?= linux/amd64,linux/arm64
GIT_SHA  ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || true)
BUILD_TIME_UTC ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
# Saída 5 do pytest = nenhum teste selecionado (componente ainda sem testes desse tipo).
PYTEST_OPTIONAL = || { rc=$$?; if [ $$rc -eq 5 ]; then echo "(nenhum teste selecionado)"; else exit $$rc; fi; }

.PHONY: help install dev check lint type security test cov fe-lint fe-type fe-test \
        native bench accuracy e2e e2e-backend e2e-frontend e2e-local test-postgres api-types api-parity \
        build image-multiarch up down logs smoke compose-config clean

help: ## Lista os alvos
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install: ## Instala dependências com os lockfiles (uv sync --frozen, npm ci)
	cd backend && $(UV) sync --frozen
	$(NPM) --prefix frontend ci

dev: ## Backend com --reload (8000) + Vite (5173), sem Docker
	@mkdir -p backend/.data
	trap 'kill 0' INT TERM EXIT; \
	( cd backend && SIMREMAP_ENV=dev SIMREMAP_DATA_DIR=./.data SIMREMAP_STATIC_DIR=../frontend/dist \
	  SIMREMAP_LOG_LEVEL=DEBUG $(RUN) uvicorn simremap.api.main:app --reload --host 127.0.0.1 \
	  --port 8000 --no-access-log ) & \
	$(NPM) --prefix frontend run dev & \
	wait

# ------------------------------------------------------------------ portão de qualidade
check: lint type security test cov api-parity fe-lint fe-type fe-test ## Portão completo (mesma ordem de scripts/check.sh)
	@echo "make check: ok"

lint: ## ruff check + ruff format --check
	cd backend && $(RUN) ruff check . && $(RUN) ruff format --check .

type: ## mypy --strict (src e tests)
	cd backend && $(RUN) mypy --strict src tests

security: ## bandit (severidade ≥ média)
	cd backend && $(RUN) bandit -c pyproject.toml -r src -ll -q

test: ## pytest com cobertura (bench/accuracy/e2e/postgres ficam de fora)
	cd backend && $(RUN) pytest -q --cov=simremap --cov-report=json:coverage.json --cov-report=term

cov: ## Cobertura mínima por pacote simremap.<pacote>
	cd backend && $(RUN) python ../scripts/coverage_per_package.py --min $(COV_MIN) \
	  --coverage coverage.json --packages $(PACKAGES)

api-parity: ## Paridade OpenAPI × tipos orval de frontend/src/lib/api/generated (D-24; salta sem a geração)
	cd backend && $(RUN) pytest -q -rs tests/contract/test_openapi_orval_parity.py

fe-lint: ## eslint --max-warnings 0
	$(NPM) --prefix frontend run lint

fe-type: ## tsc --noEmit (app e e2e)
	cd frontend && $(NPM) exec -- tsc --noEmit -p .
	cd frontend && $(NPM) exec -- tsc --noEmit -p e2e

fe-test: ## vitest run
	cd frontend && $(NPM) exec -- vitest run

# ------------------------------------------------------------------ kernels nativos (003)
native: ## Compila e instala a extensão Rust simremap_rs no venv (maturin develop --release)
	cd backend && PATH="$$HOME/.cargo/bin:$$PATH" $(RUN) maturin develop --release \
	  -m rust/simremap_rs/Cargo.toml
	cd backend && $(RUN) python -c "import simremap_rs; print('simremap_rs', simremap_rs.__version__)"

# ------------------------------------------------------------------ fora de make check (D-26)
bench: ## Benchmarks (marcador bench): física, ECU, laço, worker process×thread, event loop
	cd backend && $(RUN) pytest -m bench -q -s $(PYTEST_OPTIONAL)

accuracy: ## Desvio < 5 % contra Reference Benchmark Baseline v1 (veículos validated)
	cd backend && $(RUN) pytest -m accuracy -q -s $(PYTEST_OPTIONAL)

e2e: e2e-backend e2e-frontend ## Jornadas ponta a ponta (backend + Playwright)

e2e-backend: ## Jornadas Lucas, Rodrigo e Prof. Marcos em backend/tests/e2e
	cd backend && $(RUN) pytest -m e2e tests/e2e -q $(PYTEST_OPTIONAL)

e2e-frontend: ## Playwright em frontend/e2e contra o container local (playwright.config.ts)
	cd frontend && $(NPM) exec -- playwright test

e2e-local: ## Playwright (Chromium) contra 2 estações locais sem Docker (scripts/e2e_local.sh)
	scripts/e2e_local.sh

test-postgres: ## Matriz de migrações em PostgreSQL 16 (perfil postgres do compose)
	$(COMPOSE) -f compose.yaml --profile postgres up -d --wait postgres
	cd backend && SIMREMAP_TEST_POSTGRES_URL=$${SIMREMAP_TEST_POSTGRES_URL:-postgresql+asyncpg://simremap:simremap@127.0.0.1:5432/simremap} \
	  $(RUN) pytest -m postgres tests/integration/test_migrations_postgres.py -q

api-types: ## Gera tipos/zod do frontend (orval) a partir do OpenAPI do backend
	cd backend && $(RUN) python ../scripts/export_openapi.py ../frontend/openapi.json
	rm -rf frontend/src/lib/api/generated  # sem modelos órfãos (paridade T172)
	SIMREMAP_OPENAPI=openapi.json $(NPM) --prefix frontend run api:generate

# ------------------------------------------------------------------ Docker (D-03)
build: ## Constrói a imagem $(IMAGE) (arquitetura local)
	$(COMPOSE) -f compose.yaml -f compose.prod.yaml build \
	  --build-arg GIT_SHA=$(GIT_SHA) --build-arg BUILD_TIME_UTC=$(BUILD_TIME_UTC)

image-multiarch: ## Imagem linux/amd64 + linux/arm64 (docker buildx)
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE) \
	  --build-arg GIT_SHA=$(GIT_SHA) --build-arg BUILD_TIME_UTC=$(BUILD_TIME_UTC) .

up: ## Sobe o container de produção local (127.0.0.1:8000)
	$(COMPOSE) -f compose.yaml -f compose.prod.yaml up -d

down: ## Para os containers
	$(COMPOSE) -f compose.yaml -f compose.prod.yaml down

logs: ## Logs JSON do container
	$(COMPOSE) -f compose.yaml -f compose.prod.yaml logs -f app

smoke: ## Teste de fumo do container (--network none, health ≤ 60 s, imagem ≤ 450 MB)
	IMAGE=$(IMAGE) scripts/smoke_container.sh

compose-config: ## Valida a sintaxe dos ficheiros compose
	$(COMPOSE) -f compose.yaml config -q
	$(COMPOSE) -f compose.yaml -f compose.dev.yaml config -q
	$(COMPOSE) -f compose.yaml -f compose.staging.yaml config -q
	$(COMPOSE) -f compose.yaml -f compose.prod.yaml config -q

clean: ## Remove caches e artefactos locais
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/coverage.json \
	  backend/.coverage backend/.bench frontend/dist frontend/playwright-report frontend/test-results
