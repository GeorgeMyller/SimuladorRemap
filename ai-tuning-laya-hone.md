# Otimização Real do AI Tuning com LAYA.ai, Sintetica e Hone (MLX)

## Goal
Corrigir o motor de AI Tuning (`LAYA.ai`) para diferenciar fisicamente os 3 modos (`safe`, `balanced`, `race`), otimizar o setup completo da calibração e treinar um modelo real com dados sintéticos validados e fine-tuning MLX via Hone.

## Tasks
- [x] Task 1: Gerar dataset sintético estruturado para os 3 setups (`safe`, `balanced`, `race`) usando a física/catálogo do simulador e auditoria de qualidade do Sintetica (`data/hone_tuning_dataset/`) → Verify: `task.json`, `train.jsonl`, `valid.jsonl` e `test.jsonl` validados por `hone data check`.
- [x] Task 2: Executar fine-tuning real do `convaiinnovations/laya` com Hone (MLX LoRA + cabeças + calibração de temperatura) e exportar checkpoint fundido (`data/laya_ecu_tuned/`) → Verify: acurácia no conjunto de teste > 90% e `model.safetensors` + `rl_agent_config.json` exportados.
- [x] Task 3: Redesenhar `simremap.ai.service` (`AiTuningService` e `LayaModelHolder`) para carregar o modelo treinado pelo Hone, construir estados fiéis à física com `aggressiveness`, e otimizar o setup coordenado (`ve`, `inj_base_ms`, `lambda_target`, `ignition_base`, `oem_pressure_target`, `boost_target`, `torque_request`, `torque_limit`, `torque_limit_gear`) → Verify: respostas distintas e fisicamente coerentes para `safe`, `balanced` e `race`.
- [x] Task 4: Atualizar `frontend/src/features/ecu-tuning/TableEditorCore.tsx` e `workspaceStore.ts` para acionar o setup coordenado completo ao clicar em "🤖 Tunar com IA" → Verify: `npm test` passa sem erros.
- [x] Task 5: Atualizar `scripts/hone_tuning_model.py`, `scripts/generate_synthetic_tuning_data.py` e `scripts/evaluate_all_vehicles_ai_tune.py`, rodar testes (`pytest`, `mypy`, `ruff`) e benchmark nos 4 veículos nas 3 configurações → Verify: todos os testes e linters passam com >90% de cobertura.

## Done When
- [x] Modelo LAYA treinado via Hone (MLX) com acurácia > 90% nas 3 perguntas (`fuel_correction`, `ign_correction`, `safety_risk`).
- [x] Os 3 modos (`safe`, `balanced`, `race`) produzem calibrações distintas, seguras e com ganho progressivo real em todos os 4 veículos.
- [x] Suíte de testes backend (`pytest`) e frontend (`vitest`) 100% verde.
