# Regression Watch: 003-rust-audio-qa-total

> Âncora greenfield: watch principal vazio. Observações sem peso de regressão.

| ID | Origem (arquivo, seção) | Regra esperada após mudança | Tipo de verificação | Sinal de violação |
|----|--------------------------|-----------------------------|---------------------|-------------------|
| — | — | — | — | — |

## Observações

| ID | Origem | Regra esperada | Tipo | Sinal de violação |
|----|--------|----------------|------|-------------------|
| W320 | `core/native.py` | `SIMREMAP_NATIVE=off` usa só Python; `on` falha sem a extensão | presença | Nativo usado com `off` |
| W321 | `tests/native/*` | Paridade Python × Rust bit a bit (tolerância máx. rel 1e-9) | presença | Teste de paridade reprovado |
| W322 | `requirements.md#RNF Precisão` | `-m accuracy` < 5 % com nativo ligado e desligado | presença | Accuracy reprovado em um dos modos |
| W323 | `physics/turbo.py`, `cycle/gas.rs` | Linha de surge `0,30·ṁ_choke·√min(N/N_design,1)`, sem surge abaixo de PR 1,05 | redação | Surge a plena carga na série > 2 % |
| W324 | `ecu/runtime.py` | dTPS/dt pela mediana de 3 amostras | presença | AE > 5 % em plena carga estável |
| W325 | `ecu/runtime.py` | BOV abre com borboleta < 5 % e pré-borboleta > MAP + 10 kPa | presença | `surge_s` > 1 s no coastdown |
| W326 | `ecu/apply.py` | 1.º aplicar compara com `initial_calibration_version` | presença | `changed_tables` vazio com tabela alterada |
| W327 | `dyno/contracts.py` | `active_calibration_id` reflete aplicar/swap/base setup | presença | Workspace carrega a calibração inicial após swap |
| W328 | `dyno/session.py` | Seeds sorteadas ≤ 2^53−1 | presença | Seed > 2^53 sem pedido do cliente |
| W329 | `core/worker/loop.py` | Overrun conta acima de `dt × wall_budget_ticks` | redação | `worker.overrun` no arrefecimento do multi_pull |
| W330 | `scenarios/attempts.py` | Tentativa liquidada antes de expor a avaliação; quebra registrada antes do fecho | presença | 409 `SIM_CAPACITY_EXCEEDED` após submissão; carreira não cobra motor |
| W331 | `catalog/.../hatch-20t-gdi/calibrations/oem-stage.json` | PID de boost kp 0,1 / ki 0,3 / kd 0 | redação | Oscilação de 7,5 Hz > ±5 N·m no hatch de série |
| W332 | `audio/*` | Sem `OscillatorNode` contínuo no spool; energia 1–4 kHz < 5 %; corte 180→1400 Hz | presença | Seno contínuo de turbo ou pico em 1–4 kHz |
| W333 | `tests/qa/test_scenarios_approvable.py`, `test_career_orders.py` | 7 cenários aprováveis e 7 ordens pagáveis | presença | Cenário ou ordem sem aprovação possível |
| W334 | `Makefile#type` | `mypy --strict src tests` limpo | presença | Erro de tipo ou módulo duplicado |

## Histórico de re-extrações

> Vazio.

## Arquivadas

> Vazio.
