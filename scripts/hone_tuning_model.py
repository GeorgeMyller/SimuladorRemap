"""Script de treino e calibração (Honing) do LAYA.ai com dados sintéticos.

Processa 1.000 amostras sintéticas de telemetria automotiva,
extrai logits do modelo neural e ajusta as temperaturas de calibração
(ECE e strictly proper scoring rules) para otimização de calibração ECU.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import laya
import laya.calibrate as calib
import numpy as np


def load_dataset_pairs(file_path: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Lê registros JSONL e formata pares (state, questions, targets)."""
    pairs = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            state = item["state"]
            qs = item["questions"]

            # Vetor one-hot de combustível (choice: 5)
            fuel_crit = qs["fuel_correction"]["criteria"]
            fuel_ans = qs["fuel_correction"]["answer"]
            fuel_vec = [1.0 if opt == fuel_ans else 0.0 for opt in fuel_crit]

            # Vetor one-hot de ignição (choice: 5)
            ign_crit = qs["ign_correction"]["criteria"]
            ign_ans = qs["ign_correction"]["answer"]
            ign_vec = [1.0 if opt == ign_ans else 0.0 for opt in ign_crit]

            # Vetor one-hot de risco de quebra (noul: [não, sim])
            risk_ans = qs["safety_risk"]["answer"]
            risk_vec = [0.0, 1.0] if risk_ans else [1.0, 0.0]

            targets = {
                "fuel_correction": fuel_vec,
                "ign_correction": ign_vec,
                "safety_risk": risk_vec,
            }

            clean_qs = {
                k: {qk: qv for qk, qv in v.items() if qk != "answer"}
                for k, v in qs.items()
            }
            pairs.append((state, clean_qs, targets))
    return pairs


def evaluate_accuracy(agent: Any, pairs: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, float]:
    """Calcula a acurácia de predição do modelo sobre as perguntas."""
    correct_fuel = 0
    correct_ign = 0
    correct_risk = 0
    total = len(pairs)

    states = [p[0] for p in pairs]
    qs = pairs[0][1]

    # Batch prediction
    chunk_size = 64
    all_res = []
    for i in range(0, total, chunk_size):
        chunk_states = states[i : i + chunk_size]
        res = agent.predict_batch(chunk_states, qs)
        all_res.extend(res)

    for (_, _, targets), res in zip(pairs, all_res, strict=True):
        ans = res.get("answers", {})

        # Combustível
        pred_fuel = ans.get("fuel_correction", {}).get("choice")
        target_fuel_idx = int(np.argmax(targets["fuel_correction"]))
        target_fuel = qs["fuel_correction"]["criteria"][target_fuel_idx]
        if pred_fuel == target_fuel:
            correct_fuel += 1

        # Ignição
        pred_ign = ans.get("ign_correction", {}).get("choice")
        target_ign_idx = int(np.argmax(targets["ign_correction"]))
        target_ign = qs["ign_correction"]["criteria"][target_ign_idx]
        if pred_ign == target_ign:
            correct_ign += 1

        # Risco de segurança
        target_risk = bool(targets["safety_risk"][1] > 0.5)
        # Noul retorna act_probability ou choice
        risk_choice = ans.get("safety_risk", {}).get("choice")
        pred_risk = risk_choice in ("yes", "true", True) or ans.get("safety_risk", {}).get("confidence", 0) > 0.5
        if pred_risk == target_risk:
            correct_risk += 1

    return {
        "fuel_accuracy": correct_fuel / total,
        "ign_accuracy": correct_ign / total,
        "risk_accuracy": correct_risk / total,
        "overall_accuracy": (correct_fuel + correct_ign + correct_risk) / (total * 3),
    }


def hone_model(
    train_file: Path,
    val_file: Path,
    output_calib: Path,
) -> dict[str, Any]:
    """Executa o pipeline de treino/calibração com métricas antes e depois."""
    print("=" * 70)
    print("INICIANDO CALIBRAÇÃO E TREINO (HONING) DO LAYA.AI COM DADOS SINTÉTICOS")
    print("=" * 70)

    t0 = time.perf_counter()
    agent = laya.load()
    device = getattr(agent, "device", "cpu")
    print(f"[*] Modelo LAYA carregado com sucesso (dispositivo: {device})")

    print(f"[*] Carregando dados sintéticos:\n    Treino: {train_file}\n    Validação: {val_file}")
    train_pairs = load_dataset_pairs(train_file)
    val_pairs = load_dataset_pairs(val_file)
    total_samples = len(train_pairs) + len(val_pairs)
    print(f"[*] Total de amostras carregadas: {total_samples} (800 treino / 200 validação)")

    # 1. Avaliação Baseline (Antes do Hone)
    print("\n--- AVALIAÇÃO BASELINE (PRÉ-CALIBRAÇÃO) ---")
    metrics_before = evaluate_accuracy(agent, val_pairs)
    print(f"    Acurácia Combustível (VE): {metrics_before['fuel_accuracy'] * 100:.2f}%")
    print(f"    Acurácia Ponto de Ignição: {metrics_before['ign_accuracy'] * 100:.2f}%")
    print(f"    Detecção Risco / Knock:    {metrics_before['risk_accuracy'] * 100:.2f}%")
    print(f"    Acurácia Média Global:     {metrics_before['overall_accuracy'] * 100:.2f}%")

    # 2. Coleta de Logits do Modelo
    print("\n[*] Coletando logits e alvos supervisionados (forward passes)...")
    t_fwd = time.perf_counter()
    train_records = calib.records_from_labeled(agent, train_pairs)
    fwd_time = time.perf_counter() - t_fwd
    print(f"    {len(train_records)} registros rotulados gerados em {fwd_time:.2f}s "
          f"({fwd_time / len(train_records) * 1000:.2f}ms/registro)")

    # 3. Ajuste de Temperaturas (Hone)
    print("\n[*] Otimizando temperaturas e curvas de calibração de probabilidade (Hone)...")
    t_fit = time.perf_counter()
    fit_res = agent.fit_temperatures(train_records, compute_ece=True, seed=42)
    fit_time = time.perf_counter() - t_fit

    temp_scalars = fit_res.get("temperature", [])
    print(f"    Otimização concluída em {fit_time:.3f}s")
    print(f"    Escalares de temperatura ajustados: {temp_scalars}")
    if "report" in fit_res:
        rep = fit_res["report"]
        print(f"    Amostras avaliadas no ECE: {rep.get('n', 0)}")

    # 4. Avaliação Pós-Hone
    print("\n--- AVALIAÇÃO PÓS-TREINO / CALIBRAÇÃO (PÓS-HONING) ---")
    metrics_after = evaluate_accuracy(agent, val_pairs)
    print(f"    Acurácia Combustível (VE): {metrics_after['fuel_accuracy'] * 100:.2f}%")
    print(f"    Acurácia Ponto de Ignição: {metrics_after['ign_accuracy'] * 100:.2f}%")
    print(f"    Detecção Risco / Knock:    {metrics_after['risk_accuracy'] * 100:.2f}%")
    print(f"    Acurácia Média Global:     {metrics_after['overall_accuracy'] * 100:.2f}%")

    # 5. Salva perfil calibrado
    output_calib.parent.mkdir(parents=True, exist_ok=True)
    agent.save_calibration(str(output_calib))
    print(f"\n[+] Perfil de calibração neural salvo com sucesso em: {output_calib}")

    total_time = time.perf_counter() - t0
    print(f"[+] Processo concluído em {total_time:.2f}s!")

    return {
        "samples_total": total_samples,
        "train_samples": len(train_pairs),
        "val_samples": len(val_pairs),
        "device": str(device),
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "temperatures": temp_scalars,
        "total_time_s": round(total_time, 2),
        "calibration_path": str(output_calib),
    }


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    tr_path = base_dir / "data" / "synthetic_tuning_train.jsonl"
    vl_path = base_dir / "data" / "synthetic_tuning_val.jsonl"
    out_calib = base_dir / "data" / "laya_tuning_calibration.json"

    res = hone_model(tr_path, vl_path, out_calib)
    summary_path = base_dir / "data" / "honing_training_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"[+] Resumo da calibração salvo em: {summary_path}")
