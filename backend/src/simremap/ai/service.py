"""Serviço de otimização de calibração via LAYA.ai."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, Final

import laya

from simremap.ai.contracts import AiTuneRequest, AiTuneResponse, CellCorrection
from simremap.catalog.service import CatalogService, get_catalog
from simremap.core.logging import get_logger
from simremap.ecu.calibration import Calibration
from simremap.ecu.contracts import TableKind
from simremap.ecu.limits import table_limit
from simremap.ecu.tables import Table2D, Table3D

log = get_logger("simremap.ai")

EPSILON: Final[float] = 1e-4
CHUNK_SIZE: Final[int] = 64
STEP_RATIO_LIGHT: Final[float] = 0.4
STEP_DEG_LIGHT: Final[float] = 0.5
STEP_DEG_HEAVY_RATIO: Final[float] = 1.5
MIN_EMERGENCY_RETARD: Final[float] = 3.0
DEFAULT_CONFIDENCE: Final[float] = 0.5
KNOCK_IGN_MARGIN: Final[float] = 1.5

RPM_IDLE_MAX: Final[float] = 1200.0
MAP_IDLE_MAX_KPA: Final[float] = 58.0
MAP_CRUISE_MAX_KPA: Final[float] = 105.0
MAP_CRUISE_RICH_KPA: Final[float] = 85.0
MAP_CRUISE_LOW_KPA: Final[float] = 80.0
MAP_BOOST_HIGH_KPA: Final[float] = 135.0
MAP_BOOST_SAFE_MAX_KPA: Final[float] = 180.0
LOAD_HIGH_PCT: Final[float] = 65.0
PEDAL_HIGH_PCT: Final[float] = 50.0

RPM_CRUISE_LOW: Final[float] = 1800.0
RPM_CRUISE_MID: Final[float] = 2000.0
RPM_BOOST_MID: Final[float] = 2200.0
RPM_BOOST_MIN: Final[float] = 2400.0
RPM_BOOST_SAFE_ADVANCE: Final[float] = 2800.0
RPM_BOOST_HIGH: Final[float] = 3500.0
RPM_HIGH_LOAD: Final[float] = 3800.0
RPM_REDLINE_START: Final[float] = 4000.0

EGT_BASE: Final[float] = 620.0
EGT_RPM_SCALE: Final[float] = 7500.0
EGT_RPM_FACTOR: Final[float] = 160.0
EGT_MAP_SCALE: Final[float] = 260.0
EGT_MAP_FACTOR: Final[float] = 95.0
EGT_RETARD_FACTOR: Final[float] = 12.0
EGT_LEAN_FACTOR: Final[float] = 320.0
EGT_RICH_FACTOR: Final[float] = 160.0

TABLE_ALIASES: Final[dict[str, str]] = {
    "inj.ve": "ve",
    "ign.base": "ignition_base",
    "ign.optimal": "ignition_optimal",
    "inj.lambda_target": "lambda_target",
}

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


class LayaModelHolder:
    """Gerenciador de ciclo de vida do agente LAYA em memória com cache de predição."""

    _instance: Any = None
    _cache: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def _find_data_path(cls, rel_name: str) -> Path:
        cand = (Path("data") / rel_name).resolve()
        if cand.exists():
            return cand
        root = Path(__file__).resolve().parents[4]
        return (root / "data" / rel_name).resolve()

    @classmethod
    def get_agent(cls) -> Any:
        """Obtém ou instancia o agente neural LAYA com checkpoint afinado se disponível."""
        if cls._instance is None:
            tuned_dir = cls._find_data_path("laya_ecu_tuned")
            if (tuned_dir / "rl_agent_config.json").exists() and (
                tuned_dir / "model.safetensors"
            ).exists():
                log.info("ai_tuning.loading_laya_tuned", path=str(tuned_dir))
                cls._instance = laya.load(str(tuned_dir), device="cpu")
            else:
                log.info("ai_tuning.loading_laya_base")
                cls._instance = laya.load(device="cpu")

            calib_file = cls._find_data_path("laya_tuning_calibration.json")
            if calib_file.exists():
                try:
                    log.info("ai_tuning.loading_calibration", path=str(calib_file))
                    cls._instance.load_calibration(str(calib_file))
                except Exception as exc:
                    log.warning("ai_tuning.load_calibration_failed", error=str(exc))
            log.info("ai_tuning.laya_ready", device=str(cls._instance.device))
        return cls._instance

    @classmethod
    def set_agent(cls, agent: Any) -> None:
        """Permite injeção de mock para testes unitários."""
        cls._instance = agent
        cls._cache.clear()

    @classmethod
    def predict_batch_cached(
        cls,
        agent: Any,
        states: list[str],
        questions: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Avalia estados reutilizando inferências cacheadas para ganho de performance."""
        results: list[dict[str, Any] | None] = [cls._cache.get(s) for s in states]
        missing_indices: list[int] = [i for i, r in enumerate(results) if r is None]

        if missing_indices:
            unique_missing = list(dict.fromkeys(states[i] for i in missing_indices))
            for i in range(0, len(unique_missing), CHUNK_SIZE):
                chunk_states = unique_missing[i : i + CHUNK_SIZE]
                chunk_preds = agent.predict_batch(chunk_states, questions)
                for s, p in zip(chunk_states, chunk_preds, strict=True):
                    cls._cache[s] = p

            for idx in missing_indices:
                results[idx] = cls._cache[states[idx]]

        return [r for r in results if r is not None]


def resolve_table_in_calibration(
    calibration: Calibration, target_id: str
) -> tuple[str, Table2D | Table3D] | None:
    """Resolve o ID ou alias da tabela para a instância concreta (2D ou 3D) na calibração."""
    table = calibration.tables.get(target_id)
    if isinstance(table, (Table2D, Table3D)):
        return target_id, table

    alias = TABLE_ALIASES.get(target_id)
    if alias:
        table = calibration.tables.get(alias)
        if isinstance(table, (Table2D, Table3D)):
            return alias, table

    for tid, cand in calibration.tables.items():
        if isinstance(cand, (Table2D, Table3D)):
            if target_id in (cand.kind, cand.kind.value):
                return tid, cand

    return None


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


def _resolve_aggressiveness_params(
    request: AiTuneRequest,
) -> tuple[float, float, float, float]:
    """Calcula limites de combustível, ignição, ganho base e margem de knock."""
    fuel_step = request.max_fuel_step_pct
    ign_step = request.max_ign_advance_step_deg

    if request.aggressiveness == "safe":
        return min(fuel_step, 6.0), min(ign_step, 1.2), 2.0, 2.2
    if request.aggressiveness == "race":
        return max(fuel_step, 12.0), max(ign_step, 3.0), 7.0, 1.0
    return fuel_step, ign_step, 3.5, KNOCK_IGN_MARGIN


class AiTuningService:
    """Serviço que orquestra a inferência do LAYA.ai sobre calibrações da ECU."""

    def __init__(self, catalog: CatalogService | None = None) -> None:
        self.catalog = catalog or get_catalog()

    def _get_factory_tables(
        self,
        vehicle_id: str,
        profile_id: str,
    ) -> dict[str, Any]:
        """Obtém tabelas originais de fábrica para uso como referencial físico."""
        try:
            payload = self.catalog.get_factory_calibration_payload(vehicle_id, profile_id)
            tables = payload.get("tables", {})
            return dict(tables) if isinstance(tables, dict) else {}
        except Exception:
            return {}

    def _determine_zone(self, rpm: float, map_kpa: float) -> str:
        """Determina a zona de operação do motor (idle, cruise, boost)."""
        if rpm <= RPM_IDLE_MAX or map_kpa <= MAP_IDLE_MAX_KPA:
            return "idle"
        if map_kpa <= MAP_CRUISE_MAX_KPA:
            return "cruise"
        return "boost"

    def _build_cell_states(  # noqa: PLR0912, PLR0915
        self,
        table: Table3D,
        veh_id: str,
        fuel_id: str,
        aggressiveness: str,
        *,
        is_ve: bool,
        is_ign: bool,
        factory_tables: dict[str, Any],
        knock_margin: float = KNOCK_IGN_MARGIN,
    ) -> tuple[list[str], list[tuple[int, int, float]]]:
        """Gera estados JSON serializados com coerência física para predição neural."""
        states: list[str] = []
        coords: list[tuple[int, int, float]] = []

        factory_ve_dict = factory_tables.get("ve", {})
        factory_ve_vals = factory_ve_dict.get("values")
        factory_ign_dict = factory_tables.get("ignition_base", {})
        factory_ign_vals = factory_ign_dict.get("values")
        factory_lam_dict = factory_tables.get("lambda_target", {})
        factory_lam_vals = factory_lam_dict.get("values")

        for r_idx, map_kpa in enumerate(table.y.values):
            for c_idx, rpm in enumerate(table.x.values):
                current_val = table.values[r_idx][c_idx]
                zone = self._determine_zone(rpm, map_kpa)

                base_lam = 1.0
                if factory_lam_vals and r_idx < len(factory_lam_vals):
                    row = factory_lam_vals[r_idx]
                    if c_idx < len(row):
                        base_lam = float(row[c_idx])

                if zone == "idle":
                    target_lambda = 1.0
                elif zone == "cruise":
                    target_lambda = round(0.96 if map_kpa > MAP_CRUISE_RICH_KPA else base_lam, 3)
                else:
                    is_ethanol = fuel_id == "e100"
                    if aggressiveness == "safe":
                        target_lambda = round(min(base_lam, 0.80 if is_ethanol else 0.84), 3)
                    elif aggressiveness == "race":
                        target_lambda = round(min(base_lam, 0.78 if is_ethanol else 0.80), 3)
                    else:
                        target_lambda = round(min(base_lam, 0.79 if is_ethanol else 0.82), 3)

                base_ve = current_val
                if factory_ve_vals and r_idx < len(factory_ve_vals):
                    row = factory_ve_vals[r_idx]
                    if c_idx < len(row):
                        base_ve = float(row[c_idx])

                if zone == "boost":
                    target_ve = (
                        base_ve * 1.032
                        if aggressiveness == "safe"
                        else base_ve * 1.09
                        if aggressiveness == "race"
                        else base_ve * 1.055
                    )
                else:
                    target_ve = base_ve

                if is_ve:
                    ratio = current_val / max(10.0, target_ve)
                    measured_lambda = round(
                        max(0.62, min(1.28, target_lambda / max(0.4, ratio))), 3
                    )
                    delta_lambda = round(measured_lambda - target_lambda, 3)
                else:
                    measured_lambda = target_lambda
                    delta_lambda = 0.0

                base_ign = 18.0
                if factory_ign_vals and r_idx < len(factory_ign_vals):
                    row = factory_ign_vals[r_idx]
                    if c_idx < len(row):
                        base_ign = float(row[c_idx])

                if zone == "idle":
                    optimal_ign = base_ign
                elif zone == "cruise":
                    ign_offset = 0.0
                    if (
                        aggressiveness == "race"
                        and rpm >= RPM_CRUISE_LOW
                        and map_kpa >= MAP_CRUISE_LOW_KPA
                    ):
                        ign_offset = 1.6
                    elif rpm >= RPM_CRUISE_MID and map_kpa >= MAP_CRUISE_RICH_KPA:
                        ign_offset = 1.2
                    optimal_ign = base_ign + ign_offset
                else:
                    if aggressiveness == "safe":
                        ign_offset = (
                            1.1
                            if rpm >= RPM_BOOST_SAFE_ADVANCE and map_kpa <= MAP_BOOST_SAFE_MAX_KPA
                            else -0.5
                        )
                    elif aggressiveness == "race":
                        ign_offset = 3.2 if rpm >= RPM_CRUISE_MID else 1.8
                    else:
                        ign_offset = (
                            2.4
                            if rpm >= RPM_BOOST_HIGH
                            else 1.4
                            if rpm >= RPM_BOOST_MID
                            else 0.5
                        )
                    optimal_ign = base_ign + ign_offset

                if is_ign:
                    current_ign = current_val
                else:
                    current_ign = optimal_ign

                delta_ign = round(current_ign - optimal_ign, 1)

                base_egt = (
                    EGT_BASE
                    + (rpm / EGT_RPM_SCALE) * EGT_RPM_FACTOR
                    + (map_kpa / EGT_MAP_SCALE) * EGT_MAP_FACTOR
                )
                egt_retard_penalty = max(0.0, -delta_ign) * EGT_RETARD_FACTOR
                egt_lean_penalty = max(0.0, delta_lambda) * EGT_LEAN_FACTOR
                egt_rich_cooling = min(0.0, delta_lambda) * EGT_RICH_FACTOR
                egt_c = round(
                    base_egt + egt_retard_penalty + egt_lean_penalty + egt_rich_cooling, 1
                )

                knock_risk = bool(is_ign and current_ign > (optimal_ign + knock_margin))

                state = json.dumps(
                    {
                        "vehicle_id": veh_id,
                        "fuel_id": fuel_id,
                        "aggressiveness": aggressiveness,
                        "zone": zone,
                        "rpm": round(rpm, 0),
                        "map_kpa": round(map_kpa, 1),
                        "measured_lambda": measured_lambda,
                        "target_lambda": target_lambda,
                        "delta_lambda": delta_lambda,
                        "current_ign_deg": round(current_ign, 1),
                        "optimal_ign_deg": round(optimal_ign, 1),
                        "delta_ign_deg": delta_ign,
                        "egt_c": egt_c,
                        "knock": knock_risk,
                    },
                    ensure_ascii=False,
                )
                states.append(state)
                coords.append((r_idx, c_idx, current_val))

        return states, coords

    def _tune_ve_table(
        self,
        table_id: str,
        table: Table3D,
        coords: list[tuple[int, int, float]],
        batch_results: list[dict[str, Any]],
        fuel_step: float,
    ) -> list[CellCorrection]:
        """Aplica correções na tabela VE a partir do head fuel_correction do LAYA."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)

        for (r_idx, c_idx, current_val), res in zip(coords, batch_results, strict=True):
            answers = res.get("answers", {})
            fuel_ans = answers.get("fuel_correction", {})
            action = str(fuel_ans.get("choice", "hold"))
            conf = float(fuel_ans.get("answer_confidence", DEFAULT_CONFIDENCE))
            new_val, expl = apply_ve_correction(current_val, action, fuel_step)

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
        return corrections

    def _tune_ign_table(
        self,
        table_id: str,
        table: Table3D,
        coords: list[tuple[int, int, float]],
        batch_results: list[dict[str, Any]],
        ign_step: float,
    ) -> list[CellCorrection]:
        """Aplica correções na tabela de ignição a partir do head ign_correction do LAYA."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)

        for (r_idx, c_idx, current_val), res in zip(coords, batch_results, strict=True):
            answers = res.get("answers", {})
            ign_ans = answers.get("ign_correction", {})
            action = str(ign_ans.get("choice", "hold"))
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
        return corrections

    def _tune_lambda_target(
        self,
        table_id: str,
        table: Table3D,
        fuel_id: str,
        aggressiveness: str,
    ) -> list[CellCorrection]:
        """Ajusta lambda alvo em plena carga para casamento de mistura estequiométrica/potência."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)
        is_ethanol = fuel_id == "e100"

        for r_idx, map_kpa in enumerate(table.y.values):
            if map_kpa < MAP_BOOST_HIGH_KPA:
                continue
            for c_idx, rpm in enumerate(table.x.values):
                if rpm < RPM_BOOST_MIN:
                    continue
                current_val = table.values[r_idx][c_idx]
                if aggressiveness == "safe":
                    ceiling = 0.81 if is_ethanol else 0.84
                elif aggressiveness == "race":
                    ceiling = 0.77 if is_ethanol else 0.80 if rpm >= RPM_HIGH_LOAD else 0.82
                else:
                    ceiling = 0.79 if is_ethanol else 0.80 if rpm >= RPM_REDLINE_START else 0.86

                new_val = min(current_val, ceiling)
                new_val = max(lim.min, min(lim.max, new_val))
                new_val = round(new_val, 3)

                if abs(new_val - current_val) > EPSILON:
                    corrections.append(
                        CellCorrection(
                            table_id=table_id,
                            row=r_idx,
                            col=c_idx,
                            old_value=current_val,
                            new_value=new_val,
                            action="enrich_coordinated",
                            confidence=0.92,
                            explanation=f"Ajuste térmico em alta carga ({new_val:.3f}λ)",
                        )
                    )
        return corrections

    def _tune_pressure_target(
        self,
        table_id: str,
        table: Table3D,
        aggressiveness: str,
    ) -> list[CellCorrection]:
        """Eleva a pressão alvo de sobrealimentação (oem_pressure_target ou boost_target)."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)
        scale = 1.06 if aggressiveness == "safe" else 1.18 if aggressiveness == "race" else 1.12

        for r_idx, y_val in enumerate(table.y.values):
            if y_val < LOAD_HIGH_PCT:
                continue
            for c_idx, rpm in enumerate(table.x.values):
                if rpm < RPM_BOOST_MID:
                    continue
                current_val = table.values[r_idx][c_idx]
                new_val = round(current_val * scale, 1)
                new_val = max(lim.min, min(lim.max, new_val))

                if abs(new_val - current_val) > EPSILON:
                    corrections.append(
                        CellCorrection(
                            table_id=table_id,
                            row=r_idx,
                            col=c_idx,
                            old_value=current_val,
                            new_value=new_val,
                            action="boost_scale",
                            confidence=0.90,
                            explanation=f"Aumento de boost (+{round((scale - 1.0) * 100)}%)",
                        )
                    )
        return corrections

    def _tune_torque_request(
        self,
        table_id: str,
        table: Table3D,
        aggressiveness: str,
    ) -> list[CellCorrection]:
        """Aumenta o mapa de torque solicitado pelo pedal (torque_request)."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)
        scale = 1.10 if aggressiveness == "safe" else 1.28 if aggressiveness == "race" else 1.20

        for r_idx, pedal_pct in enumerate(table.y.values):
            if pedal_pct < PEDAL_HIGH_PCT:
                continue
            for c_idx, rpm in enumerate(table.x.values):
                if rpm < RPM_CRUISE_LOW:
                    continue
                current_val = table.values[r_idx][c_idx]
                new_val = round(current_val * scale, 1)
                new_val = max(lim.min, min(lim.max, new_val))

                if abs(new_val - current_val) > EPSILON:
                    corrections.append(
                        CellCorrection(
                            table_id=table_id,
                            row=r_idx,
                            col=c_idx,
                            old_value=current_val,
                            new_value=new_val,
                            action="torque_request_scale",
                            confidence=0.91,
                            explanation=f"Aumento de torque ({round((scale - 1.0) * 100)}%)",
                        )
                    )
        return corrections

    def _tune_2d_limit(
        self,
        table_id: str,
        table: Table2D,
        aggressiveness: str,
    ) -> list[CellCorrection]:
        """Ajusta limitadores 2D coordenados."""
        corrections: list[CellCorrection] = []
        lim = table_limit(table.kind)
        scale = 1.08 if aggressiveness == "safe" else 1.22 if aggressiveness == "race" else 1.15

        for c_idx, _x_val in enumerate(table.x.values):
            current_val = table.values[c_idx]
            new_val = round(current_val * scale, 1)
            new_val = max(lim.min, min(lim.max, new_val))

            if abs(new_val - current_val) > EPSILON:
                corrections.append(
                    CellCorrection(
                        table_id=table_id,
                        row=0,
                        col=c_idx,
                        old_value=current_val,
                        new_value=new_val,
                        action="limit_raise",
                        confidence=0.89,
                        explanation=f"Aumento de teto permissivo ({round(new_val, 1)} {lim.unit})",
                    )
                )
        return corrections

    def tune_calibration(  # noqa: PLR0912, PLR0915
        self,
        calibration: Calibration,
        request: AiTuneRequest,
        fuel_id: str = "e100",
    ) -> AiTuneResponse:
        """Executa a otimização assistida nas tabelas solicitadas."""
        agent = LayaModelHolder.get_agent()
        veh_id = calibration.vehicle_id
        profile_id = calibration.profile_id
        factory_tables = self._get_factory_tables(veh_id, profile_id)

        corrections: list[CellCorrection] = []
        fuel_step, ign_step, base_gain, knock_margin = _resolve_aggressiveness_params(request)

        safety_risk_detected = False
        risk_confidences: list[float] = []
        coordinated_boost_tuned = False

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

            if isinstance(table, Table3D) and (is_ve or is_ign):
                states, coords = self._build_cell_states(
                    table,
                    veh_id,
                    fuel_id,
                    request.aggressiveness,
                    is_ve=is_ve,
                    is_ign=is_ign,
                    factory_tables=factory_tables,
                    knock_margin=knock_margin,
                )
                batch_results = LayaModelHolder.predict_batch_cached(
                    agent, states, TUNING_QUESTIONS
                )

                for res in batch_results:
                    risk_info = res.get("answers", {}).get("safety_risk", {})
                    choice = str(risk_info.get("choice", "no")).lower()
                    if choice in ("yes", "true", "1"):
                        safety_risk_detected = True
                        risk_confidences.append(float(risk_info.get("answer_confidence", 0.95)))

                if is_ve:
                    corrs = self._tune_ve_table(
                        table_id, table, coords, batch_results, fuel_step
                    )
                else:
                    corrs = self._tune_ign_table(
                        table_id, table, coords, batch_results, ign_step
                    )
                corrections.extend(corrs)

            elif isinstance(table, Table3D) and (
                table.kind == TableKind.LAMBDA_TARGET or "lambda" in table_id.lower()
            ):
                corrs = self._tune_lambda_target(
                    table_id, table, fuel_id, request.aggressiveness
                )
                corrections.extend(corrs)

            elif isinstance(table, Table3D) and (
                table.kind in (TableKind.OEM_PRESSURE_TARGET, TableKind.BOOST_TARGET)
                or "pressure" in table_id.lower()
                or "boost_target" in table_id.lower()
            ):
                corrs = self._tune_pressure_target(table_id, table, request.aggressiveness)
                corrections.extend(corrs)
                if corrs:
                    coordinated_boost_tuned = True

            elif isinstance(table, Table3D) and (
                table.kind == TableKind.TORQUE_REQUEST or "torque_request" in table_id.lower()
            ):
                corrs = self._tune_torque_request(table_id, table, request.aggressiveness)
                corrections.extend(corrs)

            elif isinstance(table, Table2D) and (
                table.kind
                in (
                    TableKind.TORQUE_LIMIT,
                    TableKind.TORQUE_LIMIT_GEAR,
                    TableKind.BOOST_TARGET_GEAR,
                )
                or "limit" in table_id.lower()
            ):
                corrs = self._tune_2d_limit(table_id, table, request.aggressiveness)
                corrections.extend(corrs)

        total_mod = len(corrections)
        summary = (
            f"Otimização concluída: {total_mod} células ajustadas em "
            f"{len(request.target_table_ids)} tabelas com perfil {request.aggressiveness}."
        )

        final_risk_conf = (
            round(sum(risk_confidences) / len(risk_confidences), 2)
            if risk_confidences
            else 0.95
        )

        if total_mod == 0:
            final_gain_pct = 0.0
        elif coordinated_boost_tuned:
            extra = (
                3.5
                if request.aggressiveness == "safe"
                else 9.5
                if request.aggressiveness == "race"
                else 6.0
            )
            final_gain_pct = round(base_gain + extra, 1)
        else:
            final_gain_pct = base_gain

        return AiTuneResponse(
            corrections=corrections,
            total_cells_modified=total_mod,
            summary=summary,
            safety_risk=safety_risk_detected,
            risk_confidence=final_risk_conf,
            estimated_torque_gain_pct=final_gain_pct,
        )
