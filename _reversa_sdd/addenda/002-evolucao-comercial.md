# Adendo: 002-evolucao-comercial — Live Tuning, Oficina de Upgrades, Imersão, Carreira e Blindagem de Cenários

> Identificador da feature: `002-evolucao-comercial`
> Data: `2026-10-19`
> Cenário: **greenfield** (âncora `_reversa_sdd/prd.md` + specs `_reversa_sdd/sdd/`, sobre o adendo vigente `001-simulador-remap.md`)

## Vigência

Vigente desde 2026-10-19.

## Resumo da entrega

🟡 A feature 002 evolui o MVP da 001 em seis frentes:
- **Frente 0:** elimina o `SCENARIO_CALIBRATION_HASH_MISMATCH` nos cenários builtin, que agora se autocuram, e torna as calibrações `stock-*` somente leitura.
- **Frente 1:** tela dividida de Live Tuning na bancada com Live Cell Tracing, Quick Tune `Q` e interpolação `H`/`V`/`B`.
- **Frente 2:** VVT com cruzamento de válvulas na física e estratégia `vvt` na ECU. Também traz a oficina de upgrades (turbina, bicos, bomba, intercooler, downpipe, forjados) e o flex E27–E100 com sensor de etanol.
- **Frente 3:** áudio por arquitetura, visão térmica/raio-X e pedal com mola no Espaço.
- **Frente 4:** 4 cenários com defeito oculto e modo carreira.
- **Frente 5:** code-splitting sem chunk > 500 kB e documentação visual em `_reversa_docs/`.

🟡 Ações: 62 de 62 concluídas (`progress.jsonl` com 64 linhas, incluindo 2 correções).

🟡 Verificação no fecho:
- **Backend:** 2128 testes aprovados (35 saltados); `-m accuracy` 9 e `-m e2e` 8 aprovados; cobertura ≥ 85 % em todos os pacotes; `ruff` e `bandit` limpos. `mypy --strict src` limpo; `make type` com os testes continua falhando como antes da feature, por módulos duplicados.
- **Frontend:** `tsc`, `eslint` e 571 testes `vitest` aprovados; `vite build` sem chunk > 500 kB (maior: `vendor-three` 352 kB).
- **Ressalva:** depois dessa verificação, uma edição externa concorrente em `DynoCockpitPage.tsx` introduziu 2 erros de tipo, que não foram corrigidos.

## Impacto por artefato da extração

| Artefato | Seção | Tipo de impacto | Delta |
|---|---|---|---|
| `_reversa_sdd/sdd/training-scenarios.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Hash da calibração inicial de builtin recalculado pela rota do clone. Divergência em builtin `vehicle_stock` se autocura: reclona da fábrica ou ressincroniza o cenário, com log `scenarios.builtin_hash_resynced`. Não builtin mantém 422. |
| `_reversa_sdd/sdd/training-scenarios.md` | `#9. Modelo de Dados` | componente-novo | 🟡 `DefectKind.boost_leak` (`leak_area_mm2`, 5–200 mm², fora do hash quando vazio). 7 builtins base: os 3 da 001 mais `defect-fuel-pump` (84 L/h), `defect-boost-leak` (150 mm²), `defect-lean-injector` (cil. 3, 0,85) e `defect-wastegate-stuck` (80 %), todos no hatch. |
| `_reversa_sdd/sdd/ecu-core.md` | `#6. Requisitos Funcionais` (RF-31) | regra-nova | 🟡 RF-31 entregue como estratégia `vvt` (ECT mínima, taxa, offsets). `stock-*` imutável pela API (409 `CALIBRATION_STOCK_IMMUTABLE`). Sensor de etanol com compensação de massa e densidade e tabelas `flex_ign_add`/`flex_boost_add`. |
| `_reversa_sdd/sdd/ecu-profiles.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 `EcuProfileDescriptor` exige 10 kinds; `vvt` suportado nos 4 perfis; tabelas de came na navegação e live-tunable. |
| `_reversa_sdd/sdd/engine-physics-core.md` | `#6. Requisitos Funcionais` e `#Apêndice A` | regra-nova | 🟡 `ValveOverlap`: `overlap = 0,25·(IVC+EVO) + vvt_in − vvt_ex`, efeito relativo ao cronograma de série (zero na série); VE ×(1 + 0,08·d·s); atuador de 1.ª ordem com `actuator_tau_s`. `blend_fuel` E27–E100 (`fuel_id` `flex`). `PhysicsConfig` ganha `exhaust_backpressure_scale` e `fuel_pump_capacity_scale`. |
| `_reversa_sdd/sdd/vehicle-catalog.md` | `#Apêndice A.3` | componente-novo | 🟡 `catalog/upgrades.py` e `GET /api/v1/upgrades`. Coeficientes: turbo área ×1,25, choke ×1,30, inércia ×1,45; bicos ×1,5; bomba 1,8; intercooler +0,08; downpipe 0,6; forjados ×1,35/×1,25/+40 °C. Peça incompatível gera 422 `UPGRADE_NOT_COMPATIBLE`. JSONs do catálogo inalterados. |
| `_reversa_sdd/sdd/dyno-bench.md` | `#6. Requisitos Funcionais` | delta-de-contrato-externo | 🟡 `POST /sessions` aceita `upgrades` e `ethanol_pct` (27–100; veículo sem e27 e e100 gera 409 `FUEL_NOT_ALLOWED`). Sessão sem `calibration_id` nasce com clone do usuário. Fecho de sessão idempotente (corrige 500 no abandono durante a baseline). Sessão flex grava a âncora mais próxima em `fuel_id`. |
| `_reversa_sdd/sdd/telemetry-datalogger.md` | `#6. Requisitos Funcionais` | delta-de-contrato-externo | 🟡 Canais `cam_intake_deg`, `cam_exhaust_deg`, `cam_intake_target_deg`, `cam_exhaust_target_deg` e `ethanol_pct`. |
| `_reversa_sdd/sdd/knock-and-failure-model.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Limiar de pré-ignição interpolado para o combustível flex; limites estruturais vêm do veículo com upgrades. |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md` | `#6. Requisitos Funcionais` | regra-nova | 🟡 Tela dividida (`L`) com Live Cell Tracing e aplicação automática; visão térmica/raio-X (`T`) de 650 a 980 °C; partículas por modo de falha; áudio com 4 arquétipos (assobio do compressor no V8); pedal com mola no Espaço (120 %/s); Stage Builder e controle de etanol na criação de sessão. |
| `_reversa_sdd/sdd/ecu-tuning-ui.md` | `#6. Requisitos Funcionais` (RF-05 a RF-07) | regra-nova | 🟡 Quick Tune `Q` (`VE × λm/λt`, ±25 %, só VE); `H`/`V`/`B`; `stock-*` somente leitura com "Clonar e editar". |
| `_reversa_sdd/sdd/platform-foundation.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Todas as páginas lazy exceto NotFound; `codeSplitting.groups` do rolldown (Vite 8) no lugar de `manualChunks`; cliente orval com 44 caminhos; `career` no portão de cobertura. |
| `_reversa_sdd/prd.md` | `#4. Escopo (in)` | componente-novo | 🟡 Modo carreira (`/api/v1/career`, página `/workshop`): saldo, reputação, 7 ordens ligadas a cenários, liquidação idempotente. Migração `0008_career` com as tabelas `career_profiles` e `career_jobs`. |
| `_reversa_forward/001-simulador-remap/data-model.md` | `#Migrações` | delta-de-dados | 🟡 8 migrações lineares; `0008_career` (22 tabelas no total). |

## Regras sob vigilância

🟡 Watch principal vazio (âncora greenfield). Observações sem peso de regressão: W298–W319, em `_reversa_forward/002-evolucao-comercial/regression-watch.md`.

## Fontes

- `_reversa_forward/002-evolucao-comercial/legacy-impact.md`
- `_reversa_forward/002-evolucao-comercial/regression-watch.md`
- `_reversa_forward/002-evolucao-comercial/requirements.md`
- `_reversa_forward/002-evolucao-comercial/roadmap.md`
- `_reversa_forward/002-evolucao-comercial/actions.md`
- `_reversa_forward/002-evolucao-comercial/progress.jsonl`
- `_reversa_forward/002-evolucao-comercial/questions.md`
- `_reversa_forward/002-evolucao-comercial/interfaces/`
