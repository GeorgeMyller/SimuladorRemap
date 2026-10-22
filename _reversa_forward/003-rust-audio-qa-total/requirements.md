# Requirements: Motor Nativo em Rust, Acústica Realista, QA Total e E2E

> Identificador: `003-rust-audio-qa-total`
> Data: `2026-10-19`
> Pasta da extração reversa: `_reversa_sdd/` (âncora greenfield + adendos vigentes `001` e `002`)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA / DÚVIDA

## 1. Resumo executivo

A feature 003 tem quatro frentes. A primeira move os kernels de alta frequência da simulação (tabelas e estratégias da ECU, solver do ciclo Otto e turbo, detonação e dano) para Rust nativo via PyO3, com fallback transparente em Python. A segunda reformula a síntese de áudio da bancada para um som mecânico e orgânico. A terceira corrige erros de tipo, limpa o `make type` e faz QA funcional de todas as telas e fluxos. A quarta cobre os fluxos novos com E2E Playwright, gera o build de produção, atualiza o mini-site e fecha o adendo.

## 2. Contexto a partir do legado

| Fonte | Trecho relevante | Confidência |
|-------|------------------|-------------|
| `_reversa_sdd/prd.md#6. Restrições` | Loop ≥ 100 Hz (alvo 1000 Hz); hardware de referência 4 núcleos sem GPU | 🟡 |
| `_reversa_sdd/sdd/engine-physics-core.md#6. Requisitos Funcionais` | Solver 0D/1D, Wiebe, VE, EGT, turbo e compressor | 🟡 |
| `_reversa_sdd/sdd/knock-and-failure-model.md#6. Requisitos Funcionais` | Douaud-Eyzat / Livengood-Wu e 6 modos de dano | 🟡 |
| `_reversa_sdd/sdd/ecu-core.md#6. Requisitos Funcionais` | Interpolação de tabelas e estratégias (boost PID, overrun, two-step, VVT, flex) | 🟡 |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md#6. Requisitos Funcionais` | Web Audio da bancada | 🟡 |
| `_reversa_sdd/addenda/002-evolucao-comercial.md` | VVT, flex, upgrades, cenários de defeito, carreira, tela dividida | 🟡 |

## 3. Personas e cenários de uso

| Persona | Objetivo | Cenário-chave |
|---------|----------|---------------|
| Prof. Marcos | Rodar a turma no hardware de referência sem `worker.overrun` | 30 estações a 1000 Hz sem atraso |
| Lucas | Ouvir um motor agradável e realista | Blip no Espaço com pops graves, sem apito agudo do turbo |
| Rodrigo | Confiar em todos os fluxos | Swap, base setup, cenários de defeito e ordens da carreira sem erro |

## 4. Regras de negócio novas ou alteradas

1. **RN-01:** A extensão nativa é opcional. Sem ela, o comportamento é idêntico ao Python de referência. 🟡
2. **RN-02:** Com a extensão, os resultados de física, ECU e dano ficam dentro de tolerância numérica de 1e-9 relativa por tick (ou bit a bit quando a ordem das operações for a mesma). O determinismo por seed se mantém. 🟡
3. **RN-03:** Nenhum som estridente entre 1 kHz e 4 kHz domina o espectro em nenhum arquétipo. 🟡

## 5. Requisitos Funcionais

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-01 | Pacote nativo `simremap_rs` (PyO3 ABI3 ≥ 3.12, maturin) em `backend/rust/simremap_rs` | Must | `maturin develop --release` instala; `import simremap_rs` funciona | 🟡 |
| RF-02 | Kernels nativos de interpolação 1D/2D, lookup de eixo e estratégias da ECU (boost PID, VVT/overlap, overrun, two-step, flex) | Must | Testes de paridade Python × Rust em grades aleatórias | 🟡 |
| RF-03 | Kernels nativos do ciclo Otto (Wiebe, VE, entalpia de escape, EGT, rotor do turbo, compressor mecânico) | Must | Paridade de saída por tick; `-m accuracy` aprovado | 🟡 |
| RF-04 | Kernels nativos da integral de detonação e da acumulação de dano dos 6 modos | Must | Paridade com o modelo Python | 🟡 |
| RF-05 | Integração com fallback transparente (`SIMREMAP_NATIVE=auto|off|on`) | Must | Suíte completa aprovada com e sem a extensão | 🟡 |
| RF-06 | Latência do tick reduzida e sem `worker.overrun` a 1000 Hz | Must | Benchmark antes/depois registrado; tick nativo menor que o Python | 🟡 |
| RF-07 | Síntese por pulsos de combustão com WaveShaper, passa-baixa dinâmico 180→1400 Hz, ressonadores 90–140 e 280–450 Hz, sub-bass | Must | Teste do grafo de áudio e da curva de corte por rpm/carga | 🟡 |
| RF-08 | Turbo sem seno puro: ruído de banda estreita + harmônico discreto; flutter/chirp de alívio | Must | Nenhum `OscillatorNode` senoidal contínuo para o spool | 🟡 |
| RF-09 | Pops & bangs graves (punch 90–160 Hz + estalo filtrado + decay curto) | Must | Teste da cadeia do transiente | 🟡 |
| RF-10 | 4 arquétipos ajustados sem estridência em 1–4 kHz | Must | Ganho somado em 1–4 kHz abaixo do limite por arquétipo | 🟡 |
| RF-11 | Zero erros de `tsc` e `make type` (mypy --strict src tests) limpo | Must | Comandos com saída 0 | 🟢 |
| RF-12 | QA funcional de sessão livre, encerramento, retomada, Stage Builder e etanol | Must | Fluxos verificados e bugs corrigidos com teste | 🟡 |
| RF-13 | QA da bancada: baseline, sweep, steady-state, multi-pull, W/S/Espaço, tela dividida, visão térmica, autópsia e restauração | Must | Idem | 🟡 |
| RF-14 | QA do editor: 2D/3D, Q, H/V/B, salvar/aplicar, swap para FT-Pro/M1-Race/HT-Elite e Base Setup Wizard | Must | Idem | 🟡 |
| RF-15 | Os 7 cenários iniciam, rodam baseline e podem ser aprovados com um acerto real | Must | Teste por cenário com submissão aprovada | 🟡 |
| RF-16 | As 7 ordens da carreira podem ser aceitas, executadas e liquidadas com pagamento | Must | Teste por ordem | 🟡 |
| RF-17 | E2E Playwright dos fluxos novos (carreira, Stage Builder, defeitos, Live Tuning, áudio, motor nativo) | Must | Suíte Playwright aprovada | 🟡 |
| RF-18 | Build de produção sem erros e `frontend/dist` atualizado; mini-site e adendo 003 atualizados | Must | `npm run build` saída 0; `_reversa_docs/` cita a 003 | 🟢 |

## 6. Requisitos Não Funcionais

| Tipo | Requisito | Evidência ou justificativa | Confidência |
|------|-----------|----------------------------|-------------|
| Desempenho | Tick a 1000 Hz sem overrun no hardware de desenvolvimento; ganho medido | `prd.md#6` | 🟡 |
| Precisão | `-m accuracy` < 5 % com a extensão ligada e desligada | adendo 001 | 🟡 |
| Portabilidade | Imagem Docker funciona sem toolchain Rust (fallback) ou compila a extensão no estágio de build | `prd.md#6` | 🟡 |
| Qualidade | `make check` completo aprovado | `Makefile` | 🟢 |

## 7. Critérios de Aceitação

```gherkin
Cenário: Tick nativo
  Dado a extensão simremap_rs instalada
  Quando a sessão roda uma puxada a 1000 Hz
  Então não há evento worker.overrun e a telemetria é igual à do Python dentro da tolerância

Cenário: Sem extensão
  Dado SIMREMAP_NATIVE=off
  Quando a suíte de testes roda
  Então todos os testes passam com a implementação Python

Cenário: Turbo agradável
  Quando o turbo enche a 6000 rpm
  Então não há oscilador senoidal contínuo de spool e o espectro não tem pico estridente em 1–4 kHz

Cenário: Cenário de defeito aprovado
  Dado o cenário defect-lean-injector
  Quando o aluno diagnostica o cilindro 3 e corrige a calibração
  Então a submissão é aprovada
```

## 8. Prioridade MoSCoW

| Item | MoSCoW | Justificativa |
|------|--------|---------------|
| RF-01 a RF-06 | Must | Pedido explícito; desempenho |
| RF-07 a RF-10 | Must | Reclamação do usuário |
| RF-11 a RF-16 | Must | Qualidade |
| RF-17, RF-18 | Must | Entrega |

## 9. Esclarecimentos

> Modo autônomo "não parar": dúvidas viram premissas em `questions.md`.

## 10. Lacunas

- 🔴 [DÚVIDA] A imagem Docker deve compilar a extensão Rust ou usar só o fallback Python?
- 🔴 [DÚVIDA] Paridade numérica exigida: bit a bit ou tolerância relativa?

## 11. Histórico de alterações

| Data | Alteração | Autor |
|------|-----------|-------|
| 2026-10-19 | Versão inicial (modo autônomo) | reversa |
