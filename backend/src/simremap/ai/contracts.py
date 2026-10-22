"""Contratos Pydantic do assistente de calibração autônomo (LAYA.ai)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from simremap.core.contracts import ContractModel

AggressivenessLevel = Literal["safe", "balanced", "race"]


class AiTuneRequest(ContractModel):
    """Requisição de otimização autônoma de calibração."""

    target_table_ids: list[str] = Field(
        default_factory=lambda: ["ve", "ignition_base"],
        description="IDs das tabelas a otimizar",
    )
    aggressiveness: AggressivenessLevel = Field(
        default="safe",
        description="Nível de agressividade: safe, balanced ou race (potência máxima)",
    )
    max_fuel_step_pct: float = Field(
        default=10.0,
        ge=1.0,
        le=25.0,
        description="Limite percentual de correção por aplicação na VE",
    )
    max_ign_advance_step_deg: float = Field(
        default=2.0,
        ge=0.5,
        le=5.0,
        description="Limite máximo de avanço de ignição em graus por aplicação",
    )


class CellCorrection(ContractModel):
    """Correção proposta para uma célula específica."""

    table_id: str
    row: int
    col: int
    old_value: float
    new_value: float
    action: str
    confidence: float
    explanation: str


class AiTuneResponse(ContractModel):
    """Resposta com as correções sugeridas e avaliação de segurança."""

    corrections: list[CellCorrection]
    total_cells_modified: int
    summary: str
    safety_risk: bool
    risk_confidence: float
    estimated_torque_gain_pct: float
