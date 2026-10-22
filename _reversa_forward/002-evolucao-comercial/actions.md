# Actions: Evolução Comercial — Live Tuning, Oficina de Upgrades, Imersão, Carreira e Blindagem de Cenários

> Identificador: `002-evolucao-comercial`
> Data: `2026-10-18`
> Roadmap: `_reversa_forward/002-evolucao-comercial/roadmap.md`

Trilhas de execução (arquivos disjuntos, usadas pelo `/reversa-coding` para paralelizar):
- **A** blindagem de cenários e calibrações (backend `scenarios/attempts.py`, `scenarios/catalog.py`, `scenarios/ports.py`, `ecu/router.py`)
- **B** física, ECU, upgrades e flex (backend `physics/`, `ecu/` exceto router, `profiles/`, `telemetry/`, `catalog/upgrades.py`, `dyno/`)
- **C** cenários de defeito e carreira (backend `scenarios/contracts.py`, `scenarios/builtin/`, `career/`, migração `0008`) — depois de A
- **D** Live Tuning e atalhos do editor (frontend `ecu-tuning/`, `dyno-cockpit/DynoCockpitPage.tsx`, `dyno-cockpit/live-tuning/`)
- **E** imersão (frontend `dyno-cockpit/audio/`, `render/`, `CarOnRollerView.tsx`, `RunControls.tsx`, `channels.ts`, `useCockpit.ts`)
- **F** UI de oficina, flex e carreira, cliente da API e code-splitting (frontend `app/`, `features/career/`, `features/workshop/`, `vite.config.ts`, `lib/api/generated/`) — depois de B e C

## Resumo

| Métrica | Valor |
|---------|-------|
| Total de ações | 62 |
| Paralelizáveis (`[//]`) | 38 |
| Maior cadeia de dependência | 6 (T020 → T021 → T024 → T046 → T055 → T060) |

## Fase 1, Preparação

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T001 | [A] Registrar o erro `CALIBRATION_STOCK_IMMUTABLE` (409) no catálogo de erros da ECU | - | `[//]` | `backend/src/simremap/ecu/errors.py` | 🟡 | `[X]` |
| T002 | [B] Adicionar `StrategyKind.VVT`, `VvtConfig`, `TableKind.FLEX_IGN_ADD`/`FLEX_BOOST_ADD`, `AxisQuantity.ETHANOL_PCT` e limites das tabelas novas | - | `[//]` | `backend/src/simremap/ecu/contracts.py`, `ecu/limits.py` | 🟡 | `[X]` |
| T003 | [B] Adicionar `exhaust_backpressure_scale` e `fuel_pump_capacity_scale` em `PhysicsConfig` e `ethanol_pct` em `SensorReadings`; `FuelId` ganha `flex` | - | `[//]` | `backend/src/simremap/physics/contracts.py`, `catalog/contracts.py` | 🟡 | `[X]` |
| T004 | [C] Migração Alembic `0008_career` e modelos SQLModel `career_profiles`/`career_jobs` | - | `[//]` | `backend/src/simremap/db/migrations/versions/0008_career.py` | 🟡 | `[X]` |
| T005 | [F] Snapshot do build atual (tamanhos de chunk) para comparação | - | `[//]` | `frontend/dist/` (leitura) | 🟢 | `[X]` |

## Fase 2, Testes

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T006 | [A] Teste: stock v1 alterada no banco e `stage1-oem` inicia com 201 e hashes iguais (porta real) | T001 | `[//]` | `backend/tests/integration/test_builtin_hash_resync.py` | 🟡 | `[X]` |
| T007 | [A] Teste de API: PUT/revert/PATCH em `stock-*` → 409 `CALIBRATION_STOCK_IMMUTABLE` | T001 | `[//]` | `backend/tests/ecu/test_stock_immutable.py` | 🟡 | `[X]` |
| T008 | [B] Testes do overlap de VVT (baixa rotação reduz VE, alta rotação com MAP > contrapressão aumenta) | T003 | `[//]` | `backend/tests/physics/test_vvt_overlap.py` | 🟡 | `[X]` |
| T009 | [B] Testes de `blend_fuel` (AFR, PCI, RON monotônicos entre E27 e E100; limites 27–100) | T003 | `[//]` | `backend/tests/physics/test_fuel_blend.py` | 🟡 | `[X]` |
| T010 | [B] Testes de `apply_upgrades` (cada peça, incompatibilidade, validadores do veículo) | T003 | `[//]` | `backend/tests/catalog/test_upgrades.py` | 🟡 | `[X]` |
| T011 | [D] Testes das operações `quickTune`, `interpolateH`, `interpolateV`, `blockSmooth` | - | `[//]` | `frontend/src/features/ecu-tuning/ops/quickTune.test.ts` | 🟡 | `[X]` |
| T012 | [E] Testes de `thermalColor`, `useHoldThrottle` e presets de áudio por arquitetura | - | `[//]` | `frontend/src/features/dyno-cockpit/render/thermal.test.ts` | 🟡 | `[X]` |

## Fase 3, Núcleo

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T013 | [A] `load_builtin` calcula o hash do cenário pela rota do clone (`compute_content_hash(parse_content(stock.content))`) | T006 | - | `backend/src/simremap/scenarios/catalog.py` | 🟡 | `[X]` |
| T014 | [A] `ScenarioCatalog.resync_builtin_hash(scenario_id, new_hash)` recalcula `scenario_sha256` e faz `upsert_builtin` | T013 | - | `backend/src/simremap/scenarios/catalog.py` | 🟡 | `[X]` |
| T015 | [A] `AttemptService.start`: autocura em builtin com `vehicle_stock` (recria do payload de fábrica e, se preciso, ressincroniza); não builtin mantém 422 | T014 | - | `backend/src/simremap/scenarios/attempts.py` | 🟡 | `[X]` |
| T016 | [A] `EcuCalibrationPort`: método `factory_clone` a partir do payload do catálogo | T013 | `[//]` | `backend/src/simremap/scenarios/ports.py` | 🟡 | `[X]` |
| T017 | [A] Recusar PUT, revert e PATCH de tabela em `stock-*` nas rotas | T001, T007 | - | `backend/src/simremap/ecu/router.py` | 🟡 | `[X]` |
| T018 | [B] `DynoService._create` sem `calibration_id` clona a stock numa calibração do usuário | T017 | - | `backend/src/simremap/dyno/session.py` | 🟡 | `[X]` |
| T019 | [B] Overlap de VVT em `TrueVolumetricEfficiency` e fração residual; usar `VvtSpec.actuator_tau_s` no atuador | T008 | - | `backend/src/simremap/physics/fuel.py`, `physics/engine.py` | 🟡 | `[X]` |
| T020 | [B] Estratégia `VvtControl` (ECT mínima, taxa máxima, offsets) e ligação no `EcuRuntime` | T002 | - | `backend/src/simremap/ecu/strategies/vvt.py`, `ecu/runtime.py` | 🟡 | `[X]` |
| T021 | [B] Descritores de perfil com 10 kinds (`vvt` suportado) e tabelas de came na navegação e em `live_tunable_table_ids` | T020 | - | `backend/src/simremap/profiles/contracts.py`, `profiles/descriptors/*.py` | 🟡 | `[X]` |
| T022 | [B] `physics/fuel_blend.py::blend_fuel` e registro de cache do solver por chave do blend | T009 | `[//]` | `backend/src/simremap/physics/fuel_blend.py`, `physics/cycle_solver.py` | 🟡 | `[X]` |
| T023 | [B] Sensor flex (`SensorReadings.ethanol_pct`) e compensação na ECU: AFR estequiométrico lido, tabelas `flex_ign_add`/`flex_boost_add` | T022, T002 | - | `backend/src/simremap/ecu/runtime.py`, `physics/engine.py` | 🟡 | `[X]` |
| T024 | [B] `catalog/upgrades.py`: catálogo de peças e `apply_upgrades` (turbo, bicos, bomba, intercooler, downpipe, forjados) | T010 | `[//]` | `backend/src/simremap/catalog/upgrades.py` | 🟡 | `[X]` |
| T025 | [B] Física consome `exhaust_backpressure_scale` (p04/EGT) e `fuel_pump_capacity_scale` (teto da bomba) | T003 | - | `backend/src/simremap/physics/engine.py` | 🟡 | `[X]` |
| T026 | [C] `DefectKind.boost_leak` com `leak_area_mm2` e conversão `to_physics_fault` | T015 | `[//]` | `backend/src/simremap/scenarios/contracts.py` | 🟡 | `[X]` |
| T027 | [C] Cenários `defect-fuel-pump` (queda acima de 5.500 rpm), `defect-boost-leak`, `defect-lean-injector`, `defect-wastegate-stuck` | T026 | `[//]` | `backend/src/simremap/scenarios/builtin/defect-*.json` | 🟡 | `[X]` |
| T028 | [C] `BUILTIN_IDS` com 7 ids e ajuste dos testes que fixam 3 builtins | T027 | - | `backend/src/simremap/scenarios/catalog.py`, `backend/tests/scenarios/test_catalog.py` | 🟡 | `[X]` |
| T029 | [C] Pacote `career`: contratos, `orders.json`, repositório | T004 | `[//]` | `backend/src/simremap/career/` | 🟡 | `[X]` |
| T030 | [C] `CareerService`: aceitar (cria tentativa), liquidar (pagamento, reputação, custo do motor, idempotente) | T029, T015 | - | `backend/src/simremap/career/service.py` | 🟡 | `[X]` |
| T031 | [D] Operações puras `quickTune`, `interpolateH`, `interpolateV`, `blockSmooth` | T011 | `[//]` | `frontend/src/features/ecu-tuning/ops/quickTune.ts` | 🟡 | `[X]` |
| T032 | [D] Atalhos `Q`, `H`, `V`, `B` e botões na barra do `TableEditorCore`; entradas no `ShortcutsDialog` | T031 | - | `frontend/src/features/ecu-tuning/TableEditorCore.tsx` | 🟡 | `[X]` |
| T033 | [D] `LiveTuningPanel`: `WorkspaceStore` da sessão, editor compacto, seletor de tabela, aplicação automática à sessão | T032 | - | `frontend/src/features/dyno-cockpit/live-tuning/LiveTuningPanel.tsx` | 🟡 | `[X]` |
| T034 | [D] Live Cell Tracing: destaque piscante da célula ativa a partir do `TelemetryStore` | T033 | - | `frontend/src/features/dyno-cockpit/live-tuning/liveCell.ts` | 🟡 | `[X]` |
| T035 | [E] `thermalColor(egt)` e camada térmica/raio-X (coletor, turbina) no `drawCarScene` | T012 | `[//]` | `frontend/src/features/dyno-cockpit/render/thermal.ts` | 🟡 | `[X]` |
| T036 | [E] Partículas por modo de falha e chamas de escape nos pops & bangs | T035 | - | `frontend/src/features/dyno-cockpit/render/CarAnimator.ts` | 🟡 | `[X]` |
| T037 | [E] `EngineProfile.archetype` e presets de áudio (lope do clássico, assobio do compressor do V8) | T012 | `[//]` | `frontend/src/features/dyno-cockpit/audio/EngineSynth.ts`, `audio/AudioEngine.ts` | 🟡 | `[X]` |
| T038 | [E] `useHoldThrottle` (Espaço sobe 120 %/s, soltar fecha) integrado ao `RunControls` | T012 | `[//]` | `frontend/src/features/dyno-cockpit/useHoldThrottle.ts`, `RunControls.tsx` | 🟡 | `[X]` |

## Fase 4, Integração

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T039 | [B] `SessionCreateRequest`/`SimulationSession` com `upgrades` e `ethanol_pct`; `_create` aplica `apply_upgrades`, monta o combustível flex e propaga as escalas para `PhysicsConfig` | T024, T023, T025, T018 | - | `backend/src/simremap/dyno/contracts.py`, `dyno/session.py`, `dyno/assembly.py` | 🟡 | `[X]` |
| T040 | [B] Rota `GET /api/v1/upgrades` | T024 | `[//]` | `backend/src/simremap/catalog/router.py` | 🟡 | `[X]` |
| T041 | [B] Canais de telemetria `cam_*` e `ethanol_pct` (channels, sampler, sampler de fallback) | T019, T023 | - | `backend/src/simremap/telemetry/channels.py`, `telemetry/sampler.py`, `dyno/sampler.py` | 🟡 | `[X]` |
| T042 | [B] Testes de integração: sessão com upgrades (IDC menor, IAT menor, limites maiores) e E85 (lambda na janela) | T039 | - | `backend/tests/integration/test_upgrades_flex_session.py` | 🟡 | `[X]` |
| T043 | [C] Router `/api/v1/career` registrado no `api/registry.py` e testes de API da carreira | T030 | - | `backend/src/simremap/career/router.py`, `backend/tests/career/test_api.py` | 🟡 | `[X]` |
| T044 | [C] Teste de física do `defect-fuel-pump` (pobre acima de 5.500 rpm, janela abaixo de 5.000 rpm) e dos outros 3 defeitos | T027 | `[//]` | `backend/tests/scenarios/test_defect_scenarios.py` | 🟡 | `[X]` |
| T045 | [D] Botão "Tela Dividida (Live Tuning)" e layout lado a lado no `DynoCockpitPage` | T034 | - | `frontend/src/features/dyno-cockpit/DynoCockpitPage.tsx` | 🟡 | `[X]` |
| T046 | [F] Exportar OpenAPI e regenerar o cliente orval (`make api-types`) | T039, T040, T043 | - | `frontend/openapi.json`, `frontend/src/lib/api/generated/` | 🟢 | `[X]` |
| T047 | [F] Stage Builder: seletor de peças e controle de etanol na criação de sessão | T046 | - | `frontend/src/features/workshop/StageBuilder.tsx`, `frontend/src/app/HomePage.tsx` | 🟡 | `[X]` |
| T048 | [F] Página "Oficina (Carreira)": perfil, ordens, aceitar, liquidar, histórico | T046 | `[//]` | `frontend/src/features/career/WorkshopPage.tsx` | 🟡 | `[X]` |
| T049 | [F] Rota e item de navegação da carreira (lazy) | T048 | - | `frontend/src/app/routes.tsx`, `app/paths.ts`, `app/App.tsx` | 🟡 | `[X]` |
| T050 | [E] Canal `egt_c` subscrito quando a visão térmica está ligada; toggle "Visão Térmica / Raio-X" no `CarOnRollerView` | T035 | - | `frontend/src/features/dyno-cockpit/CarOnRollerView.tsx`, `channels.ts` | 🟡 | `[X]` |
| T051 | [E] Perfil de áudio por veículo no `useCockpit` | T037 | - | `frontend/src/features/dyno-cockpit/useCockpit.ts` | 🟡 | `[X]` |
| T052 | [D] Workspace ECU trata calibração `stock-*` como somente leitura com ação "clonar e editar" | T033 | `[//]` | `frontend/src/features/ecu-tuning/workspaceStore.ts` | 🟡 | `[X]` |

## Fase 5, Polimento

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T053 | [F] `manualChunks` por fornecedor e importações nomeadas no `Table3DSurface`; todas as páginas lazy | T049 | - | `frontend/vite.config.ts`, `ecu-tuning/Table3DSurface.tsx` | 🟡 | `[X]` |
| T054 | [D] Testes de componente do Live Tuning (célula piscante, aplicação automática) | T045 | `[//]` | `frontend/src/features/dyno-cockpit/live-tuning/LiveTuningPanel.test.tsx` | 🟡 | `[X]` |
| T055 | [F] Testes de componente do Stage Builder e da página da carreira | T047, T048 | `[//]` | `frontend/src/features/career/WorkshopPage.test.tsx` | 🟡 | `[X]` |
| T056 | [E] Atalhos novos (Espaço, visão térmica) no diálogo de atalhos da bancada | T038, T050 | `[//]` | `frontend/src/features/dyno-cockpit/messages.ts` | 🟡 | `[X]` |
| T057 | [B] Log estruturado `scenarios.builtin_hash_resynced` e `session.upgrades_applied` | T015, T039 | `[//]` | `backend/src/simremap/dyno/session.py` | 🟡 | `[X]` |
| T058 | Rodar a suíte backend completa (`ruff`, `mypy --strict`, `bandit`, `pytest`) e corrigir regressões | T042, T043, T044, T057 | - | `backend/` | 🟢 | `[X]` |
| T059 | Rodar `-m accuracy` para confirmar o benchmark sem upgrades | T058 | - | `backend/tests/accuracy/` | 🟡 | `[X]` |
| T060 | Rodar `tsc`, `eslint`, `vitest` e `npm run build`; confirmar chunks ≤ 500 kB | T053, T054, T055, T056 | - | `frontend/` | 🟢 | `[X]` |
| T061 | Atualizar `frontend/dist` servido pelo backend (build de produção) | T060 | - | `frontend/dist/` | 🟢 | `[X]` |
| T062 | Gerar a documentação visual com `/reversa-docs` em `_reversa_docs/` | T061 | - | `_reversa_docs/` | 🟡 | `[X]` |
