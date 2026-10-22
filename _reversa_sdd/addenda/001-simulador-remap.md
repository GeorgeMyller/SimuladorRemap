# Adendo: 001-simulador-remap — Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador da feature: `001-simulador-remap`
> Data: `2026-10-18`
> Cenário: **greenfield** (âncora `_reversa_sdd/prd.md` + specs `_reversa_sdd/sdd/`)
> Sincronização: **parcial** (escolha do usuário em 2026-10-18). 452 de 453 ações entregues; T091 em aberto.

## Vigência

Vigente desde 2026-10-18.

## Resumo da entrega

🟡 A feature 001 entrega o MVP do SimuladorRemap como aplicação web local-first num container por estação: backend FastAPI (Python 3.12, uv) com física termodinâmica 0D/1D do ciclo Otto a 100–1000 Hz, modelo de detonação, pré-ignição e dano com laudo forense, dinamômetro virtual, ECU genérica com 4 perfis (OEM-Stage, FT-Pro, M1-Race, HT-Elite) e swap OEM → standalone, catálogo de 4 veículos validados contra o `Reference Benchmark Baseline v1`, telemetria por WebSocket com datalogger, e cenários de treino com avaliação objetiva e pacotes assinados; frontend React + TypeScript + Vite + Tailwind com a bancada (Canvas, Web Audio, gauges, curvas antes vs. depois, espectrograma, autópsia) e o software de tuning (editor 2D/3D, estratégias, wizard de swap). Objetivo do `requirements.md`: integrar os 11 componentes das specs SDD nas jornadas do Lucas, do Rodrigo e do Prof. Marcos.

🟡 Ações: 452 de 453 concluídas (`progress.jsonl` com 476 linhas). Pendente: **T091** (`scripts/smoke_container.sh`, smoke test do container), bloqueada porque o disco da VM do Docker Desktop está cheio; o script existe e `docker compose config` / `docker build --check` passam. Uma reexecução do `/reversa-sync` após a T091 acrescenta uma seção `## Atualização`.

🟡 Verificação no fecho: backend 2035 testes aprovados (35 opt-in saltados), `-m accuracy` + `-m e2e` 17 aprovados, `ruff`/`mypy --strict`/`bandit` limpos; frontend `tsc`, `eslint`, 450 testes `vitest`, `vite build`; Playwright 7/7 (3 jornadas, axe 0 violações A/AA, cockpit p5 60 FPS).

## Impacto por artefato da extração

| Artefato | Seção | Tipo de impacto | Delta |
|---|---|---|---|
| `_reversa_sdd/prd.md` | `#3. Métricas de sucesso` | componente-novo | 🟡 Desvio < 5 % atingido nos 4 veículos contra o `Reference Benchmark Baseline v1` (torque: hatch 3,4 %, coupé 1,4 %, clássico 2,3 %, V8 3,5 %); laço ≥ 1000 Hz medido em Apple Silicon (física 0,078 ms/tick), ainda sem medição no hardware de referência de 4 núcleos. |
| `_reversa_sdd/prd.md` | `#4. Escopo (in)` | componente-novo | 🟡 Todo o escopo do MVP está implementado; o código vive em `backend/` e `frontend/` (mapa por arquivo em `legacy-impact.md`). |
| `_reversa_sdd/prd.md` | `#9. Critérios de aceite (alto nível)` | componente-novo | 🟡 Lucas: série 214,7 whp, Stage 1 +46 whp, Stage 2 com pops & bangs +67,7 whp sem knock e EGT 915 °C; calibração exagerada quebra a biela com laudo de 5 elos. Rodrigo: swap para FT-Pro no clássico, ~334 whp em `multi_pull` com dispersão 0,34 %. Prof. Marcos: desafio exportado, tentativa avaliada com o mesmo `evaluation_sha256` no instrutor. |
| `_reversa_sdd/sdd/platform-foundation.md` | `#6. Requisitos Funcionais` (RF-01..RF-24) | componente-novo | 🟡 Implementado; ler com estes deltas: `worker_mode = process` fixado por benchmark (D-04); `create_app` em `api/main.py` e health/version em `api/health.py` (as ações citavam `api/app.py` e `api/routers/system.py`); lifespan cache → catálogo → worker → routers; limite de corpo resolvido por rota (64 MiB nos imports); ping WS 15 s. |
| `_reversa_sdd/sdd/engine-physics-core.md` | `#6. Requisitos Funcionais` (RF-01..RF-26) e `#Apêndice A` | componente-novo | 🟡 Implementado; ler com estes deltas: pressões dos volumes integradas por Euler linearmente implícito (Heun instável a 1 ms); EGT por cilindro lida na sonda do runner; teto de 2400 K no gás da porta; `S_L,ref` avaliado no estado da faísca. |
| `_reversa_sdd/sdd/vehicle-catalog.md` | `#Apêndice A.3` e `#A.8` | componente-novo | 🟡 Os valores de turbo, compressor, VE, avanço e MAP de série foram recalibrados pelo gerador `catalog/tools/` para cumprir o benchmark e os ganhos de remap. O hatch passou a turbina 3,2 cm² (eficiência de pico 0,79), compressor até 250 000 rpm, `turbo_max_rpm` 250 000 (a spec diz 210 000), intercooler 0,82. O V8 passou a polia 2,10 com teto de MAP 240 kPa. `knock_threshold` das calibrações ficou em 0–1 (0,30–0,45). Os 4 veículos estão `validated`, `catalog_version` 1.1.0. Os dados do catálogo prevalecem sobre a spec até à próxima re-extração. |
| `_reversa_sdd/sdd/dyno-bench.md` | `#6. Requisitos Funcionais` (RF-01..RF-26) | componente-novo | 🟡 Implementado; a sessão fica congelada até o primeiro comando de condução (reprodutibilidade por seed); limitador de pedal no arming; o V8 é medido em 5.ª marcha no aceite (em 4.ª, −5,4 % por inércia); pontos de extensão `StreamHub.set_stream_factory` e `DynoService.add_calibration_listener`. |
| `_reversa_sdd/sdd/knock-and-failure-model.md` | `#6. Requisitos Funcionais` (RF-01..RF-32) e `#Apêndices B–E` | componente-novo | 🟡 Implementado com `DamageConfig` 1.2.0 calibrado com a física: τ de Douaud-Eyzat ×4,25; LSPI só acima de 2700 kPa de IMEP, com probabilidades /10; dano térmico pela temperatura do metal (τ 5 s nas válvulas, 6 s na turbina); limiares de ponto quente +20 °C (E27 840, E0 820, E100 860, Podium 880 °C); junta pelo anel de fogo mais carregado. Os testes das equações continuam com os coeficientes literais da spec. |
| `_reversa_sdd/sdd/ecu-core.md` | `#6. Requisitos Funcionais` (RF-01..RF-33) | componente-novo | 🟡 Implementado; `Table2D`/`Table3D` em `ecu/tables.py`, `Calibration` em `ecu/calibration.py`; banda morta na taxa do TPS; escolhas de interpretação registadas (avanço final = mínimo entre override e normal; corte total inibe os níveis abaixo; no máximo 1 evento de knock por ciclo e cilindro). RF-31 (comando variável, Could) fora do backlog. |
| `_reversa_sdd/sdd/ecu-profiles.md` | `#6. Requisitos Funcionais` (RF-01..RF-31) e `#Apêndice F` | componente-novo | 🟡 Implementado; OEM-Stage ganhou controle de marcha lenta (860–1000 rpm), corte na desaceleração e borboleta acima de 1 atm no V8. Two-step aceite com média ±100 rpm e picos até ±150 rpm. A calibração exagerada da jornada do Lucas usa limites de torque OEM ×1,5. |
| `_reversa_sdd/sdd/telemetry-datalogger.md` | `#6. Requisitos Funcionais` (RF-01..RF-25) | componente-novo | 🟡 Implementado; canal novo `pedal_pct` no DataLog; espectro e traço de pressão só calculados com subscritor; banda de 77 kB/s com compressão WS (231 kB/s sem ela); log JSON de `multi_pull` (~257 MB) excede o limite de import de 64 MiB. |
| `_reversa_sdd/sdd/training-scenarios.md` | `#6. Requisitos Funcionais` (RF-01..RF-27) | componente-novo | 🟡 Implementado; premissas adotadas: `standalone-swap` = 300 whp absolutos, pacotes só SHA-256 sem PIN, taxa de conclusão só nos cenários base com abandonadas no denominador; seeds > 2^53 viajam como texto no pacote; replay aceita até 2 % de diferença no pico. |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md` | `#6. Requisitos Funcionais` (RF-01..RF-22) | componente-novo | 🟡 Implementado; tela inicial com seletor dos 4 carros, perfil e cenário; painel lateral da tentativa; limites de boost dos gauges inferidos (2,0 bar turbo, 1,0 bar supercharger, 0,3 bar aspirado). |
| `_reversa_sdd/sdd/ecu-tuning-ui.md` | `#6. Requisitos Funcionais` (RF-01..RF-22) | componente-novo | 🟡 Implementado; o trim de ignição na UI é ±10° (a tabela aceita ±15°); edição de breakpoints de eixo (EC-05) não implementada; superfície WebGL só testada por geometria e fallback 2D. |
| `_reversa_forward/001-simulador-remap/data-model.md` | `#Migrações` | delta-de-dados | 🟡 19 tabelas em 7 migrações lineares `0001_foundation_base` … `0007_scenarios_base`, validadas em SQLite e PostgreSQL 16. |
| `_reversa_forward/001-simulador-remap/contracts/` | `rest-api.md`, `websocket-telemetry.md`, `simulation-bus.md`, `file-formats.md` | delta-de-contrato-externo | 🟡 Contratos implementados; acréscimos ainda não refletidos nos documentos: campos novos de `telemetry.config`, `spectrum_available` no `session.ready`, canal `pedal_pct`, pontos de extensão do dyno. Cliente REST gerado por orval em `frontend/src/lib/api/generated/` (39 caminhos). |

## Regras sob vigilância

🟡 Watch principal vazio (feature greenfield, sem regras 🟢). Observações sem peso de regressão, em `_reversa_forward/001-simulador-remap/regression-watch.md`:

- 🟡 W001–W024: `platform-foundation`
- 🟡 W025–W050: `engine-physics-core`
- 🟡 W051–W079: `vehicle-catalog`
- 🟡 W080–W105: `dyno-bench`
- 🟡 W106–W137: `knock-and-failure-model`
- 🟡 W138–W170: `ecu-core`
- 🟡 W171–W201: `ecu-profiles`
- 🟡 W202–W226: `telemetry-datalogger`
- 🟡 W227–W253: `training-scenarios`
- 🟡 W254–W275: `dyno-cockpit-ui`
- 🟡 W276–W297: `ecu-tuning-ui`

## Fontes

- `_reversa_forward/001-simulador-remap/legacy-impact.md`
- `_reversa_forward/001-simulador-remap/regression-watch.md`
- `_reversa_forward/001-simulador-remap/requirements.md`
- `_reversa_forward/001-simulador-remap/progress.jsonl`
- `_reversa_forward/001-simulador-remap/actions.md`
- `_reversa_forward/001-simulador-remap/roadmap.md`
- `_reversa_sdd/prd.md`
- `_reversa_sdd/sdd/*.md`
