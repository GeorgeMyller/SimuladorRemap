"""Script de treino real (MLX LoRA + Cabeças + Calibração) do LAYA.ai via Hone.

Executa o pipeline completo do motor de decisões do Hone no Apple Silicon (MLX):
1. Valida o dataset em `data/hone_tuning_dataset/` (`hone data check`).
2. Treina LoRA (`Wqkv`, `Wo`, `Wi`) e cabeças (`type_emb`, `head`, `scorer`) com `hone train`.
3. Calibra temperaturas por faixa (`choice:3-5`, `noul:2`) e avalia no conjunto `test`.
4. Exporta o checkpoint fundido para `data/laya_ecu_tuned/` (`hone export`) para carga direta pelo `laya.load()`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

HONE_BIN = Path("/Volumes/SSD-EXTERNO/hone/.venv/bin/hone")


def _extract_metrics(section: dict[str, Any]) -> dict[str, float]:
    """Extrai acurácias por pergunta do relatório do Hone."""
    qs = section.get("questions", {})
    fuel_acc = float(qs.get("fuel_correction", {}).get("accuracy", 0.0))
    ign_acc = float(qs.get("ign_correction", {}).get("accuracy", 0.0))
    risk_acc = float(qs.get("safety_risk", {}).get("accuracy", 0.0))
    overall = round((fuel_acc + ign_acc + risk_acc) / 3.0, 4)
    return {
        "fuel_accuracy": round(fuel_acc, 4),
        "ign_accuracy": round(ign_acc, 4),
        "risk_accuracy": round(risk_acc, 4),
        "overall_accuracy": overall,
    }


def hone_model(
    data_dir: Path,
    run_dir: Path,
    export_dir: Path,
    output_calib: Path,
    *,
    epochs: int = 4,
    batch: int = 16,
    lr: float = 2.5e-4,
) -> dict[str, Any]:
    """Executa o pipeline de fine-tuning MLX e exportação do LAYA via Hone."""
    print("=" * 72)
    print("INICIANDO FINE-TUNING REAL (MLX LoRA) DO LAYA.AI VIA HONE")
    print("=" * 72)
    t0 = time.perf_counter()

    if run_dir.exists():
        shutil.rmtree(run_dir)
    if export_dir.exists():
        shutil.rmtree(export_dir)

    cmd_check = [
        str(HONE_BIN),
        "data",
        "check",
        "--data",
        str(data_dir),
        "--model",
        "convaiinnovations/laya",
    ]
    subprocess.run(cmd_check, check=True)  # noqa: S603

    cmd_train = [
        str(HONE_BIN),
        "train",
        "--data",
        str(data_dir),
        "--model",
        "convaiinnovations/laya",
        "--out",
        str(run_dir),
        "--epochs",
        str(epochs),
        "--batch",
        str(batch),
        "--lr",
        str(lr),
        "--baseline",
    ]
    subprocess.run(cmd_train, check=True)  # noqa: S603

    cmd_export = [
        str(HONE_BIN),
        "export",
        "--run",
        str(run_dir),
        "--out",
        str(export_dir),
    ]
    subprocess.run(cmd_export, check=True)  # noqa: S603

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    metrics_before = _extract_metrics(report.get("baseline", {}))
    metrics_after = _extract_metrics(report.get("test", {}))

    agent_cfg = json.loads((export_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
    cal_info = report.get("calibration") or {}
    calib_payload = {
        "version": 2,
        "temperature": cal_info.get("temperature", agent_cfg.get("temperature", [1.0, 1.0, 1.0])),
        "temperature_by_options": cal_info.get(
            "temperature_by_options",
            agent_cfg.get("temperature_by_options", {}),
        ),
        "model_id_or_path": str(export_dir),
        "subfolder": None,
        "config": agent_cfg,
    }
    output_calib.write_text(
        json.dumps(calib_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total_time = round(time.perf_counter() - t0, 2)
    examples = report.get("examples", {})
    train_n = int(examples.get("train", {}).get("states", 0))
    val_n = int(examples.get("valid", {}).get("states", 0))
    test_n = int(examples.get("test", {}).get("states", 0))

    print("\n--- RESUMO PÓS-TREINO HONE (MLX) ---")
    print(f"    Baseline -> Global: {metrics_before['overall_accuracy'] * 100:.2f}%")
    print(f"    Pós-Hone -> Combustível: {metrics_after['fuel_accuracy'] * 100:.2f}%")
    print(f"    Pós-Hone -> Ignição:     {metrics_after['ign_accuracy'] * 100:.2f}%")
    print(f"    Pós-Hone -> Risco/Knock: {metrics_after['risk_accuracy'] * 100:.2f}%")
    print(f"    Pós-Hone -> Global:      {metrics_after['overall_accuracy'] * 100:.2f}%")
    print(f"    Checkpoint exportado:    {export_dir}")

    return {
        "engine": "hone-mlx-decision",
        "samples_total": train_n + val_n + test_n,
        "train_samples": train_n,
        "val_samples": val_n,
        "test_samples": test_n,
        "device": "mlx-applegpu",
        "epochs": epochs,
        "trainable_parameters": report.get("trainable_parameters"),
        "peak_memory_gb": report.get("peak_memory_gb"),
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "temperatures": calib_payload["temperature"],
        "temperature_by_options": calib_payload["temperature_by_options"],
        "total_time_s": total_time,
        "exported_model_path": str(export_dir),
        "calibration_path": str(output_calib),
    }


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    d_dir = base_dir / "data" / "hone_tuning_dataset"
    r_dir = base_dir / "data" / "hone_laya_run"
    e_dir = base_dir / "data" / "laya_ecu_tuned"
    c_path = base_dir / "data" / "laya_tuning_calibration.json"

    res = hone_model(d_dir, r_dir, e_dir, c_path)
    summary_path = base_dir / "data" / "honing_training_summary.json"
    summary_path.write_text(
        json.dumps(res, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[+] Resumo da calibração salvo em: {summary_path}")
