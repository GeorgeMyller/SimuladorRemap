# Regression Watch: 002-evolucao-comercial

> Feature com âncora greenfield: watch principal vazio (nenhuma regra 🟢 extraída de código). Os requisitos implementados ficam em "Observações", sem peso de regressão, até uma futura extração `/reversa` confirmá-los como 🟢.

| ID | Origem (arquivo, seção) | Regra esperada após mudança | Tipo de verificação | Sinal de violação |
|----|--------------------------|-----------------------------|---------------------|-------------------|
| — | — | — | — | — |

## Observações

| ID | Origem | Regra esperada | Tipo | Sinal de violação |
|----|--------|----------------|------|-------------------|
| W298 | `requirements.md#RF-01`, `scenarios/attempts.py` | Tentativa de cenário builtin com `vehicle_stock` nunca retorna 422 de hash | presença | 422 `SCENARIO_CALIBRATION_HASH_MISMATCH` num builtin |
| W299 | `requirements.md#RN-02` | Cenário importado com hash divergente retorna 422 | presença | Tentativa criada com hash divergente num não builtin |
| W300 | `requirements.md#RF-02`, `scenarios/catalog.py` | Hash do builtin calculado pela rota do clone | presença | `stock.content_hash` usado direto no `load_builtin` |
| W301 | `requirements.md#RF-03`, `ecu/router.py` | PUT, revert e PATCH em `stock-*` → 409 `CALIBRATION_STOCK_IMMUTABLE` | presença | Versão nova criada numa `stock-*` pela API |
| W302 | `requirements.md#RF-04`, `dyno/session.py` | Sessão sem `calibration_id` aponta para clone do usuário | presença | `session.calibration_id` começa por `stock-` em sessão nova |
| W303 | `roadmap.md#D-05`, `physics/fuel.py` | `overlap = base + vvt_in − vvt_ex`, efeito zero no cronograma de série | redação | Sinal de `vvt_ex` invertido ou efeito ≠ 0 na série |
| W304 | `requirements.md#RNF Precisão` | Desvio < 5 % contra `Reference Benchmark Baseline v1` sem upgrades | presença | `pytest -m accuracy` reprovado |
| W305 | `requirements.md#RF-11`, `ecu/strategies/vvt.py` | Alvos de came 0 com ECT abaixo do mínimo | presença | Came atuado com motor frio |
| W306 | `profiles/contracts.py` | Descritor com 10 kinds, `vvt` incluso | presença | Validador volta a exigir 9 kinds |
| W307 | `requirements.md#RF-13..17`, `catalog/upgrades.py` | Peças: turbo ×1,25 área / ×1,30 choke / ×1,45 inércia; bicos ×1,5; bomba 1,8; intercooler +0,08; downpipe 0,6; forjados ×1,35/×1,25/+40 °C | redação | Coeficientes alterados sem nova feature |
| W308 | `requirements.md#RN-05` | Peça incompatível → 422 `UPGRADE_NOT_COMPATIBLE` | presença | Turbo upgraded aceito no V8 |
| W309 | `requirements.md#RN-06`, `physics/fuel_blend.py` | Etanol 27–100 %, só em veículo com e27 e e100 (409 `FUEL_NOT_ALLOWED`) | presença | E15 aceito ou flex em veículo sem e100 |
| W310 | `requirements.md#RF-18` | AFR estequiométrico do blend entre E27 e E100, monotônico | presença | AFR fora do intervalo |
| W311 | `requirements.md#RF-23`, `scenarios/catalog.py` | 7 cenários builtin carregados | presença | Contagem ≠ 7 |
| W312 | `requirements.md#RF-24`, `defect-fuel-pump.json` | Bomba fraca (84 L/h): λ na janela < 5.000 rpm e pobre > 5.500 rpm | presença | `test_fuel_pump_lean_only_above_5500_rpm` reprovado |
| W313 | `requirements.md#RN-07`, `career/service.py` | Pagamento só com tentativa aprovada; quebra debita custo do motor; liquidação idempotente | presença | Crédito em tentativa reprovada ou dupla liquidação |
| W314 | `requirements.md#RN-04`, `ecu-tuning/ops/quickTune.ts` | Quick Tune `VE × λm/λt`, limite ±25 %, só tabela VE | redação | Correção fora do limite ou aplicada em outra tabela |
| W315 | `requirements.md#RF-06`, `live-tuning/liveCell.ts` | Célula ativa pisca pelo frame WS; estática com `prefers-reduced-motion` | presença | Destaque ausente ou animado com movimento reduzido |
| W316 | `requirements.md#RF-21`, `render/thermal.ts` | Gradiente 650 °C vermelho → 815 °C laranja → 980 °C amarelo | redação | Cores fora da escala |
| W317 | `requirements.md#RF-22`, `useHoldThrottle.ts` | Espaço sobe 120 %/s; soltar → 0 % em ≤ 150 ms | presença | Pedal não volta a 0 ao soltar |
| W318 | `requirements.md#RF-27`, `vite.config.ts` | Nenhum chunk JS > 500 kB sem subir `chunkSizeWarningLimit` | presença | Aviso de chunk grande no build |
| W319 | `dyno/session.py` (`_close`) | Fecho de sessão idempotente (abandono durante a baseline responde 200) | presença | 500 `KeyError` no abandono |

## Histórico de re-extrações

> Vazio. Preenchido pelo `/reversa` na próxima re-extração.

## Arquivadas

> Vazio.
