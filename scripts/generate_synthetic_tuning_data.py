"""Gerador de dados sintéticos para calibração autônoma com LAYA.ai.

Gera amostras de treino e validação simulando variações de ponto de ignição,
mistura ar-combustível (lambda), temperatura e rotação nos veículos do catálogo.
Saída: arquivos JSONL em `data/synthetic_tuning_train.jsonl` e `data/synthetic_tuning_val.jsonl`.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from simremap.catalog.service import get_catalog


def build_dataset(
    output_dir: Path,
    train_samples: int = 800,
    val_samples: int = 200,
    seed: int = 42,
) -> tuple[Path, Path]:
    """Gera datasets sintéticos rotulados para treino do LAYA.ai."""
    random.seed(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = get_catalog()
    vehicles = catalog.list_vehicles()

    records: list[dict] = []

    fuel_options = ["enrich_heavy", "enrich_light", "hold", "lean_light", "lean_heavy"]
    ign_options = ["retard_critical", "retard_light", "hold", "advance_light", "advance_heavy"]

    for _ in range(train_samples + val_samples):
        veh_summary = random.choice(vehicles)
        veh_id = veh_summary.vehicle_id
        veh = catalog.get_vehicle(veh_id)

        fuel_id = random.choice(veh.allowed_fuel_ids)
        fuel_spec = catalog.get_fuel(fuel_id)

        try:
            schedule = catalog.get_reference_command_schedule(veh_id)
            ref_pts = schedule.points
        except Exception:
            continue

        ref_pt = random.choice(ref_pts)
        rpm = ref_pt.rpm
        target_map = ref_pt.map_target_kpa
        optimal_ign = ref_pt.ignition_advance_deg
        optimal_lambda = ref_pt.lambda_target

        # Variações e perturbações propositais
        delta_lambda = random.choice([
            random.uniform(-0.15, -0.05),  # muito rico
            random.uniform(-0.04, -0.02),  # levemente rico
            random.uniform(-0.015, 0.015), # ideal (hold)
            random.uniform(0.02, 0.04),    # levemente pobre
            random.uniform(0.05, 0.15),    # muito pobre
        ])
        measured_lambda = round(max(0.60, min(1.30, optimal_lambda + delta_lambda)), 3)

        delta_ign = random.choice([
            random.uniform(-8.0, -3.5),   # muito atrasado
            random.uniform(-3.0, -1.2),   # levemente atrasado
            random.uniform(-0.8, 0.8),    # ponto MBT ideal (hold)
            random.uniform(1.2, 2.5),     # levemente adiantado (início de detonação)
            random.uniform(2.8, 6.0),     # muito adiantado (detonação severa)
        ])
        current_ign = round(optimal_ign + delta_ign, 1)

        # Simulação de EGT e Knock baseada nos desvios
        base_egt = 700.0 + (rpm / 7500.0) * 180.0
        # Ponto atrasado aumenta EGT
        egt_retard_penalty = max(0.0, -delta_ign) * 15.0
        # Mistura pobre aumenta EGT
        egt_lean_penalty = max(0.0, delta_lambda) * 350.0
        # Mistura rica resfria EGT
        egt_rich_cooling = min(0.0, delta_lambda) * 200.0

        egt_c = round(base_egt + egt_retard_penalty + egt_lean_penalty + egt_rich_cooling, 1)

        # Sensibilidade a detonação (RON mais alto reduz knock)
        octane_margin = (fuel_spec.ron - 95.0) * 0.5
        knock_threshold = 1.5 + octane_margin
        knock_detected = bool(delta_ign >= knock_threshold)
        knock_severity = "severe" if delta_ign >= (knock_threshold + 2.0) else ("light" if knock_detected else "none")

        # Classificação da ação ideal de combustível
        if delta_lambda > 0.04:
            fuel_action = "enrich_heavy"
        elif delta_lambda > 0.015:
            fuel_action = "enrich_light"
        elif delta_lambda < -0.04:
            fuel_action = "lean_heavy"
        elif delta_lambda < -0.015:
            fuel_action = "lean_light"
        else:
            fuel_action = "hold"

        # Classificação da ação ideal de ignição
        if knock_severity == "severe" or egt_c >= veh.mechanical_limits.egt_max_c:
            ign_action = "retard_critical"
        elif knock_severity == "light":
            ign_action = "retard_light"
        elif delta_ign < -3.0:
            ign_action = "advance_heavy"
        elif delta_ign < -1.0:
            ign_action = "advance_light"
        else:
            ign_action = "hold"

        # Risco de quebra mecânica
        safety_risk = bool(knock_detected or egt_c > veh.mechanical_limits.egt_max_c or current_ign > (optimal_ign + 3.0))

        # Estado textual compacto
        state_dict = {
            "vehicle_id": veh_id,
            "fuel_id": fuel_id,
            "rpm": rpm,
            "map_kpa": round(target_map, 1),
            "measured_lambda": measured_lambda,
            "target_lambda": optimal_lambda,
            "current_ign_deg": current_ign,
            "egt_c": egt_c,
            "knock": knock_detected,
        }

        records.append({
            "state": json.dumps(state_dict, ensure_ascii=False),
            "questions": {
                "fuel_correction": {
                    "type": "choice",
                    "instructions": "Qual correção de combustível aplicar com base na sonda medida e alvo?",
                    "criteria": fuel_options,
                    "answer": fuel_action,
                },
                "ign_correction": {
                    "type": "choice",
                    "instructions": "Qual correção de ponto de ignição aplicar considerando MBT e detonação?",
                    "criteria": ign_options,
                    "answer": ign_action,
                },
                "safety_risk": {
                    "type": "noul",
                    "instructions": "O motor está operando com risco de detonação ou sobreaquecimento?",
                    "answer": safety_risk,
                },
            },
        })

    random.shuffle(records)
    train_data = records[:train_samples]
    val_data = records[train_samples:]

    train_path = output_dir / "synthetic_tuning_train.jsonl"
    val_path = output_dir / "synthetic_tuning_val.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for r in train_data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for r in val_data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return train_path, val_path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data"
    tr, vl = build_dataset(out)
    print(f"Dataset sintético gerado com sucesso:\n- Treino: {tr}\n- Validação: {vl}")
