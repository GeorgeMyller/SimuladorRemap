# Legacy Impact: Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador: `001-simulador-remap`
> Data: `2026-10-18`
> Cenário: **greenfield**. Feature greenfield, sem legado pré-existente. Âncora: prd.md + specs SDD.
> Política de edição no momento da execução: `allowLegacyEdits: true`, `allowedPaths: []` (liberação irrestrita; a escrita ficou restrita, por disciplina, a `backend/`, `frontend/`, `scripts/`, `Dockerfile`, `compose*.yaml`, `Makefile`, `.dockerignore`).
> Nenhum arquivo pré-existente do projeto foi modificado ou apagado (o projeto tinha só `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `temp/` e as pastas do Reversa/stack VLM).

## Arquivos afetados

| Arquivo afetado | Componente | Tipo | Severidade | Justificativa |
|---|---|---|---|---|
| `.dockerignore` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `Dockerfile` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `Makefile` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/.bench/rss.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/.bench/worker_modes.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/.python-version` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/alembic.ini` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/coverage.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/pyproject.toml` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/deps.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/health.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/main.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/middleware.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/problems.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/py.typed` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/registry.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/serve.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/api/static.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/catalog/__init__.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/__main__.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/accuracy.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/canonical.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/compare.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/contracts.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/fuels/e0.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/fuels/e100.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/fuels/e27.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/fuels/podium.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/manifest.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/classic-20t-swap/calibrations/ft-pro.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/classic-20t-swap/calibrations/oem-stage.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/classic-20t-swap/reference-curves/stock-e100.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/classic-20t-swap/vehicle.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/coupe-30t-i6/calibrations/oem-stage.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/coupe-30t-i6/reference-curves/stock-e27.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/coupe-30t-i6/vehicle.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/hatch-20t-gdi/calibrations/oem-stage.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/hatch-20t-gdi/reference-curves/stock-e27.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/hatch-20t-gdi/vehicle.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/muscle-v8-sc/calibrations/oem-stage.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/muscle-v8-sc/reference-curves/stock-e27.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/data/vehicles/muscle-v8-sc/vehicle.json` | `vehicle-catalog` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/drivetrain.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/errors.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/grids.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/loader.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/provenance.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/py.typed` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/router.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/service.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/settings.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/tools/__init__.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/tools/gen_data.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/tools/gen_ve.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/tools/jsonfmt.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/tools/rehash.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/catalog/trademarks.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/core/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/cache.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/config.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/contracts.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/errors.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/logging.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/py.typed` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/request_context.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/versions.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/host.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/logbridge.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/loop.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/physics_task.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/protocol.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/queues.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/synthetic.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/core/worker/thread_backend.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/damage/__init__.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/config.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/contracts.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/digest.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/errors.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/failure.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/__init__.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/chain.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/recommend.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/report.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/texts/__init__.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/texts/pt-BR/beginner.json` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/texts/pt-BR/instructor.json` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/texts/pt-BR/intermediate.json` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/texts/pt-BR/phrases.json` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/view.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/forensic/warnings.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/knock.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/mechanical.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/model.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/preignition.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/py.typed` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/router.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/service.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/session_port.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/signal.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/spectrum.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/thermal.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/damage/trace.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/db/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/base.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/engine.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrate.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrations/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrations/env.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrations/script.py.mako` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrations/versions/0001_foundation_base.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/migrations/versions/0002_dyno_sessions_runs.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/db/migrations/versions/0003_damage_health_reports.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/db/migrations/versions/0004_ecu_calibrations.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/db/migrations/versions/0005_profiles_session_state.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/db/migrations/versions/0006_telemetry_datalog.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/db/migrations/versions/0007_scenarios_base.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/db/models/__init__.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/models/_columns.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/models/calibration.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/db/models/damage.py` | `knock-and-failure-model` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/src/simremap/db/models/datalog.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/db/models/dyno.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/db/models/foundation.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/models/profiles.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/db/models/scenarios.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/db/py.typed` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/db/seeds.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/dyno/__init__.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/assembly.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/contracts.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/controllers.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/correction.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/curve.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/errors.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/guards.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/output_router.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/ports.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/py.typed` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/repository.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/rig.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/router.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/runner.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/runs.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/sampler.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/session.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/stream.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/dyno/trace_codec.py` | `dyno-bench` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/src/simremap/ecu/__init__.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/apply.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/arbitration.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/calibration.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/compiled.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/contracts.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/errors.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/hooks.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/limits.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/ports.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/py.typed` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/repository.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/router.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/runtime.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/seed_stock.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/service.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/session_port.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/__init__.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/antilag.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/base.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/boost.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/closed_loop.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/failsafe.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/fuel.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/ignition.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/overrun.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/powershift.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/rev_limiter.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/strategies/two_step.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/ecu/tables.py` | `ecu-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/src/simremap/physics/__init__.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/combustion.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/config.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/contracts.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/cycle_solver.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/digest.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/engine.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/errors.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/exhaust.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/faults.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/friction.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/fuel.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/geometry.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/interp.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/manifold.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/py.typed` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/reference.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/sensors.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/supercharger.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/thermal.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/physics/turbo.py` | `engine-physics-core` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/src/simremap/profiles/__init__.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/adapter.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/compliance.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/contracts.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/__init__.py` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/hardware/__init__.py` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/hardware/classic-20t-swap.json` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/hardware/coupe-30t-i6.json` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/hardware/hatch-20t-gdi.json` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/data/hardware/muscle-v8-sc.json` | `ecu-profiles` | componente-novo | LOW | Dado criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/__init__.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/common.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/ft_pro.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/ht_elite.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/m1_race.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/descriptors/oem_stage.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/errors.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/hardware.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/hooks/common.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/hooks/oem_stage.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/hooks/standalone.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/py.typed` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/registry.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/repository.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/router.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/service.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/session_port.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/setup.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/swap.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/wizard.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/profiles/worker.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/py.typed` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/src/simremap/scenarios/__init__.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/attempts.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/builtin/examples/challenge-400whp-e27.json` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/builtin/stage1-oem.json` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/builtin/stage2-pops-bangs.json` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/builtin/standalone-swap.json` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/catalog.py` | `vehicle-catalog` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/src/simremap/scenarios/contracts.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/errors.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/evaluator.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/events.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/hints.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/jcs.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/packages.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/ports.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/probe.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/profiles.py` | `ecu-profiles` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/src/simremap/scenarios/py.typed` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/replay.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/repository.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/router.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/trace.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/scenarios/validity.py` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/src/simremap/telemetry/__init__.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/broadcaster.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/channels.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/compare.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/contracts.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/datalog.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/decimator.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/errors.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/export.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/logbook.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/py.typed` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/repository.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/router.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/sampler.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/service.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/spectrum.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/src/simremap/telemetry/ws.py` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/api/test_app.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/api/test_health.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/api/test_middleware.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/api/test_registry.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/api/test_serve.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/catalog/accuracy/test_accuracy_reference.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/conftest.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_api.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_compare.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_contracts.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_drivetrain.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_ecu_validator.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_factory_calibrations.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_grids_provenance.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_invariants.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_loader.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_prd_values.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_reference_curves.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_service.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_tools.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/catalog/test_trademarks.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/conftest.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_coverage_per_package.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_determinism_imports.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/contract/test_error_catalog.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/contract/test_no_pii.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_openapi.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_openapi_orval_parity.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_problem_detail.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_strategy_zod_parity.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_trademark_blocklist.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/contract/test_versions.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/bench/test_bench_rss.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/bench/test_bench_worker_modes.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_cache.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_config_minimal.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_contracts.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_errors.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_logging.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_physics_task.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/core/test_settings.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_worker_host.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/core/test_worker_queues.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/damage/conftest.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/kfm_helpers.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_api.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_contracts.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_damage_mechanical.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_damage_thermal.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_determinism.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_failure_modes.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_forensic.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_knock.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_preignition.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/damage/test_signal_spectrum.py` | `knock-and-failure-model` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/knock-and-failure-model.md` |
| `backend/tests/db/test_engine.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/db/test_migrate_backup.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/db/test_migrations.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/db/test_models_foundation.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/db/test_seeds.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/db/test_session_dependency.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/dyno/bench/test_bench_loop.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/conftest.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/data/hatch_stock_tuned.json` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/dyno_helpers.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_acceptance_catalog.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/dyno/test_api.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_contracts.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_controllers.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_correction.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_curve.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_determinism.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_ports.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_pull_types.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_rig.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_run_state_machine.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_runner_commands.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_session_manager.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_stream_sampler_codec.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/dyno/test_tick_order.py` | `dyno-bench` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-bench.md` |
| `backend/tests/e2e/conftest.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/e2e/e2e_support.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/e2e/test_determinism_20x.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/e2e/test_journey_lucas.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/e2e/test_journey_marcos.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/ecu/bench/test_bench_ecu_step.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/conftest.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_api.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_apply.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_arbitration.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_boost.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_calibration.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_contracts.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_failsafe.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_fuel.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_ignition_knock.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_runtime.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_seed_stock.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_strategies.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/ecu/test_tables.py` | `ecu-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-core.md` |
| `backend/tests/fixtures/digests/arm64.json` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/conftest.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/test_import_50_packages.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/test_journey_lucas.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/integration/test_journey_rodrigo.py` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `backend/tests/integration/test_migrations_postgres.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/test_sprint2_failure_flow.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/test_stage1_real_attempt.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/integration/test_stock_seed.py` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `backend/tests/physics/bench/test_bench_step.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/conftest.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_combustion.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_config_geometry.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_contracts.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_cycle_solver.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_determinism.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_exhaust.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_faults.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_friction_dynamics.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_fuel_air.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_lock.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_manifold.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_reference_curves.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_sensors_property.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_supercharger.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_thermal.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/physics/test_turbo.py` | `engine-physics-core` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/engine-physics-core.md` |
| `backend/tests/profiles/bench/test_bench_profiled_ecu.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/conftest.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_api.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_contracts.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_hardware_repository.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_oem_protection.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_oem_torque_path.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_protections_overrides.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_registry.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_standalone_profiles.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_swap_setup.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_symptoms.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/profiles/test_wizard.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/scenarios/conftest.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/scn_env.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/scn_helpers.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_api.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_attempts.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_catalog.py` | `vehicle-catalog` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/vehicle-catalog.md` |
| `backend/tests/scenarios/test_challenges.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_contracts.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_evaluator.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_hints_stats.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_packages.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_player_profiles.py` | `ecu-profiles` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-profiles.md` |
| `backend/tests/scenarios/test_probe.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_replay.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/scenarios/test_validity.py` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `backend/tests/telemetry/bench/test_bench_sampler.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/conftest.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/tel_helpers.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_backpressure.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_channels.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_contracts.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_datalog.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_decimator.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_events.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_export_import_compare.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_logbook.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_resume.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_seq.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_spectrum_trace.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/test_ws_protocol.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/tests/telemetry/ws_helpers.py` | `telemetry-datalogger` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `backend/uv.lock` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `compose.dev.yaml` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `compose.prod.yaml` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `compose.staging.yaml` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `compose.yaml` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/.gitignore` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/e2e/a11y.spec.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/cockpit-fps.spec.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/e2e/helpers.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/journey-lucas.spec.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/journey-marcos.spec.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/journey-rodrigo.spec.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/smoke.spec.ts` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/e2e/tsconfig.json` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/eslint.config.js` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/index.html` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/openapi.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/orval.config.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/package-lock.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/package.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/playwright.config.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/App.test.tsx` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/App.tsx` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/HomePage.test.tsx` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/HomePage.tsx` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/NotFoundPage.tsx` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/a11y.test.tsx` | `transversal (E2E)` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `frontend/src/app/activeSession.test.tsx` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/activeSession.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/flags.test.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/flags.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/homeApi.test.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/homeApi.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/paths.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/routes.tsx` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/test-fixtures.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/app/useAppVersion.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/features/dyno-cockpit/AttemptSidebar.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/AudioControls.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/CarOnRollerView.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/CarOnRollerView.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/ConnectionIndicator.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/CylinderPressureTrace.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DataloggerPanel.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DataloggerPanel.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DiagnosticsPanel.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/Dialog.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DynoChart.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DynoCockpitPage.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/DynoCockpitPage.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/EngineAutopsyView.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/EngineAutopsyView.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/EventTimeline.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/EventTimeline.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/GaugeCluster.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/GaugeCluster.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/KnockSpectrogram.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/KnockSpectrogram.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/LambdaEgtChart.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/RunControls.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/RunControls.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/ShortcutsDialog.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/UnitsMenu.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/a11y.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/api.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/audio/AudioEngine.test.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/audio/AudioEngine.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/audio/EngineSynth.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/channels.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/charts.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/charts/UPlotChart.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/cockpitState.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/flashGuard.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/messages.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/prefs.test.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/prefs.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/CarAnimator.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/RenderLoop.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/RingBuffer.test.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/RingBuffer.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/SpectrogramModel.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/createSurface.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/render/spectrogramRenderers.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/store.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/test-utils/harness.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/test-utils/mocks.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/test-utils/uplotMock.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/dyno-cockpit/useCockpit.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/features/ecu-tuning/BaseSetupWizard.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/BaseSetupWizard.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/CalibrationVersions.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/CalibrationVersions.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/CylinderTrims.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/EcuWorkspace.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/EcuWorkspace.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/EcuWorkspacePage.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/LiveTuneIndicator.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/LiveTuneIndicator.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/OperationCursor.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/OperationCursor.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ProfileNavigator.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ProfileNavigator.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ShortcutsDialog.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/StrategyForms.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/StrategyForms.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/SwapSelector.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/Table3DGeometry.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/Table3DSurface.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/Table3DView.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/Table3DView.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableEditor.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableEditor2D.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableEditor3D.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableEditorCore.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableGrid.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableToolbar.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TableToolbar.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TuningWarnings.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/TuningWarnings.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/VehicleSelector.test.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/VehicleSelector.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/api.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/api.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/baseSetupSchemas.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/fixtures/strategy-parity.json` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/heatmap.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/history/UndoStack.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/history/UndoStack.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/messages.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/model.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/diffCalibrations.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/edgeCases.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/interpolate.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/ops.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/selectionOps.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/ops/tsv.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/prefs.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/prefs.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/strategySchemas.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/telemetryFeed.ts` | `telemetry-datalogger` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/telemetry-datalogger.md` |
| `frontend/src/features/ecu-tuning/test-utils/fixtures.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/test-utils/harness.tsx` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/types.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/usePatchQueue.test.ts` | `ecu-tuning-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/usePatchQueue.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/warnings.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/ecu-tuning/workspaceStore.ts` | `ecu-tuning-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/ecu-tuning-ui.md` |
| `frontend/src/features/scenarios/AttemptProgressPanel.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ChallengeForm.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ChallengeForm.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ClassGradeTable.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ClassGradeTable.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/EvaluationResult.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/EvaluationResult.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/EvidenceLink.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/HintPanel.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/InstructorPanel.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/PackageImportQueue.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/PackageImportQueue.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ProfileCreateDialog.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ProfilePicker.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ProfilePicker.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ScenarioBriefing.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ScenarioList.test.tsx` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ScenarioList.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ScenariosPage.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/api.test.ts` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/api.ts` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/gradesCsv.test.ts` | `training-scenarios` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/gradesCsv.ts` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/test-utils/fixtures.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/types.ts` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/ui.tsx` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/useActiveProfile.ts` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/features/scenarios/useAttempt.ts` | `training-scenarios` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/training-scenarios.md` |
| `frontend/src/index.css` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/client.test.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/client.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/index.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/mutator.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/problem.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/units/UnitsContext.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/units/index.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/units/units.test.tsx` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/units/units.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/ws/TelemetrySocket.test.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/ws/TelemetrySocket.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/ws/envelope.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/lib/ws/index.ts` | `dyno-cockpit-ui` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/dyno-cockpit-ui.md` |
| `frontend/src/main.tsx` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/axe.test.tsx` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/axe.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/audio.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/browser.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/canvas.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/index.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/mocks.test.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/mocks/websocket.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/test/setup.ts` | `platform-foundation` | componente-novo | LOW | Teste criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/tsconfig.json` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/vite.config.ts` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `scripts/check.sh` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `scripts/coverage_per_package.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `scripts/e2e_local.sh` | `transversal (E2E)` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/prd.md` |
| `scripts/export_openapi.py` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `scripts/smoke_container.sh` | `platform-foundation` | componente-novo | LOW | Código criado pela feature 001 (sem legado pré-existente); spec `_reversa_sdd/sdd/platform-foundation.md` |
| `frontend/src/lib/api/generated/` (342 arquivos) | `dyno-cockpit-ui` / todos | componente-novo | LOW | Cliente REST + schemas zod gerados por orval a partir do OpenAPI (T433/T443, D-24); regenerar com `make api-types` |

Total: 651 arquivos criados (sem contar `node_modules/`, `.venv/`, caches, `dist/`, `coverage/`) + 342 arquivos gerados em `frontend/src/lib/api/generated/`.

## Diff conceitual por componente

### `platform-foundation`

🟡 Monorepo `backend/` + `frontend/`, app FastAPI (`create_app`, lifespan cache → catálogo → worker → routers), erros RFC 9457 com catálogo único, `Settings` `SIMREMAP_`, SQLAlchemy async + Alembic (cadeia 0001–0007), `SimWorkerHost` (process padrão por benchmark, thread), filas com faixa crítica sem descarte, Docker multi-stage + compose dev/staging/prod, Makefile e portões de qualidade. Arquivos: 139 (87 código, 52 teste).

### `engine-physics-core`

🟡 Motor 0D/1D ciclo Otto a 100–1000 Hz determinístico: coletor filling & emptying, VE física, combustível com dead time e wall-wetting, Wiebe, ciclo de zona única com Woschni, Chen-Flynn, EGT, turbo com inércia do eixo e mapas, supercharger, intercooler, sensores com ruído semeado (`knock_sensor_v` 0–5 V + `knock_intensity` 0–1), `PhysicsFault` (incl. `wastegate_stuck`), cache de ciclos e digest. Arquivos: 40 (21 código, 19 teste).

### `vehicle-catalog`

🟡 4 veículos validados (hatch 2.0 TSI, coupé 3.0 I6 turbo, clássico 2.0 turbo para swap, V8 supercharged) gerados por `catalog/tools/`, combustíveis, calibrações de série `oem-stage` e mapa base `ft-pro`, manifest SHA-256, `Reference Benchmark Baseline v1` com desvio < 5 % nos 4 veículos, API `/api/v1/vehicles`. Arquivos: 59 (22 código, 18 dado, 19 teste).

### `dyno-bench`

🟡 Dinamômetro virtual (rolo inercial + Foucault), baseline/sweep/steady-state/multi-pull, correção SAE J1349/DIN 70020, máquina de estados da puxada, abortos, sessões e runs persistidos, `DynoSimTask` no worker, portas para ECU/dano/perfis, `StreamHub`, ouvinte `add_calibration_listener`. Arquivos: 40 (22 código, 18 teste).

### `knock-and-failure-model`

🟡 Livengood-Wu/Douaud-Eyzat, classes de knock, pré-ignição e LSPI, dano por knock/térmico/biela/válvulas/turbina/junta/bronzinas, 6 modos de falha, bloqueio do motor, laudo forense com cadeia causal e regras didáticas, `DamageConfig` 1.2.0 calibrado com a física. Arquivos: 43 (31 código, 12 teste).

### `ecu-core`

🟡 Runtime genérico de ECU (tabelas 2D/3D, speed-density, lambda alvo, malha fechada, compensações, ignição por cilindro, knock control, boost PID por marcha, limitador, two-step, antilag, powershift, overrun/pops & bangs, failsafe, arbitragem), calibrações versionadas com `base_version` e API `/api/v1/calibrations`. Arquivos: 47 (32 código, 15 teste).

### `ecu-profiles`

🟡 Perfis OEM-Stage (caminho de torque, flags e checksum OEM, marcha lenta), FT-Pro, M1-Race e HT-Elite; `BaseSetup`, wizard de mapa base, `ProfiledEcu` com hardware declarado vs. real (sintomas S-01..S-10), swap OEM → standalone e guarda `ECU_SETUP_INCOMPLETE`. Arquivos: 48 (28 código, 6 dado, 14 teste).

### `telemetry-datalogger`

🟡 WebSocket `/ws/v1/sessions/{id}/telemetry` (envelope v1, `seq` + 1 em todo envelope, decimação 30–60 FPS, agregação, backpressure, replay/resume), datalogger por puxada, export JSON/CSV, import com SHA-256, comparação antes vs. depois, espectro de knock. Arquivos: 36 (20 código, 16 teste).

### `dyno-cockpit-ui`

🟡 Bancada no navegador: cliente WS tipado, gráficos uPlot antes vs. depois, gauges, espectrograma, traço de pressão, animação Canvas do carro no rolo (fogo em pops & bangs, explosão em falha), áudio procedural Web Audio, autópsia forense, datalogger, tela inicial e rotas. Arquivos: 60 (17 teste, 43 código).

### `ecu-tuning-ui`

🟡 Software de ECU no navegador por perfil: editor de tabelas 2D/3D até 32×32 com heatmap, operações, TSV, undo/redo e cursor ao vivo, superfície three.js lazy, formulários de estratégias com paridade zod × Pydantic, wizard de swap, versões e avisos didáticos. Arquivos: 58 (18 teste, 40 código).

### `training-scenarios`

🟡 Perfis locais sem PII, cenários base `stage1-oem`, `stage2-pops-bangs`, `standalone-swap` e desafio do instrutor, defeitos ocultos, avaliação determinística, pacotes assinados JCS + SHA-256, painel do instrutor com CSV de notas, UI `features/scenarios`. Arquivos: 64 (43 código, 21 teste).

### `transversal (E2E)`

🟡 E2E das jornadas Lucas, Rodrigo e Prof. Marcos (backend e Playwright), determinismo 20× com digests, axe com 0 violações A/AA, benchmark de FPS da cockpit. Arquivos: 17 (16 teste, 1 código).

## Preservadas

Feature greenfield: não há regras 🟢 extraídas de código pré-existente em `_reversa_sdd/domain.md` para preservar.

## Modificadas

Feature greenfield: nenhuma regra 🟢 alterada ou removida.
