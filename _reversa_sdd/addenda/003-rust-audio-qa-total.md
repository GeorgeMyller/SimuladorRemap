# Adendo: 003-rust-audio-qa-total — Motor Nativo em Rust, Acústica Realista, QA Total e E2E

> Identificador da feature: `003-rust-audio-qa-total`
> Data: `2026-10-19`
> Cenário: **greenfield** (âncora `_reversa_sdd/prd.md` + specs `_reversa_sdd/sdd/`, sobre os adendos vigentes `001` e `002`)

## Vigência

Vigente desde 2026-10-19.

## Resumo da entrega

🟡 A feature 003 entrega quatro frentes:
- **Motor nativo:** extensão nativa `simremap_rs` em Rust (PyO3 ABI3 ≥ 3.12, maturin) com kernels de tabelas/ECU, ciclo Otto/gás/térmico e detonação/dano. Tem fallback Python transparente (`SIMREMAP_NATIVE=auto|off|on`) e paridade bit a bit.
- **Áudio:** síntese da bancada reescrita por pulsos de combustão, sem osciladores puros.
- **QA:** QA total com correções em backend, ECU, física e frontend, e `make type` limpo.
- **Entrega:** E2E Playwright dos fluxos novos, build de produção e mini-site atualizado.

🟡 Ações: 33 de 33 concluídas (30 planejadas + 3 de correção acrescentadas pelo QA). O `progress.jsonl` tem 37 linhas.

🟡 Verificação no fecho:

| Verificação | Resultado |
|---|---|
| `make check`, backend | 2201 aprovados, 78 saltados; cobertura 90,8–99,1 % por pacote |
| Lint, tipos e segurança | `ruff`, `mypy --strict src tests` (440 arquivos) e `bandit` limpos |
| `api-parity` | aprovado |
| Backend com `SIMREMAP_NATIVE=off` | 2155 aprovados, 109 saltados |
| `-m accuracy` | 9/9 com nativo ligado e desligado |
| `-m e2e` | 49 aprovados com nativo ligado; 49 aprovados com nativo desligado |
| Frontend | `tsc` e `eslint` limpos; 628 testes `vitest`; build sem erros e sem chunk > 500 kB |
| Playwright | 24 aprovados na rodada completa; `live-tuning` e `native-engine` com 4/4 após a correção da calibração ativa |

## Impacto por artefato da extração

| Artefato | Seção | Tipo de impacto | Delta |
|---|---|---|---|
| `_reversa_sdd/prd.md` | `#6. Restrições` | componente-novo | 🟡 Camada nativa opcional. Física 2,8× mais rápida (tick médio do hatch 179 → 107 µs, P99 490 → 345 µs), ECU 27,5 → 19,8 µs, dano 48,0 → 7,5 µs. `sweep_pull` sem janelas de overrun nos 4 veículos. A stack continua Python com fallback total; Rust 1.99 e maturin entram só como build opcional (`make native`, estágio opcional no Dockerfile). |
| `_reversa_sdd/sdd/engine-physics-core.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Kernels `CycleKernel`, `GasKernel` e `ThermalKernel` com a referência Python preservada. Linha de surge `0,30·ṁ_choke·√min(N/N_design,1)` com PR mínimo 1,05: surge a plena carga na série cai de 17,2 % para 1,4 % no hatch. |
| `_reversa_sdd/sdd/ecu-core.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Tabelas avaliadas em lote no Rust e flex no Rust; as outras estratégias ficam em Python por ganho desprezível. Correções: dTPS/dt pela mediana de 3 amostras (sem enriquecimento espúrio), BOV pela pressão pré-borboleta (`surge_s` 7,3 → 0,1 s) e 1.º aplicar comparado com a versão carregada. |
| `_reversa_sdd/sdd/knock-and-failure-model.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Kernel Rust da integral de detonação e do passo contínuo de dano; sorteios de LSPI continuam no Python (mesma sequência PCG64). `engine/health` em sessão encerrada passa a responder 409 `SESSION_CLOSED`. |
| `_reversa_sdd/sdd/vehicle-catalog.md` | `#Apêndice A.3` | delta-de-dados | 🟡 PID de boost OEM do hatch passa a kp 0,1 / ki 0,3 / kd 0, com novos `content_hash` e `oem_checksum`. Oscilação de 7,5 Hz cai de ±12,3 para ±0,44 N·m; potência de série 216,3 → 214,7 whp. O coupé e o clássico continuam com os ganhos antigos. |
| `_reversa_sdd/sdd/dyno-bench.md` | `#6. Requisitos Funcionais` | delta-de-contrato-externo | 🟡 `SimulationSession` ganha `active_calibration_id` e `active_calibration_version`. Seeds sorteadas ficam ≤ 2^53−1. Puxada em sessão encerrada passa a 409 `SESSION_CLOSED`. O arrefecimento acelerado do `multi_pull` declara orçamento de parede e não conta como overrun. |
| `_reversa_sdd/sdd/training-scenarios.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 A tentativa é liquidada antes de expor a avaliação; puxadas e restauros são registrados antes do fecho, e a carreira cobra o motor quebrado. Os 7 cenários foram aprovados com acerto real e as 7 ordens pagas (`backend/tests/qa`). |
| `_reversa_sdd/sdd/ecu-profiles.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 A navegação OEM-Stage deixa de listar "Avanço cil. N" (sem tabelas de trim na série). |
| `_reversa_sdd/sdd/platform-foundation.md` | `#6. Requisitos Funcionais` | delta-de-contrato-externo | 🟡 `/api/v1/version` ganha `native_enabled` e `native_version`. Pacote `core/native.py`. `tests/` com `__init__.py` e `mypy_path` (módulos únicos). Alvos `fe-type`, `fe-test` e `e2e-frontend` do Makefile passam a usar `cd frontend`. |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md` | `#6. Requisitos Funcionais` | regra-alterada | 🟡 Áudio com a cadeia: pulsos → WaveShaper → passa-baixa dinâmico 180 → 1400 Hz → ressonadores 90–140 e 280–450 Hz → sub-bass → corte em 2,2 kHz e 4,5 kHz. Turbo por ruído de banda estreita, blow-off e flutter; pops com punch 90–160 Hz, estalo e reverb curto. Energia em 1–4 kHz < 5 % nos 4 arquétipos. A bancada mostra a calibração ativa; 9 correções de QA. |

## Regras sob vigilância

🟡 Watch principal vazio (âncora greenfield). Observações sem peso de regressão: W320–W334, em `_reversa_forward/003-rust-audio-qa-total/regression-watch.md`.

## Fontes

- `_reversa_forward/003-rust-audio-qa-total/legacy-impact.md`
- `_reversa_forward/003-rust-audio-qa-total/regression-watch.md`
- `_reversa_forward/003-rust-audio-qa-total/requirements.md`
- `_reversa_forward/003-rust-audio-qa-total/roadmap.md`
- `_reversa_forward/003-rust-audio-qa-total/questions.md`
- `_reversa_forward/003-rust-audio-qa-total/actions.md`
- `_reversa_forward/003-rust-audio-qa-total/progress.jsonl`
