"""E2E de backend da jornada do Lucas, 20 de 20 com ``seed`` 42 (T218; req RF-40; kfm G-01).

Cada execução corre num processo ``spawn`` próprio (``e2e_support.lucas_journey``, com os
ajudantes de ``tests/integration/test_journey_lucas.py``): ``hatch-20t-gdi`` OEM-Stage, E27,
1000 Hz, ``DamageConfig`` padrão, ``ProfiledEcu`` e ``DynoSimTask`` de produção.

- 20 de 20 com boost 280 kPa abs e +8° de avanço: knock ``severe``, retardo saturado, uma
  falha catastrófica, ``engine_failed`` e laudo com cadeia causal ≥ 3 elos, R-KNOCK-01 e
  R-LAMBDA-01;
- 20 de 20 com o acerto corrigido (Stage 2: λ 0,85, −3° nos cilindros com knock, +1° acima
  de 5500 rpm e pressão alvo por rotação até 292 kPa abs, depois de ``engine.restore``):
  ``completed``, knock ≤ ``light``, integridade 100 %, EGT pré-turbina ≤ 950 °C e
  Δwhp ≥ +65 sobre a puxada base (RF-40);
- as 20 execuções são idênticas (mesmos ``curve_sha256``): determinismo da jornada.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from e2e_support import SEED, lucas_journey, pool

RUNS = 20
CLASS_RANK = {"none": 0, "light": 1, "moderate": 2, "severe": 3}
MIN_DELTA_WHP = 65.0


@pytest.fixture(scope="module")
def journeys() -> list[dict[str, Any]]:
    start = time.perf_counter()
    with pool(RUNS) as executor:
        results = list(executor.map(lucas_journey, [SEED] * RUNS))
    elapsed = time.perf_counter() - start
    print(f"\njornada do Lucas: {RUNS} execuções em {elapsed:.1f} s (processos spawn)")
    return results


def test_twenty_of_twenty_exaggerated_runs_break_the_engine(
    journeys: list[dict[str, Any]],
) -> None:
    assert len(journeys) == RUNS
    for j in journeys:
        base = j["base"]
        assert base["state"] == "completed"
        assert CLASS_RANK[base["worst_knock"]] <= CLASS_RANK["light"]
        assert base["health"]["intact"] is True

        failed = j["failed"]
        assert failed["state"] == "engine_failed"
        assert failed["worst_knock"] == "severe"
        assert failed["max_retard_deg"] >= 8.0 - 1e-9
        catastrophic = [f for f in failed["failures"] if f["catastrophic"]]
        assert len(catastrophic) == 1
        assert (catastrophic[0]["mode"], catastrophic[0]["mechanism"]) in {
            ("piston_failure", "knock_erosion"),
            ("rod_failure", "rod_overload"),
        }
        assert failed["failure_event_id"] == catastrophic[0]["failure_event_id"]
        report = failed["report"]
        assert report is not None
        assert len(report["chain_kinds"]) >= 3 and report["chain_kinds"][-1] == "failure"
        assert {"R-KNOCK-01", "R-LAMBDA-01"} <= set(report["rules"])
        assert report["max_lead_time_s"] >= 1.0


def test_twenty_of_twenty_corrected_runs_survive(journeys: list[dict[str, Any]]) -> None:
    for j in journeys:
        corrected = j["corrected"]
        assert corrected["state"] == "completed"
        assert CLASS_RANK[corrected["worst_knock"]] <= CLASS_RANK["light"]
        assert corrected["health"]["integrity_pct"] == 100.0
        assert corrected["health"]["intact"] is True
        assert corrected["health"]["engine_locked"] is False
        assert corrected["egt_max_c"] <= 950.0
        assert not [f for f in corrected["failures"] if f["catastrophic"]]


def test_journey_is_identical_across_processes(journeys: list[dict[str, Any]]) -> None:
    for phase in ("base", "failed", "corrected"):
        hashes = {j[phase]["curve_sha256"] for j in journeys}
        assert len(hashes) == 1, phase
    assert len({j["failed"]["failure_event_id"] for j in journeys}) == 1


def test_corrected_gain_over_baseline(journeys: list[dict[str, Any]]) -> None:
    """RF-40 (stage2-pops-bangs): Δwhp ≥ +65 sobre a puxada base, nas 20 execuções."""
    for j in journeys:
        delta = j["corrected"]["peak_whp"] - j["base"]["peak_whp"]
        assert delta >= MIN_DELTA_WHP, (j["base"]["peak_whp"], j["corrected"]["peak_whp"])
