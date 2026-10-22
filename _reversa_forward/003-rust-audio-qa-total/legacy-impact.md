# Legacy Impact: 003-rust-audio-qa-total

> Data: 2026-10-19
> Feature: `003-rust-audio-qa-total`
> Âncora: greenfield (`_reversa_sdd/prd.md` + specs `_reversa_sdd/sdd/`) com adendos vigentes `001` e `002`. Os tipos de impacto descrevem o delta sobre o código das features 001 e 002.
> Política de edição: `allowLegacyEdits: true`, `allowedPaths: []` (liberação irrestrita).
> O projeto não é repositório git; o mapa completo de arquivos por ação está em `progress.jsonl`.

## Arquivos afetados

| Arquivo afetado | Componente | Tipo | Severidade | Justificativa |
|---|---|---|---|---|
| `backend/rust/simremap_rs/` (Cargo.toml, pyproject.toml, `src/lib.rs`, `src/tables.rs`, `src/tables/strategies.rs`, `src/cycle.rs`, `src/cycle/{solver,gas,thermal,interp}.rs`, `src/damage.rs`, `python/simremap_rs/`) | native (novo) | componente-novo | HIGH | Kernels PyO3 ABI3 ≥ 3.12 de tabelas/ECU, ciclo Otto/gás/térmico e detonação/dano |
| `backend/src/simremap/core/native.py` | platform-foundation | componente-novo | MEDIUM | Seletor `SIMREMAP_NATIVE=auto\|off\|on` |
| `backend/pyproject.toml`, `backend/uv.lock` | platform-foundation | regra-alterada | LOW | maturin como dev dependency; configuração mypy (`mypy_path`, `exclude`) |
| `backend/src/simremap/ecu/native_tables.py`, `ecu/runtime.py` | ecu-core | regra-alterada | MEDIUM | Tabelas avaliadas em lote no Rust; flex no Rust; dTPS/dt por mediana de 3 amostras (B1); BOV referenciada à pressão pré-borboleta (B4) |
| `backend/src/simremap/ecu/apply.py`, `ecu/session_port.py` | ecu-core | regra-alterada | MEDIUM | 1.º aplicar compara com a versão carregada (B2) |
| `backend/src/simremap/physics/kernels.py`, `physics/fastmodel.py`, `physics/engine.py`, `physics/cycle_solver.py` | engine-physics-core | regra-alterada | HIGH | Ponte para os kernels Rust; construção rápida de contratos; referência Python preservada |
| `backend/src/simremap/physics/turbo.py` | engine-physics-core | regra-alterada | MEDIUM | Linha de surge com recuo em baixa rotação e PR mínimo 1,05 (B4), espelhada em `cycle/gas.rs` |
| `backend/src/simremap/damage/native_bridge.py`, `damage/knock.py`, `damage/model.py` | knock-and-failure-model | regra-alterada | MEDIUM | Kernel Rust do passo contínuo e da integral de knock; cache de `ComponentHealth` |
| `backend/src/simremap/damage/router.py` | knock-and-failure-model | regra-alterada | LOW | `engine/health` em sessão encerrada → 409 `SESSION_CLOSED` |
| `backend/src/simremap/dyno/contracts.py`, `dyno/session.py`, `dyno/ports.py`, `dyno/repository.py`, `dyno/runner.py` | dyno-bench | delta-de-contrato-externo | HIGH | `active_calibration_id/version`; seeds sorteadas ≤ 2^53−1; `_require_open` (409 `SESSION_CLOSED`); orçamento de parede no arrefecimento |
| `backend/src/simremap/core/worker/loop.py` | platform-foundation | regra-alterada | MEDIUM | Overrun conta só acima de `dt × wall_budget_ticks` |
| `backend/src/simremap/api/health.py` | platform-foundation | delta-de-contrato-externo | LOW | `native_enabled`, `native_version` em `/api/v1/version` |
| `backend/src/simremap/scenarios/attempts.py` | training-scenarios | regra-alterada | HIGH | Estado da tentativa liquidado antes da avaliação; puxadas e restauros registrados antes do fecho (carreira cobra motor quebrado) |
| `backend/src/simremap/profiles/descriptors/oem_stage.py` | ecu-profiles | regra-alterada | LOW | Itens "Avanço cil. N" fora da navegação OEM |
| `backend/src/simremap/catalog/tools/gen_data.py`, `catalog/data/vehicles/hatch-20t-gdi/*`, `catalog/data/manifest.json` | vehicle-catalog | delta-de-dados | MEDIUM | PID de boost OEM do hatch kp 0,1 / ki 0,3 / kd 0 (B5); `content_hash` regenerado |
| `backend/tests/**/__init__.py` e testes existentes | qualidade | regra-alterada | LOW | Módulos únicos; `make type` limpo |
| `backend/tests/native/`, `tests/bench/`, `tests/qa/` | qualidade | componente-novo | LOW | Paridade, benchmark do tick, QA de fluxos, cenários e carreira |
| `Dockerfile`, `Makefile`, `.dockerignore` | platform-foundation | regra-alterada | LOW | Estágio Rust opcional; `make native`; `target/` fora do contexto |
| `frontend/src/features/dyno-cockpit/audio/*` | dyno-cockpit-ui | regra-alterada | MEDIUM | Síntese por pulsos com saturação, passa-baixa dinâmico, ressonadores, turbo por ruído, pops graves |
| `frontend/src/app/homeApi.ts`, `features/scenarios/*`, `features/career/*`, `features/dyno-cockpit/{DynoCockpitPage,DynoChart,ShortcutsDialog}.tsx`, `live-tuning/*`, `features/ecu-tuning/{types,workspaceStore}.ts` | frontend | regra-alterada | MEDIUM | 9 correções de QA e uso da calibração ativa |
| `frontend/e2e/*.spec.ts`, `e2e/helpers.ts`, `playwright.config.ts` | qualidade | componente-novo | LOW | 8 specs novos; `SIMREMAP_E2E_NATIVE` |
| `frontend/openapi.json`, `frontend/src/lib/api/generated/` | platform-foundation | delta-de-contrato-externo | LOW | Cliente regenerado |

## Diff conceitual

- **native:** a simulação ganha um caminho nativo opcional com paridade bit a bit e fallback Python. Física 2,8× mais rápida, ECU −28 %, dano −84 %.
- **engine-physics-core:** o surge deixa de aparecer a plena carga na série.
- **ecu-core:** o enriquecimento de aceleração ignora ruído do TPS, a BOV abre no coastdown e o 1.º aplicar faz o diff certo.
- **dyno-bench:** a sessão informa a calibração ativa e as seeds são seguras para JavaScript.
- **dyno-cockpit-ui:** o áudio deixa de usar osciladores puros.

## Preservadas

Âncora greenfield sem regras 🟢. Continuam válidos: desvio < 5 % no benchmark (nativo ligado e desligado), determinismo por seed, contratos existentes (todos os campos novos são aditivos).

## Modificadas

- `calibration_id` da sessão segue como calibração inicial; a ativa vive em `active_calibration_id`.
- Overrun do worker não conta os ticks de arrefecimento acelerado acima do orçamento declarado.
- Calibração de fábrica do hatch mudou os ganhos do PID de boost (potência de série 216,3 → 214,7 whp).
