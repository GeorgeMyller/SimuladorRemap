"""Execução e validação do AI Tuning (LAYA.ai) em todos os veículos do catálogo.

Avalia o impacto do ajuste autônomo nas tabelas de calibração em 3 configurações
(`safe`, `balanced`, `race`), mensurando ganhos de torque, potência, segurança de detonação
e tempo de execução em cada um dos 4 veículos.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from simremap.ai.contracts import AiTuneRequest
from simremap.ai.service import AiTuningService
from simremap.catalog.service import get_catalog
from simremap.ecu.calibration import validate_stock_calibration
from simremap.ecu.tables import Table2D, Table3D

SETUP_CANDIDATES = [
    "ve",
    "inj_base_ms",
    "lambda_target",
    "ignition_base",
    "oem_pressure_target",
    "boost_target",
    "torque_request",
    "torque_limit",
    "torque_limit_gear",
    "boost_target_gear",
]


def analyze_table_stats(table: Table3D) -> dict[str, Any]:
    """Calcula estatísticas de uma tabela 3D (min, max, média, amostras)."""
    vals = [v for row in table.values for v in row]
    assert table.y is not None
    return {
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "mean": round(float(sum(vals) / len(vals)), 2),
        "n_rows": len(table.y.values),
        "n_cols": len(table.x.values),
        "total_cells": len(vals),
        "sample_idle": round(table.values[2][1], 2),       # ~800-1000 RPM, 40 kPa
        "sample_cruise": round(table.values[4][5], 2),     # ~2500 RPM, 60-80 kPa
        "sample_peak_load": round(table.values[10][7], 2), # ~3500-4000 RPM, alta carga
        "sample_redline": round(table.values[14][14], 2),  # alta rotação, corte
    }


def evaluate_vehicle(
    catalog: Any,
    service: AiTuningService,
    vehicle_id: str,
    aggressiveness: str = "balanced",
) -> dict[str, Any]:
    """Executa o pipeline completo de AI Tuning coordenado em um veículo."""
    v = catalog.get_vehicle(vehicle_id)
    profile_id = getattr(v, "stock_profile_id", "oem-stage") or "oem-stage"
    stock_fuel = getattr(v, "stock_fuel_id", "e27")

    payload = catalog.get_factory_calibration_payload(vehicle_id, profile_id)
    cal = validate_stock_calibration(
        payload,
        vehicle_id=vehicle_id,
        profile_id=profile_id,
        created_at=datetime.now(UTC),
    )

    ve_before = analyze_table_stats(cal.tables["ve"]) if "ve" in cal.tables else None
    ign_before = (
        analyze_table_stats(cal.tables["ignition_base"])
        if "ignition_base" in cal.tables
        else None
    )

    # Estimativas baseline do motor
    baseline_torque_nm = 300.0
    baseline_power_hp = 220.0
    try:
        ref_curves = catalog.get_reference_curves(vehicle_id)
        if ref_curves and len(ref_curves) > 0:
            c0 = ref_curves[0]
            if getattr(c0, "torque_peak_nm", None):
                baseline_torque_nm = float(c0.torque_peak_nm)
            if getattr(c0, "power_peak_hp", None):
                baseline_power_hp = float(c0.power_peak_hp)
    except Exception:
        pass

    target_ids = [tid for tid in SETUP_CANDIDATES if tid in cal.tables]

    req = AiTuneRequest(
        target_table_ids=target_ids,
        aggressiveness=aggressiveness,
        max_fuel_step_pct=8.0,
        max_ign_advance_step_deg=2.0,
    )

    t0 = time.perf_counter()
    resp = service.tune_calibration(cal, req, fuel_id=stock_fuel)
    elapsed_s = round(time.perf_counter() - t0, 3)

    # Aplica alterações em cópia da calibração
    cal_tuned = validate_stock_calibration(
        payload,
        vehicle_id=vehicle_id,
        profile_id=profile_id,
        created_at=datetime.now(UTC),
    )

    by_table: dict[str, list[Any]] = {}
    for c in resp.corrections:
        by_table.setdefault(c.table_id, []).append(c)

    for tid, corrs in by_table.items():
        tbl = cal_tuned.tables.get(tid)
        if isinstance(tbl, Table3D):
            for c in corrs:
                tbl.values[c.row][c.col] = c.new_value
        elif isinstance(tbl, Table2D):
            for c in corrs:
                tbl.values[c.col] = c.new_value

    ve_after = analyze_table_stats(cal_tuned.tables["ve"]) if "ve" in cal_tuned.tables else None
    ign_after = (
        analyze_table_stats(cal_tuned.tables["ignition_base"])
        if "ignition_base" in cal_tuned.tables
        else None
    )

    tuned_torque_nm = round(
        baseline_torque_nm * (1.0 + resp.estimated_torque_gain_pct / 100.0), 1
    )
    tuned_power_hp = round(
        baseline_power_hp * (1.0 + resp.estimated_torque_gain_pct / 100.0), 1
    )

    table_mod_counts = {tid: len(corrs) for tid, corrs in by_table.items()}

    return {
        "vehicle_id": vehicle_id,
        "display_name": v.display_name,
        "induction": v.induction,
        "fuel_id": stock_fuel,
        "aggressiveness": aggressiveness,
        "engine_displacement_cc": getattr(v.engine, "displacement_cc", 2000),
        "max_rpm": v.mechanical_limits.max_rpm,
        "elapsed_seconds": elapsed_s,
        "corrections_summary": {
            "total_cells_modified": resp.total_cells_modified,
            "tables_modified": list(table_mod_counts.keys()),
            "cells_by_table": table_mod_counts,
            "safety_risk_flagged": resp.safety_risk,
            "risk_confidence": resp.risk_confidence,
            "estimated_torque_gain_pct": resp.estimated_torque_gain_pct,
        },
        "dyno_performance": {
            "baseline_torque_nm": baseline_torque_nm,
            "tuned_torque_nm": tuned_torque_nm,
            "torque_gain_nm": round(tuned_torque_nm - baseline_torque_nm, 1),
            "baseline_power_hp": baseline_power_hp,
            "tuned_power_hp": tuned_power_hp,
            "power_gain_hp": round(tuned_power_hp - baseline_power_hp, 1),
            "total_gain_pct": resp.estimated_torque_gain_pct,
        },
        "ve_comparison": {
            "before_mean": ve_before["mean"] if ve_before else None,
            "after_mean": ve_after["mean"] if ve_after else None,
            "delta_mean_pct": (
                round(((ve_after["mean"] - ve_before["mean"]) / ve_before["mean"]) * 100.0, 2)
                if ve_before and ve_after
                else 0.0
            ),
        },
        "ign_comparison": {
            "before_mean": ign_before["mean"] if ign_before else None,
            "after_mean": ign_after["mean"] if ign_after else None,
            "delta_mean_deg": (
                round(ign_after["mean"] - ign_before["mean"], 2)
                if ign_before and ign_after
                else 0.0
            ),
        },
    }


def run_benchmark():
    catalog = get_catalog()
    service = AiTuningService(catalog)

    eval_matrix = [
        ("hatch-20t-gdi", "safe"),
        ("hatch-20t-gdi", "balanced"),
        ("hatch-20t-gdi", "race"),
        ("coupe-30t-i6", "balanced"),
        ("muscle-v8-sc", "balanced"),
        ("classic-20t-swap", "balanced"),
    ]

    print("=" * 80)
    print("BENCHMARK E VALIDAÇÃO DE TUNING COM IA (LAYA.AI) EM TODOS OS VEÍCULOS")
    print("=" * 80)

    results = []
    current_vid = ""
    for vid, mode in eval_matrix:
        if vid != current_vid:
            print(f"\n[*] Veículo: {vid}", flush=True)
            current_vid = vid
        res = evaluate_vehicle(catalog, service, vid, aggressiveness=mode)
        results.append(res)
        p = res["dyno_performance"]
        c = res["corrections_summary"]
        print(
            f"    [{mode.upper():8s}] {res['elapsed_seconds']}s | "
            f"{c['total_cells_modified']} células em {len(c['tables_modified'])} tabelas | "
            f"Torque: {p['baseline_torque_nm']:.0f} -> {p['tuned_torque_nm']:.0f} Nm (+{p['total_gain_pct']}%) | "
            f"Knock: {'RISCO' if c['safety_risk_flagged'] else 'Zero'}",
            flush=True,
        )

    out_file = Path(__file__).resolve().parent.parent / "data" / "ai_tune_all_vehicles_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Resultados salvos em: {out_file}", flush=True)


if __name__ == "__main__":
    run_benchmark()
