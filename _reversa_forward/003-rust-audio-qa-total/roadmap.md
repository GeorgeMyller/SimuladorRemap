# Roadmap: Motor Nativo em Rust, Acústica Realista, QA Total e E2E

> Identificador: `003-rust-audio-qa-total` · Data: `2026-10-19` · Requirements: `requirements.md`

## 1. Resumo da abordagem

Crate `backend/rust/simremap_rs` (PyO3 0.23, ABI3 py312, maturin) com três submódulos de donos distintos: `tables` (ECU), `cycle` (física) e `damage` (detonação e dano). Cada módulo Python correspondente ganha um seletor `simremap.core.native` (`SIMREMAP_NATIVE=auto|off|on`) e chama o kernel nativo em lote por tick (uma travessia FFI por subsistema por tick, nunca por célula), com o Python atual preservado como implementação de referência e testes de paridade. O áudio é reescrito sobre Web Audio com pulsos de combustão, saturação e filtros. QA e E2E rodam em paralelo com escopos de arquivo disjuntos.

## 2. Princípios aplicados

Sem `.reversa/principles.md`; vale `prd.md#6` (laço determinístico, local-first, open-source).

## 3. Decisões técnicas

| ID | Decisão | Confidência |
|----|---------|-------------|
| D-01 | maturin como dev dependency (`uv add --dev maturin`); build com `uv run --frozen maturin develop --release -m rust/simremap_rs/Cargo.toml`; pacote Python `simremap_rs` com extensão `_native` | 🟢 |
| D-02 | Seletor único `simremap/core/native.py`: `SIMREMAP_NATIVE` (`auto` padrão: usa se importar; `off`: nunca; `on`: falha se ausente) | 🟡 |
| D-03 | Granularidade FFI: um kernel por subsistema por tick com arrays/structs planos; nada de chamada por célula | 🟡 |
| D-04 | Paridade: testes `tests/native/` comparam Python × Rust em entradas aleatórias com seed (tolerância rel 1e-9) | 🟡 |
| D-05 | Áudio: cadeia pulsos → WaveShaper → lowpass dinâmico (180→1400 Hz) → peaking 90–140/280–450 Hz → sub-bass → master com shelf de corte em 1–4 kHz; turbo por ruído banda estreita | 🟡 |
| D-06 | `make type`: resolver módulos duplicados com `explicit_package_bases`/`__init__.py` conforme padrão e corrigir erros dos testes | 🟡 |
| D-07 | E2E em modo `SIMREMAP_E2E_LOCAL=1` (backend próprio com diretório de dados temporário), sem tocar no banco do usuário | 🟡 |
| D-08 | Dockerfile: estágio Rust opcional para o wheel (premissa Q1) | 🟡 |

## 4. Premissas

Ver `questions.md` (Q1 Docker, Q2 tolerância).

## 5. Delta arquitetural

| Componente | Tipo | Resumo |
|---|---|---|
| native (novo) | componente-novo | crate Rust + seletor |
| engine-physics-core | regra-alterada | kernels do ciclo e turbo em Rust |
| ecu-core | regra-alterada | interpolação e estratégias em Rust |
| knock-and-failure-model | regra-alterada | detonação e dano em Rust |
| dyno-cockpit-ui | regra-alterada | síntese de áudio nova |

## 6–8. Dados, contratos e migração

Sem mudança de banco nem de contratos externos. Canal de diagnóstico opcional `native_enabled` no `/api/v1/version` (se existir health/version).

## 9. Riscos

| Risco | Mitigação |
|---|---|
| Divergência numérica quebra digests/accuracy | Paridade por kernel; regravar digests só por arquitetura |
| Overhead FFI anula o ganho | Lote por tick; benchmark antes/depois |
| Edição concorrente entre agentes e sessões externas | Escopos disjuntos; reler arquivos antes de editar |
| Docker sem Rust | Fallback Python |

## 10. Critério de pronto

- [ ] Ações `[X]`; `make check` aprovado; Playwright aprovado; build sem erros; adendo 003 e `_reversa_docs/` atualizados.

## 11. Histórico

| Data | Alteração | Autor |
|---|---|---|
| 2026-10-19 | Versão inicial (modo autônomo) | reversa |
