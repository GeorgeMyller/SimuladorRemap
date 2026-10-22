"""Testes do endpoint de otimização de calibração via IA (LAYA.ai)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from simremap.ai.service import LayaModelHolder


class DummyLayaAgent:
    """Mock determinístico do agente neural LAYA para testes de API."""

    def __init__(self) -> None:
        self.device = "mock-cpu"

    def predict_batch(
        self,
        states: list[str],
        questions: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results = []
        for _ in states:
            results.append(
                {
                    "answers": {
                        "fuel_correction": {
                            "choice": "enrich_light",
                            "answer_confidence": 0.88,
                        },
                        "ign_correction": {
                            "choice": "advance_light",
                            "answer_confidence": 0.92,
                        },
                        "safety_risk": {
                            "choice": "no",
                            "answer_confidence": 0.96,
                        },
                    }
                }
            )
        return results


@pytest.fixture(autouse=True)
def mock_laya_agent() -> Any:
    """Substitui o agente pesado por um mock leve durante a execução dos testes."""
    original = LayaModelHolder._instance
    LayaModelHolder.set_agent(DummyLayaAgent())
    yield
    LayaModelHolder.set_agent(original)


async def test_ai_tune_success(client: httpx.AsyncClient) -> None:
    """Verifica otimização bem-sucedida em calibração existente."""
    cal_id = "stock-hatch-20t-gdi-oem-stage"
    payload = {
        "target_table_ids": ["ve", "ignition_base"],
        "aggressiveness": "balanced",
        "max_fuel_step_pct": 8.0,
        "max_ign_advance_step_deg": 1.5,
    }

    resp = await client.post(f"/api/v1/calibrations/{cal_id}/ai-tune", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_cells_modified"] > 0
    assert len(data["corrections"]) == data["total_cells_modified"]
    assert data["safety_risk"] is False
    assert data["risk_confidence"] == 0.95
    assert data["estimated_torque_gain_pct"] == 3.5

    # Valida estrutura da primeira correção
    c0 = data["corrections"][0]
    assert c0["table_id"] in ("ve", "ignition_base")
    assert c0["action"] in ("enrich_light", "advance_light")
    assert c0["confidence"] > 0.8
    assert "explanation" in c0


async def test_ai_tune_resolves_navigation_aliases(client: httpx.AsyncClient) -> None:
    """Garante que IDs da interface (inj.ve e ign.base) mapeiem para as tabelas reais."""
    cal_id = "stock-hatch-20t-gdi-oem-stage"
    payload = {
        "target_table_ids": ["inj.ve", "ign.base"],
        "aggressiveness": "safe",
    }

    resp = await client.post(f"/api/v1/calibrations/{cal_id}/ai-tune", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_cells_modified"] > 0
    table_ids = {c["table_id"] for c in data["corrections"]}
    assert "ve" in table_ids
    assert "ignition_base" in table_ids


async def test_ai_tune_calibration_not_found(client: httpx.AsyncClient) -> None:
    """Retorna 404 quando o ID da calibração não existe."""
    resp = await client.post(
        "/api/v1/calibrations/calib-inexistente-123/ai-tune",
        json={"target_table_ids": ["ve"]},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == "CALIBRATION_NOT_FOUND"


async def test_ai_tune_validation_error(client: httpx.AsyncClient) -> None:
    """Retorna 422 quando os limites de segurança da requisição são violados."""
    cal_id = "stock-hatch-20t-gdi-oem-stage"
    # max_fuel_step_pct > 25.0
    resp = await client.post(
        f"/api/v1/calibrations/{cal_id}/ai-tune",
        json={"max_fuel_step_pct": 50.0},
    )
    assert resp.status_code == 422
