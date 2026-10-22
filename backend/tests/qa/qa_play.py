"""Joga uma tentativa até a avaliação com o acerto real do cenário (003 T021, T022).

- ``ACERTOS``: edição da calibração, pedido das puxadas de evidência e defeito declarado
  dos 6 cenários no OEM-Stage do ``hatch-20t-gdi``;
- ``tune_standalone``: swap para a FT-Pro, setup base pela ficha com o mapa do
  assistente, puxada base, afinação de plena carga, puxada com pressão e 2.ª passada de
  combustível (cenário ``standalone-swap``);
- ``play``: aplica o acerto, faz as puxadas válidas e submete; devolve a avaliação.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Final

import httpx
import qa_tunes as qt
from qa_support import (
    API,
    Json,
    apply_calibration,
    replace_calibration,
    run_pull,
    submit,
)

STANDALONE_ID: Final = "standalone-swap"
STANDALONE_VEHICLE: Final = "classic-20t-swap"
STANDALONE_PROFILE: Final = "ft-pro"
SWEEP: Final[Json] = {"run_type": "sweep_pull"}
# Stage 2: antes de 003 T032 (ciclo-limite de 7,5 Hz do PID de boost do hatch) a 300 rpm/s
# a pressão oscilava e o pico de torque passava dos 420 N·m da biela; com os ganhos novos
# o cenário também passa a 300 rpm/s e os 150 rpm/s ficam como margem.
SLOW_SWEEP: Final[Json] = {"run_type": "sweep_pull", "ramp_rate_rpm_s": 150.0}
EVIDENCE_PULLS: Final = 2


@dataclass(frozen=True)
class Acerto:
    edit: Callable[[Json], None]
    pull: Json = field(default_factory=lambda: dict(SWEEP))
    defect: str | None = None


ACERTOS: Final[dict[str, Acerto]] = {
    "stage1-oem": Acerto(qt.stage1),
    "stage2-pops-bangs": Acerto(qt.stage2, dict(SLOW_SWEEP)),
    "defect-fuel-pump": Acerto(qt.fuel_pump_safe, defect="fuel_pump_weak"),
    "defect-boost-leak": Acerto(qt.rich_wot, defect="boost_leak"),
    "defect-lean-injector": Acerto(qt.rich_wot, defect="injector_clogged"),
    "defect-wastegate-stuck": Acerto(
        partial(qt.rich_wot, min_map_kpa=qt.STANDALONE_SPOOL_KPA), defect="wastegate_stuck"
    ),
}


async def swap_and_setup(client: httpx.AsyncClient, session_id: str, profile_id: str) -> Json:
    """Swap OEM → ``profile_id`` e setup base pela ficha com o mapa do assistente."""
    swap = await client.post(
        f"{API}/sessions/{session_id}/ecu/swap",
        json={"target_profile_id": profile_id, "confirm_snapshot": True},
    )
    assert swap.status_code == 200, swap.text
    assert swap.json()["ecu_state"] == "awaiting_base_setup"
    setup = await client.put(
        f"{API}/sessions/{session_id}/ecu/base-setup",
        json={
            "base_version": None,
            "base_setup": qt.classic_base_setup(),
            "generate_base_map": True,
            "wizard": {"max_map_kpa": qt.STANDALONE_WOT_MAP_KPA},
        },
    )
    assert setup.status_code == 200, setup.text
    body: Json = setup.json()
    assert body["ecu_state"] == "standalone_ready" and body["calibration_id"], body
    return body


async def tune_standalone(client: httpx.AsyncClient, session_id: str) -> str:
    """Acerto do ``standalone-swap`` na FT-Pro; devolve o ``calibration_id`` aplicado."""
    setup = await swap_and_setup(client, session_id, STANDALONE_PROFILE)
    cal_id = str(setup["calibration_id"])
    base = await run_pull(client, session_id, run_type="baseline_pull")
    assert base["state"] == "completed", base.get("abort_reason")
    await replace_calibration(
        client,
        cal_id,
        lambda content: qt.standalone_wot(content, base["curve"], STANDALONE_VEHICLE),
        "plena carga",
    )
    await apply_calibration(client, session_id, cal_id)
    boosted = await run_pull(client, session_id)
    assert boosted["state"] == "completed", boosted.get("abort_reason")
    await replace_calibration(
        client, cal_id, lambda content: qt.refine_fuel(content, boosted["curve"]), "combustível"
    )
    await apply_calibration(client, session_id, cal_id)
    multi = await run_pull(client, session_id, run_type="multi_pull")
    assert multi["state"] == "completed", multi.get("abort_reason")
    return cal_id


async def tune_oem(client: httpx.AsyncClient, attempt: Json, acerto: Acerto) -> None:
    cal_id, session_id = attempt["calibration_id"], attempt["session_id"]
    await replace_calibration(client, cal_id, acerto.edit, "acerto QA")
    await apply_calibration(client, session_id, cal_id)
    for _ in range(EVIDENCE_PULLS):
        run = await run_pull(client, session_id, **acerto.pull)
        assert run["state"] == "completed", run.get("abort_reason")


async def play(
    client: httpx.AsyncClient, scenario_id: str, attempt: Json, headers: dict[str, str]
) -> Json:
    """Acerto + puxadas de evidência + submissão; devolve a avaliação terminada."""
    if scenario_id == STANDALONE_ID:
        cal_id = await tune_standalone(client, attempt["session_id"])
        return await submit(client, attempt["attempt_id"], headers, cal_id)
    acerto = ACERTOS[scenario_id]
    await tune_oem(client, attempt, acerto)
    return await submit(
        client, attempt["attempt_id"], headers, attempt["calibration_id"], acerto.defect
    )
