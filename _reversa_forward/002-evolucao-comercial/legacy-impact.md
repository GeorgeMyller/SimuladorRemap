# Legacy Impact: 002-evolucao-comercial

> Data: 2026-10-19
> Feature: `002-evolucao-comercial`
> Âncora: greenfield (`_reversa_sdd/prd.md` + specs `_reversa_sdd/sdd/`), mais o adendo vigente `_reversa_sdd/addenda/001-simulador-remap.md`. Não há extração de legado (`architecture.md`/`domain.md`); o código tocado foi criado pela feature 001, por isso os tipos de impacto abaixo descrevem o delta sobre a 001, e não só `componente-novo`.
> Política de edição no momento da execução: `allowLegacyEdits: true`, `allowedPaths: []` (liberação irrestrita).
> Snapshot pré-execução: `.reversa/snapshots/pre-002-20261018-220258.tgz` (o projeto não é repositório git).

## Arquivos afetados

| Arquivo afetado | Componente | Tipo | Severidade | Justificativa |
|---|---|---|---|---|
| `backend/src/simremap/scenarios/catalog.py` | training-scenarios | regra-alterada | HIGH | Hash do builtin pela rota do clone; `resync_builtin_hash`; `BUILTIN_IDS` com 7 ids |
| `backend/src/simremap/scenarios/attempts.py` | training-scenarios | regra-alterada | HIGH | Autocura de hash em builtin `vehicle_stock`; não builtin mantém 422; lock de fecho por tentativa |
| `backend/src/simremap/scenarios/ports.py` | training-scenarios | regra-nova | MEDIUM | `factory_clone`, `clone_hash` |
| `backend/src/simremap/scenarios/contracts.py` | training-scenarios | regra-nova | MEDIUM | `DefectKind.boost_leak` (`leak_area_mm2` 5–200 mm², fora do hash quando vazio) |
| `backend/src/simremap/scenarios/builtin/defect-*.json` (4) | training-scenarios | componente-novo | MEDIUM | Cenários base com defeito oculto, calibrados na física real |
| `backend/src/simremap/ecu/errors.py`, `ecu/router.py` | ecu-core | regra-nova | HIGH | `CALIBRATION_STOCK_IMMUTABLE` (409) em PUT, revert e PATCH de `stock-*` |
| `backend/src/simremap/ecu/contracts.py`, `ecu/limits.py` | ecu-core | delta-de-contrato-externo | MEDIUM | `StrategyKind.VVT`, `VvtConfig`, `TableKind.FLEX_IGN_ADD/FLEX_BOOST_ADD`, eixo `ethanol_pct`, âncoras do flex |
| `backend/src/simremap/ecu/strategies/vvt.py`, `ecu/runtime.py` | ecu-core | regra-nova | MEDIUM | Estratégia `vvt` (ECT mínima, taxa, offsets); compensação flex (massa ×AFR_stock/AFR_blend, ×ρ_stock/ρ_blend; avanço e boost por tabela) |
| `backend/src/simremap/profiles/contracts.py`, `profiles/setup.py`, `profiles/descriptors/*` | ecu-profiles | regra-alterada | MEDIUM | Descritor exige 10 kinds; `vvt` suportado nos 4 perfis; tabelas de came na navegação e live-tunable |
| `backend/src/simremap/physics/fuel.py` | engine-physics-core | regra-nova | HIGH | `ValveOverlap`: `overlap = base + vvt_in − vvt_ex`, efeito relativo ao cronograma de série (zero na série) |
| `backend/src/simremap/physics/engine.py` | engine-physics-core | regra-alterada | HIGH | Atuador VVT de 1.ª ordem (`actuator_tau_s`, ≤ 150 °/s); escalas de contrapressão e bomba; sensor `ethanol_pct` |
| `backend/src/simremap/physics/fuel_blend.py`, `physics/cycle_solver.py`, `physics/contracts.py` | engine-physics-core | componente-novo | MEDIUM | `blend_fuel` E27–E100; cache do solver por chave do blend; `PhysicsConfig` com escalas; `SensorReadings.ethanol_pct` |
| `backend/src/simremap/catalog/upgrades.py`, `catalog/router.py`, `catalog/errors.py`, `catalog/contracts.py` | vehicle-catalog | componente-novo | MEDIUM | Peças, `apply_upgrades`, `GET /api/v1/upgrades`, `UPGRADE_NOT_COMPATIBLE`, `FuelId` com `flex` |
| `backend/src/simremap/damage/config.py`, `damage/model.py` | knock-and-failure-model | regra-alterada | LOW | Limiar de pré-ignição para o flex |
| `backend/src/simremap/dyno/contracts.py`, `dyno/session.py`, `dyno/assembly.py`, `dyno/repository.py`, `dyno/sampler.py` | dyno-bench | delta-de-contrato-externo | HIGH | `upgrades`, `ethanol_pct`; clone da stock por sessão; fecho idempotente da sessão; fuel flex grava a âncora mais próxima em `fuel_id` |
| `backend/src/simremap/telemetry/channels.py`, `telemetry/sampler.py` | telemetry-datalogger | delta-de-contrato-externo | LOW | Canais `cam_*` e `ethanol_pct` |
| `backend/src/simremap/career/*`, `db/models/career.py`, `db/migrations/versions/0008_career.py`, `db/models/__init__.py`, `api/registry.py` | career (novo) | componente-novo | MEDIUM | Perfil, 7 ordens, aceitar/liquidar; migração `0008_career`; router atrás de `SIMREMAP_FEATURE_SCENARIOS` |
| `Makefile` | platform-foundation | regra-alterada | LOW | `career` em `PACKAGES` da cobertura |
| `frontend/src/features/ecu-tuning/*` (ops/quickTune, TableEditorCore, TableToolbar, ShortcutsDialog, workspaceStore, useWorkspaceStore, StockCalibrationBanner, telemetryFeed, OperationCursor, api, model, messages, EcuWorkspace) | ecu-tuning-ui | regra-nova | MEDIUM | Quick Tune `Q`; `H`/`V`/`B`; `stock-*` somente leitura com "Clonar e editar" |
| `frontend/src/features/dyno-cockpit/live-tuning/*`, `DynoCockpitPage.tsx`, `channels.ts`, `useCockpit.ts` | dyno-cockpit-ui | regra-nova | MEDIUM | Tela dividida (tecla `L`), Live Cell Tracing, aplicação automática, `extraChannels` |
| `frontend/src/features/dyno-cockpit/render/*`, `CarOnRollerView.tsx`, `thermalView.ts`, `keyboardTargets.ts`, `pixel-cars/sprites.ts` | dyno-cockpit-ui | regra-nova | MEDIUM | Visão térmica/raio-X (tecla `T`), partículas por modo de falha, chamas maiores |
| `frontend/src/features/dyno-cockpit/audio/*` | dyno-cockpit-ui | regra-alterada | LOW | Arquétipos de áudio por arquitetura, assobio do compressor do V8 |
| `frontend/src/features/dyno-cockpit/useHoldThrottle.ts`, `RunControls.tsx`, `messages.ts`, `ShortcutsDialog.tsx` | dyno-cockpit-ui | regra-nova | LOW | Pedal com mola no Espaço |
| `frontend/src/features/workshop/*`, `frontend/src/app/HomePage.tsx`, `app/homeApi.ts`, `app/test-fixtures.ts` | dyno-cockpit-ui (criação de sessão) | componente-novo | MEDIUM | Stage Builder e controle de etanol |
| `frontend/src/features/career/*`, `app/routes.tsx`, `app/paths.ts`, `app/App.tsx` | career (novo) | componente-novo | MEDIUM | Página "Oficina (Carreira)" e rota `/workshop` |
| `frontend/vite.config.ts` | platform-foundation | regra-alterada | LOW | `codeSplitting.groups` (rolldown); todas as páginas lazy exceto NotFound |
| `frontend/openapi.json`, `frontend/src/lib/api/generated/` | platform-foundation | delta-de-contrato-externo | LOW | Cliente orval regenerado (44 caminhos) |

## Diff conceitual por componente

- **training-scenarios:** o hash da calibração inicial deixa de ser copiado da v1 gravada e passa a ser recalculado pela mesma rota do clone. Cenários builtin se autocuram; cenários importados continuam estritos. O catálogo builtin passa de 3 para 7 cenários base.
- **ecu-core:** calibrações `stock-*` ficam somente leitura pela API. A ECU ganha a estratégia `vvt` e lê o sensor de etanol.
- **ecu-profiles:** os 4 perfis declaram 10 estratégias.
- **engine-physics-core:** o VVT afeta a VE e a fração residual pelo cruzamento de válvulas, com efeito nulo no cronograma de série. A física aceita um combustível misturado e escalas de contrapressão e de bomba.
- **vehicle-catalog:** um pacote de upgrades transforma o veículo imutável numa cópia modificada antes da sessão.
- **dyno-bench:** a sessão sem `calibration_id` nasce com um clone da stock. O fecho da sessão é idempotente.
- **career:** componente novo sobre o `AttemptService`.
- **dyno-cockpit-ui / ecu-tuning-ui:** calibração ao vivo na bancada, atalhos de tabela, imersão visual e sonora, pedal progressivo.

## Preservadas

Feature com âncora greenfield: não há regras 🟢 extraídas. Os testes de precisão (`-m accuracy`, desvio < 5 % nos 4 veículos), os 2128 testes do backend e os 571 do frontend continuam aprovados.

## Modificadas

Sem regras 🟢 de legado. Comportamentos da 001 alterados de propósito:
- Sessão sem `calibration_id` aponta para um clone do usuário, e não mais para `stock-*`.
- `EcuProfileDescriptor` exige 10 kinds (antes 9).
- `BUILTIN_IDS` com 7 cenários (antes 3); taxa de conclusão passa a contar os 4 cenários de defeito.
- Áudio e animação da bancada diferentes por arquitetura.
