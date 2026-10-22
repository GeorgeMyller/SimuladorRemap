"""Os 7 cenários builtin iniciam, rodam a baseline, permitem diagnóstico e são aprovados com
um acerto real (003 T021, RF-15). Marcador ``e2e`` (≈ 25–60 s por cenário):
``uv run --frozen pytest -m e2e tests/qa/test_scenarios_approvable.py``.

App de produção (catálogo real, ecu-core semeado, ``ProfiledEcu``, dano padrão, telemetria
a 1 kHz) em worker ``process``. Por cenário:

1. o perfil de jogador inicia a tentativa ⇒ ``in_progress`` com a ``baseline_pull`` feita;
2. diagnóstico: a 1.ª dica abre e o log da baseline traz os canais que ela cita; nos
   cenários com defeito a assinatura aparece no log (bomba: λ pobre acima de 5500 rpm;
   bico: cilindro 3 o mais quente; wastegate: MAP muito abaixo do alvo);
3. acerto (``qa_play.ACERTOS`` / ``tune_standalone``), puxadas válidas e submissão com o
   defeito declarado ⇒ avaliação aprovada em todos os critérios;
4. regressão do bug da ordem de publicação: com a avaliação ``completed`` a tentativa já
   está ``passed`` e a sessão ``closed`` (antes ficava ``evaluating`` com a sessão aberta e o
   início seguinte dava 409 ``SIM_CAPACITY_EXCEEDED``).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Final

import httpx
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_play import play
from qa_support import API, Json, failed_criteria, new_player, open_client, real_app, start_attempt

pytestmark = pytest.mark.e2e

SCENARIOS: Final = (
    "stage1-oem",
    "stage2-pops-bangs",
    "standalone-swap",
    "defect-fuel-pump",
    "defect-boost-leak",
    "defect-lean-injector",
    "defect-wastegate-stuck",
)
HINT_CHANNELS: Final[dict[str, tuple[str, ...]]] = {
    "stage1-oem": ("boost_target_kpa", "knock_retard_deg", "egt_pre_turbo_c"),
    "stage2-pops-bangs": ("overrun_afterfire", "egt_pre_turbo_c"),
    "standalone-swap": ("lambda_measured", "knock_retard_deg"),
    "defect-fuel-pump": ("lambda_measured", "lambda_target", "injector_duty_pct"),
    "defect-boost-leak": ("map_kpa", "boost_target_kpa", "turbo_rpm", "wastegate_duty_pct"),
    "defect-lean-injector": ("egt_c_cyl1", "egt_c_cyl3", "lambda_cyl3", "injector_pw_ms_cyl3"),
    "defect-wastegate-stuck": ("map_kpa", "boost_target_kpa"),
}
WOT_PEDAL_PCT: Final = 99.0


@pytest.fixture
async def client(settings_factory: Callable[..., Any]) -> AsyncIterator[httpx.AsyncClient]:
    async with open_client(real_app(settings_factory(worker_mode="process"))) as c:
        yield c


def _wot(log: Json, min_rpm: float) -> tuple[dict[str, np.ndarray], np.ndarray]:
    data = {k: np.asarray(v, dtype=np.float64) for k, v in log["data"].items()}
    mask = (data["pedal_pct"] >= WOT_PEDAL_PCT) & (data["rpm"] >= min_rpm)
    return data, mask


def assert_defect_signature(scenario_id: str, log: Json) -> None:
    if scenario_id == "defect-fuel-pump":
        data, wot = _wot(log, 5600.0)
        lean = float(np.percentile(data["lambda_measured"][wot] - data["lambda_target"][wot], 90))
        assert lean > 0.05, lean
    elif scenario_id == "defect-lean-injector":
        data, wot = _wot(log, 4500.0)
        egt = [float(np.mean(data[f"egt_c_cyl{c}"][wot])) for c in (1, 2, 3, 4)]
        assert int(np.argmax(egt)) == 2, egt
    elif scenario_id == "defect-wastegate-stuck":
        data, wot = _wot(log, 4500.0)
        shortfall = data["boost_target_kpa"][wot] - data["map_kpa"][wot]
        assert float(np.mean(shortfall)) > 40.0, float(np.mean(shortfall))


async def diagnose(
    client: httpx.AsyncClient, scenario_id: str, attempt: Json, headers: dict[str, str]
) -> None:
    hint = await client.post(f"{API}/attempts/{attempt['attempt_id']}/hints", headers=headers)
    assert hint.status_code == 200, hint.text
    assert hint.json()["order"] == 1
    resp = await client.get(f"{API}/runs/{attempt['baseline_run_id']}/log")
    assert resp.status_code == 200, resp.text
    log: Json = resp.json()
    assert set(HINT_CHANNELS[scenario_id]) <= set(log["data"])
    assert_defect_signature(scenario_id, log)


@pytest.mark.parametrize("scenario_id", SCENARIOS)
async def test_builtin_scenario_is_approvable(client: httpx.AsyncClient, scenario_id: str) -> None:
    headers = await new_player(client, f"qa_{scenario_id.replace('-', '_')}"[:24])
    attempt = await start_attempt(client, scenario_id, headers)
    assert attempt["baseline_run_id"] and (attempt["baseline_peak_whp"] or 0.0) > 100.0
    await diagnose(client, scenario_id, attempt, headers)

    evaluation = await play(client, scenario_id, attempt, headers)

    assert evaluation["status"] == "completed", evaluation
    assert not failed_criteria(evaluation), failed_criteria(evaluation)
    assert evaluation["passed"] is True
    after = await client.get(f"{API}/attempts/{attempt['attempt_id']}", headers=headers)
    assert after.json()["state"] == "passed"
    session = await client.get(f"{API}/sessions/{attempt['session_id']}")
    assert session.json()["state"] == "closed"
