"""Gerador de dados sintéticos para calibração autônoma com LAYA.ai, Sintetica e Hone.

Gera amostras de treino, validação e teste simulando os 3 perfis de configuração
(`safe`, `balanced`, `race`), zonas de carga (`idle`, `cruise`, `boost`),
variações de ponto de ignição, mistura (lambda), EGT e detonação nos veículos do catálogo.
Exporta tanto o formato legado (`data/synthetic_tuning_*.jsonl`) quanto a pasta estruturada
do motor de decisões do Hone (`data/hone_tuning_dataset/`).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Final

from simremap.catalog.service import get_catalog

FUEL_OPTIONS: Final[list[str]] = [
    "enrich_heavy",
    "enrich_light",
    "hold",
    "lean_light",
    "lean_heavy",
]
IGN_OPTIONS: Final[list[str]] = [
    "retard_critical",
    "retard_light",
    "hold",
    "advance_light",
    "advance_heavy",
]
AGGRESSIVENESS_LEVELS: Final[tuple[str, ...]] = ("safe", "balanced", "race")
ZONES: Final[tuple[str, ...]] = ("idle", "cruise", "boost")

TUNING_QUESTIONS_SPEC: Final[dict[str, dict[str, Any]]] = {
    "fuel_correction": {
        "type": "choice",
        "instructions": "Qual correção de combustível aplicar com base na sonda?",
        "criteria": FUEL_OPTIONS,
    },
    "ign_correction": {
        "type": "choice",
        "instructions": "Qual correção de ponto aplicar considerando MBT?",
        "criteria": IGN_OPTIONS,
    },
    "safety_risk": {
        "type": "noul",
        "instructions": "O motor está operando com risco de detonação ou sobreaquecimento?",
    },
}


def classify_fuel_action(delta_lambda: float) -> str:
    """Classifica a correção de combustível pelo desvio de lambda (medido - alvo)."""
    if delta_lambda >= 0.045:
        return "enrich_heavy"
    if delta_lambda >= 0.015:
        return "enrich_light"
    if delta_lambda <= -0.045:
        return "lean_heavy"
    if delta_lambda <= -0.015:
        return "lean_light"
    return "hold"


def classify_ign_action(
    delta_ign_deg: float,
    *,
    knock_detected: bool,
    knock_severe: bool,
    egt_over_limit: bool,
) -> str:
    """Classifica a correção de ignição pelo desvio para o alvo MBT e risco térmico/knock."""
    if knock_severe or egt_over_limit or (knock_detected and delta_ign_deg >= 2.2):
        return "retard_critical"
    if knock_detected or delta_ign_deg >= 1.0:
        return "retard_light"
    if delta_ign_deg <= -2.2:
        return "advance_heavy"
    if delta_ign_deg <= -0.8:
        return "advance_light"
    return "hold"


def _sample_operating_point(
    rng: random.Random,
    ref_pts: list[Any],
    zone: str,
    aggressiveness: str,
    fuel_id: str,
) -> tuple[float, float, float, float]:
    """Sorteia (rpm, map_kpa, target_lambda, optimal_ign_deg) coerentes com a zona e o modo."""
    ref_pt = rng.choice(ref_pts)
    if zone == "idle":
        rpm = float(rng.choice([750, 850, 900, 1000, 1100]))
        map_kpa = round(rng.uniform(28.0, 55.0), 1)
        target_lambda = 1.0
        optimal_ign = round(rng.uniform(18.0, 26.0), 1)
    elif zone == "cruise":
        rpm = float(rng.choice([1500, 1800, 2100, 2500, 2900, 3300]))
        map_kpa = round(rng.uniform(60.0, 102.0), 1)
        target_lambda = 0.96 if map_kpa > 85.0 else 1.0
        optimal_ign = round(rng.uniform(24.0, 34.0), 1)
    else:
        rpm = float(ref_pt.rpm)
        mode_map_add = {"safe": 8.0, "balanced": 20.0, "race": 34.0}[aggressiveness]
        map_kpa = round(ref_pt.map_target_kpa + mode_map_add + rng.uniform(-8.0, 8.0), 1)
        base_lam = float(ref_pt.lambda_target)
        if aggressiveness == "safe":
            target_lambda = round(min(base_lam, 0.84 if fuel_id != "e100" else 0.80), 3)
            optimal_ign = round(float(ref_pt.ignition_advance_deg) - 1.2, 1)
        elif aggressiveness == "balanced":
            target_lambda = round(min(base_lam, 0.82 if fuel_id != "e100" else 0.79), 3)
            optimal_ign = round(float(ref_pt.ignition_advance_deg) + 0.5, 1)
        else:
            target_lambda = round(min(base_lam, 0.80 if fuel_id != "e100" else 0.78), 3)
            optimal_ign = round(float(ref_pt.ignition_advance_deg) + 2.0, 1)
    return rpm, map_kpa, target_lambda, optimal_ign


def build_dataset(
    output_dir: Path,
    train_samples: int = 300,
    val_samples: int = 100,
    test_samples: int = 100,
    seed: int = 42,
) -> tuple[Path, Path]:
    """Gera datasets sintéticos rotulados para treino do LAYA.ai via Hone."""
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    hone_dir = output_dir / "hone_tuning_dataset"
    hone_dir.mkdir(parents=True, exist_ok=True)

    catalog = get_catalog()
    vehicles = catalog.list_vehicles()

    total_needed = train_samples + val_samples + test_samples
    legacy_records: list[dict[str, Any]] = []
    hone_records: list[dict[str, Any]] = []
    seen_states: set[str] = set()

    fuel_deltas = [
        (-0.14, -0.055),  # lean_heavy (muito rico -> empobrecer forte)
        (-0.042, -0.018), # lean_light (levemente rico -> empobrecer fino)
        (-0.012, 0.012),  # hold (na meta)
        (0.018, 0.042),   # enrich_light (levemente pobre -> enriquecer fino)
        (0.055, 0.14),    # enrich_heavy (muito pobre -> enriquecer forte)
    ]
    ign_deltas = [
        (-6.5, -2.5),     # advance_heavy (muito atrasado face ao alvo do modo)
        (-2.0, -0.9),     # advance_light (levemente atrasado)
        (-0.6, 0.7),      # hold (no ponto alvo do modo)
        (1.1, 2.1),       # retard_light (adiantado / início de knock)
        (2.5, 6.0),       # retard_critical (detonação severa)
    ]

    idx = 0
    while len(hone_records) < total_needed:
        veh_summary = vehicles[idx % len(vehicles)]
        veh_id = veh_summary.vehicle_id
        veh = catalog.get_vehicle(veh_id)
        fuel_id = rng.choice(veh.allowed_fuel_ids)
        aggressiveness = AGGRESSIVENESS_LEVELS[(idx // len(vehicles)) % len(AGGRESSIVENESS_LEVELS)]
        zone = ZONES[(idx // (len(vehicles) * len(AGGRESSIVENESS_LEVELS))) % len(ZONES)]

        schedule = catalog.get_reference_command_schedule(veh_id)
        rpm, map_kpa, target_lambda, optimal_ign = _sample_operating_point(
            rng,
            list(schedule.points),
            zone,
            aggressiveness,
            fuel_id,
        )

        f_lo, f_hi = fuel_deltas[idx % len(fuel_deltas)]
        i_lo, i_hi = ign_deltas[(idx // 5) % len(ign_deltas)]
        idx += 1

        raw_dl = rng.uniform(f_lo, f_hi)
        measured_lambda = round(max(0.62, min(1.28, target_lambda + raw_dl)), 3)
        delta_lambda = round(measured_lambda - target_lambda, 3)

        raw_di = rng.uniform(i_lo, i_hi)
        current_ign = round(optimal_ign + raw_di, 1)
        delta_ign = round(current_ign - optimal_ign, 1)

        base_egt = 620.0 + (rpm / 7500.0) * 160.0 + (map_kpa / 260.0) * 95.0
        egt_retard_penalty = max(0.0, -delta_ign) * 12.0
        egt_lean_penalty = max(0.0, delta_lambda) * 320.0
        egt_rich_cooling = min(0.0, delta_lambda) * 160.0
        egt_c = round(base_egt + egt_retard_penalty + egt_lean_penalty + egt_rich_cooling, 1)

        egt_max_c = float(veh.mechanical_limits.egt_max_c)
        egt_over_limit = egt_c >= egt_max_c

        knock_threshold = 1.4 if zone == "boost" else 2.0
        knock_detected = bool(delta_ign >= knock_threshold)
        knock_severe = bool(delta_ign >= (knock_threshold + 1.1))

        fuel_action = classify_fuel_action(delta_lambda)
        ign_action = classify_ign_action(
            delta_ign,
            knock_detected=knock_detected,
            knock_severe=knock_severe,
            egt_over_limit=egt_over_limit,
        )
        safety_risk = bool(
            knock_detected
            or egt_over_limit
            or delta_ign >= 2.0
            or (zone == "boost" and delta_lambda >= 0.055)
        )

        state_dict = {
            "vehicle_id": veh_id,
            "fuel_id": fuel_id,
            "aggressiveness": aggressiveness,
            "zone": zone,
            "rpm": round(rpm, 0),
            "map_kpa": round(map_kpa, 1),
            "measured_lambda": measured_lambda,
            "target_lambda": target_lambda,
            "delta_lambda": delta_lambda,
            "current_ign_deg": current_ign,
            "optimal_ign_deg": optimal_ign,
            "delta_ign_deg": delta_ign,
            "egt_c": egt_c,
            "knock": knock_detected,
        }
        state_str = json.dumps(state_dict, ensure_ascii=False)
        if state_str in seen_states:
            continue
        seen_states.add(state_str)

        group_id = f"{veh_id}:{aggressiveness}:{zone}:{len(hone_records) // 6}"
        hone_records.append(
            {
                "group": group_id,
                "state": state_str,
                "answers": {
                    "fuel_correction": fuel_action,
                    "ign_correction": ign_action,
                    "safety_risk": safety_risk,
                },
            }
        )

        legacy_records.append(
            {
                "state": state_str,
                "questions": {
                    "fuel_correction": {
                        **TUNING_QUESTIONS_SPEC["fuel_correction"],
                        "answer": fuel_action,
                    },
                    "ign_correction": {
                        **TUNING_QUESTIONS_SPEC["ign_correction"],
                        "answer": ign_action,
                    },
                    "safety_risk": {
                        **TUNING_QUESTIONS_SPEC["safety_risk"],
                        "answer": safety_risk,
                    },
                },
            }
        )

    train_hone = hone_records[:train_samples]
    val_hone = hone_records[train_samples : train_samples + val_samples]
    test_hone = hone_records[train_samples + val_samples :]

    task_payload = {
        "questions": TUNING_QUESTIONS_SPEC,
        "decide": "safety_risk",
        "policy": {"high": 0.5, "low": 0.5, "positive": "true"},
    }
    (hone_dir / "task.json").write_text(
        json.dumps(task_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for split_name, rows in (
        ("train.jsonl", train_hone),
        ("valid.jsonl", val_hone),
        ("test.jsonl", test_hone),
    ):
        with open(hone_dir / split_name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    train_path = output_dir / "synthetic_tuning_train.jsonl"
    val_path = output_dir / "synthetic_tuning_val.jsonl"
    with open(train_path, "w", encoding="utf-8") as f:
        for r in legacy_records[:train_samples]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(val_path, "w", encoding="utf-8") as f:
        for r in legacy_records[train_samples : train_samples + val_samples]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return train_path, val_path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data"
    tr, vl = build_dataset(out)
    print(f"Dataset sintético gerado com sucesso:\n- Treino: {tr}\n- Validação: {vl}")
