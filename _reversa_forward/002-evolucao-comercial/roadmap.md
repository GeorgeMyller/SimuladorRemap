# Roadmap: Evolução Comercial — Live Tuning, Oficina de Upgrades, Imersão, Carreira e Blindagem de Cenários

> Identificador: `002-evolucao-comercial`
> Data: `2026-10-18`
> Requirements: `_reversa_forward/002-evolucao-comercial/requirements.md`
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA

## 1. Resumo da abordagem

A feature é um delta sobre os pacotes entregues pela 001 (`backend/src/simremap/*`, `frontend/src/features/*`). Não há reescrita de componentes. A frente 0 corrige a origem do hash dos cenários builtin, adiciona autocura no início da tentativa e torna `stock-*` somente leitura, com a sessão passando a trabalhar num clone. A frente 2 entra na física e na ECU por pontos de extensão que já existem: termo de overlap no `TrueVolumetricEfficiency`, nova estratégia `vvt` no `EcuRuntime`, transformação pura `apply_upgrades(vehicle, pacote)` aplicada em `DynoService._create`, e um `FuelSpec` misturado para o flex. A frente 4 reaproveita `HiddenDefect` → `PhysicsFault` para os cenários novos e cria um pacote `career` sobre o `AttemptService`. As frentes 1 e 3 são só frontend e reaproveitam `WorkspaceStore`, `TableEditorCore`, `OperationCursor`, `AudioEngine` e `CarAnimator`. A frente 5 ajusta o `vite.config.ts` e roda o `/reversa-docs` no fim.

## 2. Princípios aplicados

| Princípio | Como a feature se relaciona | Status |
|-----------|------------------------------|--------|
| (sem `.reversa/principles.md`) | Restrições do `prd.md#6` usadas no lugar: loop ≥ 1000 Hz, zero PII, stack open-source, contratos aditivos | respeita |

## 3. Decisões técnicas

| ID | Decisão | Justificativa | Alternativas descartadas | Confidência |
|----|---------|----------------|--------------------------|-------------|
| D-01 | `ScenarioCatalog.load_builtin` calcula o hash como `compute_content_hash(parse_content(stock.content))`, a mesma rota do clone, e não `stock.content_hash` | Elimina a causa raiz: o clone recalcula o hash após a ida e volta `model_dump` → `parse_content` | Copiar o hash do stock para o clone sem recalcular (esconde corrupção) | 🟡 |
| D-02 | Em `AttemptService.start`, cenário `builtin` com `vehicle_stock` e hash divergente: recria o clone a partir do payload de fábrica do catálogo; se ainda divergir, ressincroniza o `initial_calibration.content_hash` do cenário com o hash do clone (novo `scenario_sha256`, `upsert_builtin`) e segue; loga `scenarios.builtin_hash_resynced` | Pedido explícito; builtins são confiáveis por construção | Abortar com 422 (comportamento atual) | 🟡 |
| D-03 | Erro novo `CALIBRATION_STOCK_IMMUTABLE` (409) em PUT, revert e PATCH de tabela quando `calibration_id` começa por `stock-`; o seed usa o repositório e não passa pela rota | Mantém a v1 de fábrica íntegra | Bloquear no repositório (quebraria o seed) | 🟡 |
| D-04 | `DynoService._create` sem `calibration_id` clona a stock numa calibração do usuário (`source="user"`, nome "Sessão <veículo> <perfil>") e a sessão aponta para o clone | Com D-03 a edição numa sessão comum falharia | Clonar no frontend no primeiro PATCH (só protege um cliente) | 🟡 |
| D-05 | VVT físico: `overlap_deg = overlap_base + vvt_in − vvt_ex` (avanço do escape fecha o escape mais cedo; corrigido na integração); fator `f_ov = 1 + k_ov·tanh(overlap/40)·s(rpm, p_man/p_exh)`, negativo em baixa rotação e positivo em alta rotação com p_man > p_exh; fração residual cresce com overlap em baixa rotação | Fecha OQ-03 do ecu-core; usa só variáveis já presentes no tick | Modelo 1D de ondas (custo alto, quebra o orçamento de 1 ms) | 🟡 |
| D-06 | Nova `StrategyKind.VVT` com `VvtConfig` (habilitação por ECT mínima, taxa máxima, offsets); `EcuRuntime` passa os alvos das tabelas pela estratégia; `EcuProfileDescriptor` passa a exigir 10 kinds; OEM-Stage, FT-Pro, M1-Race e HT-Elite declaram `vvt` como `supported` | Segue o padrão das 9 estratégias existentes | Tratar VVT fora das estratégias (não aparece na UI de estratégias) | 🟡 |
| D-07 | `catalog/upgrades.py`: catálogo fixo de peças por categoria (`turbo`, `injectors`, `fuel_pump`, `intercooler`, `downpipe`, `internals`) e `apply_upgrades(vehicle, UpgradePackage) -> VehicleSpec` via `model_copy`; downpipe e bomba entram como campos novos de `PhysicsConfig` (`exhaust_backpressure_scale`, `fuel_pump_capacity_scale`) | Veículo imutável; física, dano e ECU OEM enxergam o mesmo veículo modificado | Campos novos no JSON do catálogo (mudaria hashes e o benchmark) | 🟡 |
| D-08 | Flex: `physics/fuel_blend.py::blend_fuel(e27, e100, ethanol_pct) -> FuelSpec` com AFR por `1/AFR` linear na fração mássica, PCI, h_fg e densidade lineares, RON/MON por curva empírica; `FuelId` ganha `"flex"`; `SensorReadings.ethanol_pct`; a ECU compensa combustível pelo AFR estequiométrico lido e aplica tabelas 2D opcionais `flex_ign_add` e `flex_boost_add` (eixo `ethanol_pct`) | Mantém o modelo de combustível único da física | Simular dois tanques | 🟡 |
| D-09 | Quick Tune e interpolação H/V/B como operações puras em `frontend/src/features/ecu-tuning/ops/` reutilizadas pelo `TableEditorCore`; `H`/`V` usam a interpolação por eixo já existente, `B` usa a suavização 3×3 | Testável sem DOM; reaproveita RF-06/RF-07 do ecu-tuning-ui | Lógica dentro do componente | 🟡 |
| D-10 | Live Tuning: `LiveTuningPanel` dentro da bancada monta um `WorkspaceStore` da sessão e o `TableEditorCore` compacto com `OperationCursor` alimentado pelo `TelemetryStore` da bancada; após cada lote de PATCH com sucesso chama `applyToSession` | Reusa o editor inteiro em vez de duplicá-lo | iframe da página ECU | 🟡 |
| D-11 | Áudio: `EngineProfile.archetype` (`i4_turbo_modern`, `i6_turbo`, `i4_turbo_classic`, `v8_supercharged`) derivado do veículo; presets de harmônicos, lope de came no clássico e oscilador de assobio do compressor no V8 | Diferença audível com o motor de áudio atual | Amostras gravadas (licença e peso) | 🟡 |
| D-12 | Visão térmica: camada extra no `drawCarScene` com coletor e turbina desenhados nos pontos `exhaust`/`engineBay` do sprite; cor por `thermalColor(egt_c)`; partículas por modo de falha no `CarAnimator` | Canvas 2D atual; sem dependência nova | WebGL | 🟡 |
| D-13 | Pedal progressivo: `useHoldThrottle` com taxa de subida 120 %/s enquanto Espaço está pressionado e retorno a 0 % no keyup; continua usando o `ThrottleSender` | Mantém o limite de 20 msg/s | Enviar keydown/keyup ao backend | 🟡 |
| D-14 | Cenários de defeito: 4 JSONs novos em `scenarios/builtin/`, `BUILTIN_IDS` com 7 ids; `DefectKind` ganha `boost_leak` (`leak_area_mm2`); `defect-lean-injector` usa `injector_clogged`; `defect-fuel-pump` com `fuel_pump_max_lph` calibrado para cair acima de 5.500 rpm | Reaproveita `HiddenDefect.to_physics_fault` | Novo tipo de falha na física | 🟡 |
| D-15 | Pacote `backend/src/simremap/career/` (contratos, repositório, serviço, router `/api/v1/career`), migração `0008_career`, ordens de serviço fixas em `career/orders.json` vinculadas a `scenario_id` | Premissa Q1 | Estado no navegador | 🟡 |
| D-16 | Code-splitting: `build.rolldownOptions.output.codeSplitting.groups` (Vite 8/rolldown; `manualChunks` obsoleto) separando `three`, `react`/`react-dom`/router e libs de gráfico; `Table3DSurface` com importações nomeadas; todas as páginas por `React.lazy` (inclusive a da carreira) | Premissa Q3 | Subir `chunkSizeWarningLimit` | 🟡 |
| D-17 | Contratos novos regeram o cliente orval (`make api-types`) para manter o `api-parity` | Portão `make check` | Editar o gerado à mão | 🟢 |

## 4. Premissas

| Premissa | Origem (`requirements.md` seção) | Risco se errada |
|----------|----------------------------------|-----------------|
| Estado da carreira no banco do backend (Q1) | `#10. Lacunas` | Médio: troca de armazenamento |
| Teor de etanol fixo por sessão (Q2) | `#10. Lacunas` | Baixo: endpoint de reabastecimento depois |
| Núcleo 3D isolado se passar de 500 kB, sem esconder o aviso (Q3) | `#10. Lacunas` | Baixo |

## 5. Delta arquitetural

| Componente | Arquivo de origem no legado | Tipo de mudança | Resumo |
|------------|------------------------------|-----------------|--------|
| training-scenarios | `_reversa_sdd/sdd/training-scenarios.md` | regra-alterada | Autocura de hash em builtins; 4 cenários novos; `boost_leak` em `DefectKind` |
| ecu-core | `_reversa_sdd/sdd/ecu-core.md` | regra-nova | `stock-*` imutável; estratégia `vvt`; sensor de etanol e compensação flex |
| ecu-profiles | `_reversa_sdd/sdd/ecu-profiles.md` | regra-alterada | 10 kinds no descritor; tabelas de came na navegação |
| engine-physics-core | `_reversa_sdd/sdd/engine-physics-core.md` | regra-nova | Overlap no VVT; blend de combustível; escalas de contrapressão e bomba |
| vehicle-catalog | `_reversa_sdd/sdd/vehicle-catalog.md` | componente-novo | `catalog/upgrades.py` com peças e `apply_upgrades` |
| dyno-bench | `_reversa_sdd/sdd/dyno-bench.md` | contrato-alterado | `upgrades` e `ethanol_pct` na criação; clone da stock por sessão |
| telemetry-datalogger | `_reversa_sdd/sdd/telemetry-datalogger.md` | contrato-alterado | Canais de came e `ethanol_pct` |
| career (novo) | — | componente-novo | Perfil, ordens, liquidação |
| dyno-cockpit-ui | `_reversa_sdd/sdd/dyno-cockpit-ui.md` | regra-nova | Tela dividida, visão térmica, áudio por arquitetura, pedal progressivo |
| ecu-tuning-ui | `_reversa_sdd/sdd/ecu-tuning-ui.md` | regra-nova | Quick Tune `Q`; `H`/`V`/`B` |
| platform-foundation (frontend) | `_reversa_sdd/sdd/platform-foundation.md` | regra-alterada | Divisão de chunks; rota da carreira |

## 6. Delta no modelo de dados

- Resumo: duas tabelas novas (`career_profiles`, `career_jobs`) na migração `0008_career`; nenhum campo novo nas tabelas existentes. Contratos Pydantic ganham campos opcionais.
- Detalhe completo em: `_reversa_forward/002-evolucao-comercial/data-delta.md`

## 7. Delta de contratos externos

| Contrato | Tipo | Arquivo de detalhe |
|----------|------|--------------------|
| Calibrações (imutabilidade stock) | HTTP | `interfaces/calibrations-stock.md` |
| Sessões (upgrades, flex) e catálogo de upgrades | HTTP | `interfaces/sessions-upgrades-flex.md` |
| Carreira | HTTP | `interfaces/career.md` |
| Telemetria (canais novos) | WebSocket | `interfaces/telemetry-channels.md` |

## 8. Plano de migração

1. Alembic `0008_career` cria as duas tabelas; roda no arranque como as anteriores.
2. Cenários builtin: no próximo arranque o `load_builtin` grava o hash corrigido (`updated`); os 4 novos entram como `inserted`.
3. Sessões já existentes continuam apontando para `stock-*`; elas ficam só leitura e a interface oferece "clonar e editar". Sessões novas já nascem com clone.

## 9. Riscos e mitigações

| Risco | Impacto | Probabilidade | Mitigação |
|-------|---------|---------------|-----------|
| Overlap muda a VE de série e quebra o benchmark | alto | médio | `k_ov` calibrado para efeito nulo na posição de came de série; rodar `-m accuracy` |
| Testes que assumem 9 estratégias, 3 builtins ou `session.calibration_id == stock-*` | médio | alto | Atualizar esses testes na mesma ação |
| Custo por tick do VVT e do blend | médio | baixo | Blend calculado uma vez na criação; overlap só com `tanh` |
| Chunk de three.js > 500 kB | baixo | médio | Premissa Q3 |
| Projeto sem git | médio | — | Snapshot em `.reversa/snapshots/pre-002-*.tgz` |

## 10. Critério de pronto

- [ ] Todas as ações do `actions.md` marcadas `[X]`
- [ ] `pytest` backend, `vitest`, `tsc`, `eslint`, `ruff`, `mypy --strict` aprovados
- [ ] `npm run build` sem chunk > 500 kB (ou exceção registrada conforme Q3)
- [ ] `regression-watch.md` gerado
- [ ] Adendo `_reversa_sdd/addenda/002-evolucao-comercial.md` e `_reversa_docs/` gerados

## 11. Histórico de alterações

| Data | Alteração | Autor |
|------|-----------|-------|
| 2026-10-18 | Versão inicial gerada por `/reversa-plan` (modo autônomo) | reversa |
