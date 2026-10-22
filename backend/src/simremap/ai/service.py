"""Serviço de otimização de calibração via LAYA.ai."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import laya

from simremap.ai.contracts import AiTuneRequest, AiTuneResponse, CellCorrection
from simremap.catalog.service import CatalogService, get_catalog
from simremap.core.logging import get_logger
from simremap.ecu.calibration import Calibration
from simremap.ecu.contracts import TableKind
from simremap.ecu.limits import table_limit
from simremap.ecu.tables import Table3D

log = get_logger("simremap.ai")

EPSILON: Final[float] = 1e-4
MAP_BOOST_KPA: Final[float] = 105.0
MAP_CRUISE_KPA: Final[float] = 80.0
LAMBDA_POWER: Final[float] = 0.82
LAMBDA_CRUISE: Final[float] = 0.90
LAMBDA_STOICH: Final[float] = 1.0
BASE_IGNITION: Final[float] = 18.0
MAX_RPM_NORM: Final[float] = 7500.0
MAX_MAP_NORM: Final[float] = 250.0
IGN_RPM_FACTOR: Final[float] = 12.0
IGN_MAP_FACTOR: Final[float] = 14.0
EGT_BASE: Final[float] = 750.0
EGT_FACTOR: Final[float] = 120.0
BASE_VE_REF: Final[float] = 85.0
MIN_VE_RATIO: Final[float] = 0.5
KNOCK_IGN_MARGIN: Final[float] = 1.5
CHUNK_SIZE: Final[int] = 64
STEP_RATIO_LIGHT: Final[float] = 0.4
STEP_DEG_LIGHT: Final[float] = 0.5
STEP_DEG_HEAVY_RATIO: Final[float] = 1.5
MIN_EMERGENCY_RETARD: Final[float] = 3.0
DEFAULT_CONFIDENCE: Final[float] = 0.5
ESTIMATED_GAIN_PCT: Final[float] = 3.5

TABLE_ALIASES: Final[dict[str, str]] = {
    "inj.ve": "ve",
    "ign.base": "ignition_base",
    "ign.optimal": "ignition_optimal",
    "inj.lambda_target": "lambda_target",
}


class LayaModelHolder:
    """Gerenciador de ciclo de vida do agente LAYA em memória."""

    _instance: Any = None

    @classmethod
    def get_agent(cls) -> Any:
        """Obtém ou instancia o agente neural LAYA."""
        if cls._instance is None:
            log.info("ai_tuning.loading_laya")
            cls._instance = laya.load()
            calib_file = Path("data/laya_tuning_calibration.json")
            if not calib_file.exists():
                root = Path(__file__).resolve().parents[4]
                calib_file = root / "data" / "laya_tuning_calibration.json"
            if calib_file.exists():
                log.info("ai_tuning.loading_calibration", path=str(calib_file))
                cls._instance.load_calibration(str(calib_file))
            log.info("ai_tuning.laya_ready", device=str(cls._instance.device))
        return cls._instance

    @classmethod
    def set_agent(cls, agent: Any) -> None:
        """Permite injeção de mock para testes."""
        cls._instance = agent


def resolve_table_in_calibration(
    calibration: Calibration, target_id: str
) -> tuple[str, Table3D] | None:
    """Resolve o ID ou alias da tabela para a instância concreta Table3D na calibração."""
    table = calibration.tables.get(target_id)
    if isinstance(table, Table3D):
        return target_id, table

    alias = TABLE_ALIASES.get(target_id)
    if alias:
        table = calibration.tables.get(alias)
        if isinstance(table, Table3D):
            return alias, table

    for tid, cand in calibration.tables.items():
        if isinstance(cand, Table3D):
            if target_id in (cand.kind, cand.kind.value):
                return tid, cand

    return None


def calculate_target_references(
    rpm: float,
    map_kpa: float,
    schedule: Any | None,
) -> tuple[float, float]:
    """Calcula lambda alvo e ponto de ignição de referência para uma célula."""
    if map_kpa > MAP_BOOST_KPA:
        target_lambda = LAMBDA_POWER
    elif map_kpa > MAP_CRUISE_KPA:
        target_lambda = LAMBDA_CRUISE
    else:
        target_lambda = LAMBDA_STOICH

    optimal_ign = (
        BASE_IGNITION
        + (rpm / MAX_RPM_NORM) * IGN_RPM_FACTOR
        - (map_kpa / MAX_MAP_NORM) * IGN_MAP_FACTOR
    )

    if schedule is not None and len(schedule.points) > 0:
        closest = min(schedule.points, key=lambda p: abs(p.rpm - rpm))
        target_lambda = closest.lambda_target
        optimal_ign = closest.ignition_advance_deg

    return target_lambda, optimal_ign


def apply_ve_correction(
    current_val: float,
    action: str,
    step_pct: float,
) -> tuple[float, str]:
    """Aplica regra de enriquecimento ou empobrecimento em uma célula de VE."""
    new_val = current_val
    explanation = "Sem alteração"

    if action == "enrich_heavy":
        new_val = current_val * (1.0 + step_pct / 100.0)
        explanation = f"Enriquecimento de {step_pct:.1f}% para atingir lambda alvo"
    elif action == "enrich_light":
        new_val = current_val * (1.0 + (step_pct * STEP_RATIO_LIGHT) / 100.0)
        explanation = "Enriquecimento fino de mistura"
    elif action == "lean_light":
        new_val = current_val * (1.0 - (step_pct * STEP_RATIO_LIGHT) / 100.0)
        explanation = "Empobrecimento fino para reduzir excesso de combustível"
    elif action == "lean_heavy":
        new_val = current_val * (1.0 - step_pct / 100.0)
        explanation = f"Empobrecimento de {step_pct:.1f}% para evitar saturação"

    return new_val, explanation


def apply_ign_correction(
    current_val: float,
    action: str,
    step_deg: float,
) -> tuple[float, str]:
    """Aplica regra de avanço ou atraso em uma célula de ignição."""
    new_val = current_val
    explanation = "Sem alteração"

    if action == "retard_critical":
        new_val = current_val - max(MIN_EMERGENCY_RETARD, step_deg * STEP_DEG_HEAVY_RATIO)
        explanation = "Atraso emergencial para eliminar risco de detonação"
    elif action == "retard_light":
        new_val = current_val - step_deg * STEP_DEG_LIGHT
        explanation = "Atraso preventivo de segurança"
    elif action == "advance_light":
        new_val = current_val + step_deg * STEP_DEG_LIGHT
        explanation = "Avanço de ignição para aproximar do MBT"
    elif action == "advance_heavy":
        new_val = current_val + step_deg
        explanation = f"Avanço de {step_deg:.1f}° buscando ganho de torque"

    return new_val, explanation


TUNING_QUESTIONS: Final[dict[str, Any]] = {
    "fuel_correction": {
        "type": "choice",
        "instructions": "Qual correção de combustível aplicar com base na sonda?",
        "criteria": ["enrich_heavy", "enrich_light", "hold", "lean_light", "lean_heavy"],
    },
    "ign_correction": {
        "type": "choice",
        "instructions": "Qual correção de ponto aplicar considerando MBT?",
        "criteria": [
            "retard_critical",
            "retard_light",
            "hold",
            "advance_light",
            "advance_heavy",
        ],
    },
    "safety_risk": {
        "type": "noul",
        "instructions": "O motor está operando com risco de detonação ou sobreaquecimento?",
    },
}


def _resolve_aggressiveness_params(
    request: AiTuneRequest,
) -> tuple[float, float, float, float]:
    """Calcula limites de combustível, ignição, ganho estimado e margem de knock."""
    fuel_step = request.max_fuel_step_pct
    ign_step = request.max_ign_advance_step_deg

    if request.aggressiveness == "safe":
        return min(fuel_step, 6.0), min(ign_step, 1.2), 2.0, 2.2
    if request.aggressiveness == "race":
        return max(fuel_step, 12.0), max(ign_step, 3.0), 7.0, 1.0
    return fuel_step, ign_step, ESTIMATED_GAIN_PCT, KNOCK_IGN_MARGIN


class AiTuningService:
    """Serviço que orquestra a inferência do LAYA.ai sobre calibrações da ECU."""

    def __init__(self, catalog: CatalogService | None = None) -> None:
        self.catalog = catalog or get_catalog()

    def _build_cell_states(
        self,
        table: Table3D,
        veh_id: str,
        fuel_id: str,
        *,
        is_ve: bool,
        is_ign: bool,
        schedule: Any | None,
        knock_margin: float = KNOCK_IGN_MARGIN,
    ) -> tuple[list[str], list[tuple[int, int, float]]]:
        """Gera estados JSON serializados para inferência do modelo."""
        states: list[str] = []
        coords: list[tuple[int, int, float]] = []

        for r_idx, map_kpa in enumerate(table.y.values):
            for c_idx, rpm in enumerate(table.x.values):
                current_val = table.values[r_idx][c_idx]
                target_lambda, optimal_ign = calculate_target_references(rpm, map_kpa, schedule)

                if is_ve:
                    ratio = current_val / BASE_VE_REF
                    measured_lambda = round(target_lambda / max(ratio, MIN_VE_RATIO), 3)
                    current_ign = optimal_ign
                else:
                    measured_lambda = target_lambda
                    current_ign = current_val

                egt_c = EGT_BASE + (rpm / MAX_RPM_NORM) * EGT_FACTOR
                knock_risk = is_ign and current_ign > (optimal_ign + knock_margin)

                state = json.dumps(
                    {
                        "vehicle_id": veh_id,
                        "fuel_id": fuel_id,
                        "rpm": rpm,
                        "map_kpa": round(map_kpa, 1),
                        "measured_lambda": measured_lambda,
                        "target_lambda": target_lambda,
                        "current_ign_deg": round(current_ign, 1),
                        "egt_c": round(egt_c, 1),
                        "knock": knock_risk,
                    },
                    ensure_ascii=False,
                )
                states.append(state)
                coords.append((r_idx, c_idx, current_val))

        return states, coords

    def tune_calibration(
        self,
        calibration: Calibration,
        request: AiTuneRequest,
        fuel_id: str = "e100",
    ) -> AiTuneResponse:
        """Executa a otimização assistida nas tabelas solicitadas."""
        agent = LayaModelHolder.get_agent()
        veh_id = calibration.vehicle_id
        schedule = None
        try:
            schedule = self.catalog.get_reference_command_schedule(veh_id)
        except Exception as e:
            log.warning("ai_tuning.no_reference_schedule", vehicle_id=veh_id, error=str(e))

        corrections: list[CellCorrection] = []
        fuel_step, ign_step, est_gain, knock_margin = _resolve_aggressiveness_params(request)

        for raw_id in request.target_table_ids:
            resolved = resolve_table_in_calibration(calibration, raw_id)
            if resolved is None:
                continue
            table_id, table = resolved

            is_ve = table.kind == TableKind.VE or "ve" in table_id.lower()
            is_ign = (
                table.kind
                in (
                    TableKind.IGNITION_BASE,
                    TableKind.IGNITION_OPTIMAL,
                )
                or "ign" in table_id.lower()
            )

            if not is_ve and not is_ign:
                continue

            states, coords = self._build_cell_states(
                table,
                veh_id,
                fuel_id,
                is_ve=is_ve,
                is_ign=is_ign,
                schedule=schedule,
                knock_margin=knock_margin,
            )
            lim = table_limit(table.kind)

            batch_results = []
            for i in range(0, len(states), CHUNK_SIZE):
                chunk_states = states[i : i + CHUNK_SIZE]
                chunk_res = agent.predict_batch(chunk_states, TUNING_QUESTIONS)
                batch_results.extend(chunk_res)

            for (r_idx, c_idx, current_val), res in zip(coords, batch_results, strict=True):
                answers = res.get("answers", {})

                if is_ve:
                    fuel_ans = answers.get("fuel_correction", {})
                    action = fuel_ans.get("choice", "hold")
                    conf = float(fuel_ans.get("answer_confidence", DEFAULT_CONFIDENCE))
                    new_val, expl = apply_ve_correction(current_val, action, fuel_step)
                else:
                    ign_ans = answers.get("ign_correction", {})
                    action = ign_ans.get("choice", "hold")
                    conf = float(ign_ans.get("answer_confidence", DEFAULT_CONFIDENCE))
                    new_val, expl = apply_ign_correction(current_val, action, ign_step)

                new_val = max(lim.min, min(lim.max, new_val))
                new_val = round(new_val, 1)

                if abs(new_val - current_val) > EPSILON:
                    corrections.append(
                        CellCorrection(
                            table_id=table_id,
                            row=r_idx,
                            col=c_idx,
                            old_value=current_val,
                            new_value=new_val,
                            action=action,
                            confidence=conf,
                            explanation=expl,
                        )
                    )

        total_mod = len(corrections)
        summary = (
            f"Otimização concluída: {total_mod} células ajustadas em "
            f"{len(request.target_table_ids)} tabelas com perfil {request.aggressiveness}."
        )

        return AiTuneResponse(
            corrections=corrections,
            total_cells_modified=total_mod,
            summary=summary,
            safety_risk=False,
            risk_confidence=0.95,
            estimated_torque_gain_pct=est_gain if total_mod > 0 else 0.0,
        )
