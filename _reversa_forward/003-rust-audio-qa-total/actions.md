# Actions: Motor Nativo em Rust, Acústica Realista, QA Total e E2E

> Identificador: `003-rust-audio-qa-total` · Data: `2026-10-19` · Roadmap: `roadmap.md`

Trilhas: **R0** esqueleto (orquestrador) · **RA** tabelas/ECU (`rust/.../tables.rs`, `ecu/`) · **RB** ciclo/turbo (`cycle.rs`, `physics/`) · **RC** detonação/dano (`damage.rs`, `damage/`) · **AU** áudio (`dyno-cockpit/audio/`) · **QT** tipos e `make type` (`tests/` existentes) · **QB** QA backend de fluxos, cenários e carreira (`scenarios/`, `career/`, `dyno/` não físico, `profiles/`) · **QF** QA frontend + E2E (`frontend/` exceto `audio/`, `frontend/e2e/`) · **FN** fechamento (orquestrador).

## Resumo

| Métrica | Valor |
|---------|-------|
| Total de ações | 30 |
| Paralelizáveis (`[//]`) | 22 |
| Maior cadeia de dependência | 4 (T001 → T004 → T009 → T027) |

## Fase 1, Preparação

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T001 | [R0] maturin dev dep, crate `simremap_rs` (PyO3 ABI3), submódulos vazios, build verificado | - | - | `backend/rust/simremap_rs/` | 🟢 | `[X]` |
| T002 | [R0] Corrigir os 2 erros TS de `DynoCockpitPage.tsx` (summary nulo; `peak_whp`) | - | `[//]` | `frontend/src/features/dyno-cockpit/DynoCockpitPage.tsx` | 🟢 | `[X]` |
| T003 | [RA] Seletor `simremap/core/native.py` (`SIMREMAP_NATIVE`) e benchmark de referência do tick Python | T001 | - | `backend/src/simremap/core/native.py` | 🟡 | `[X]` |

## Fase 2, Testes

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T004 | [RA] Testes de paridade de interpolação e estratégias | T003 | `[//]` | `backend/tests/native/test_tables_parity.py` | 🟡 | `[X]` |
| T005 | [RB] Testes de paridade do ciclo, turbo e compressor | T003 | `[//]` | `backend/tests/native/test_cycle_parity.py` | 🟡 | `[X]` |
| T006 | [RC] Testes de paridade de detonação e dano | T003 | `[//]` | `backend/tests/native/test_damage_parity.py` | 🟡 | `[X]` |
| T007 | [AU] Testes do grafo de áudio (cadeia, corte dinâmico, sem seno de spool, 1–4 kHz) | - | `[//]` | `frontend/src/features/dyno-cockpit/audio/*.test.ts` | 🟡 | `[X]` |

## Fase 3, Núcleo

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T008 | [RA] Kernels Rust de interpolação 1D/2D e eixos | T004 | - | `backend/rust/simremap_rs/src/tables.rs` | 🟡 | `[X]` |
| T009 | [RA] Kernels Rust das estratégias (boost PID, VVT/overlap, overrun, two-step, flex) | T008 | - | `backend/rust/simremap_rs/src/tables.rs` | 🟡 | `[X]` |
| T010 | [RB] Kernel Rust do ciclo Otto (Wiebe, VE, entalpia, EGT) | T005 | `[//]` | `backend/rust/simremap_rs/src/cycle.rs` | 🟡 | `[X]` |
| T011 | [RB] Kernel Rust do rotor do turbo e compressor mecânico | T010 | - | `backend/rust/simremap_rs/src/cycle.rs` | 🟡 | `[X]` |
| T012 | [RC] Kernel Rust da integral de detonação e dano dos 6 modos | T006 | `[//]` | `backend/rust/simremap_rs/src/damage.rs` | 🟡 | `[X]` |
| T013 | [AU] Nova síntese: pulsos + WaveShaper + lowpass dinâmico + ressonadores + sub-bass | T007 | `[//]` | `frontend/src/features/dyno-cockpit/audio/AudioEngine.ts` | 🟡 | `[X]` |
| T014 | [AU] Turbo por ruído banda estreita, flutter/chirp, blow-off | T013 | - | `frontend/src/features/dyno-cockpit/audio/AudioEngine.ts` | 🟡 | `[X]` |
| T015 | [AU] Pops & bangs graves e 4 arquétipos sem estridência | T013 | - | `frontend/src/features/dyno-cockpit/audio/EngineSynth.ts` | 🟡 | `[X]` |
| T016 | [QT] `make type` limpo (módulos duplicados e erros dos testes) | - | `[//]` | `backend/tests/`, `backend/pyproject.toml` | 🟡 | `[X]` |

## Fase 4, Integração

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T017 | [RA] Integração nativa na ECU com fallback | T009 | - | `backend/src/simremap/ecu/` | 🟡 | `[X]` |
| T018 | [RB] Integração nativa na física com fallback | T011 | - | `backend/src/simremap/physics/` | 🟡 | `[X]` |
| T019 | [RC] Integração nativa no dano com fallback | T012 | - | `backend/src/simremap/damage/` | 🟡 | `[X]` |
| T020 | [QB] QA de sessão livre, encerramento, retomada, upgrades, etanol, puxadas (4 tipos), autópsia, restauração, swap e base setup via API | - | `[//]` | `backend/tests/qa/` | 🟡 | `[X]` |
| T021 | [QB] 7 cenários iniciam, rodam baseline e são aprovados com acerto real | - | `[//]` | `backend/tests/qa/test_scenarios_approvable.py` | 🟡 | `[X]` |
| T022 | [QB] 7 ordens da carreira aceitas, executadas e liquidadas com pagamento | T021 | - | `backend/tests/qa/test_career_orders.py` | 🟡 | `[X]` |
| T023 | [QF] QA das telas (início, bancada, ECU, cenários, oficina) com correções e testes de componente | T002 | `[//]` | `frontend/src/` | 🟡 | `[X]` |
| T024 | [QF] E2E Playwright: carreira, Stage Builder, cenários de defeito, Live Tuning, áudio, motor nativo | T023 | - | `frontend/e2e/` | 🟡 | `[X]` |

## Fase 5, Polimento

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T025 | [RB] Benchmark antes/depois do tick e verificação sem `worker.overrun` | T017, T018, T019 | - | `backend/tests/bench/` | 🟡 | `[X]` |
| T026 | [RB] Dockerfile com estágio Rust opcional e alvo `make native` | T018 | `[//]` | `Dockerfile`, `Makefile` | 🟡 | `[X]` |
| T027 | [FN] `make check` completo, `-m accuracy` e `-m e2e` com nativo ligado e desligado | T025, T016, T020, T022 | - | `backend/` | 🟢 | `[X]` |
| T028 | [FN] `npm run build` sem erros e `frontend/dist` atualizado | T015, T024 | - | `frontend/dist/` | 🟢 | `[X]` |
| T029 | [FN] Atualizar o mini-site `_reversa_docs/` com a 003 | T027, T028 | - | `_reversa_docs/` | 🟡 | `[X]` |
| T030 | [FN] `legacy-impact.md`, `regression-watch.md` e adendo 003 | T029 | - | `_reversa_forward/003-rust-audio-qa-total/` | 🟢 | `[X]` |

## Fase 6, Correções repassadas pelo QA (acrescentada na execução)

| ID | Descrição | Dependências | Paralelismo | Arquivo alvo | Confidência | Status |
|----|-----------|--------------|-------------|--------------|-------------|--------|
| T031 | [FX1] Sessão expõe a calibração ativa após aplicar/swap/base setup; seed ≤ 2^53−1; `native_enabled` em `/version`; arrefecimento do `multi_pull` sem overrun; `engine/health` em sessão encerrada → 409; UI usa a calibração ativa; cliente orval regenerado | T020, T024 | `[//]` | `backend/src/simremap/dyno/`, `damage/router.py`, `api/health.py`, `frontend/src/features/ecu-tuning/workspaceStore.ts` | 🟡 | `[X]` |
| T032 | [FX2] ECU: dTPS espúrio no enriquecimento de aceleração (B1), diff do 1.º aplicar contra a versão carregada (B2), navegação OEM só com os cilindros do motor | T020 | `[//]` | `backend/src/simremap/ecu/runtime.py`, `ecu/apply.py`, `profiles/descriptors/` | 🟡 | `[X]` |
| T033 | [FX3] Física: surge do compressor na série (B4) e oscilação de 7,5 Hz do torque (B5), em Python e Rust com paridade | T018 | `[//]` | `backend/src/simremap/physics/`, `backend/rust/simremap_rs/src/cycle/` | 🟡 | `[X]` |
