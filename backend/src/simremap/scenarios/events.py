"""Eventos locais e taxa de conclusão (training-scenarios RF-16, RF-17; premissa OQ-03).

Eventos gravados em ``scenario_event`` (sem ``nickname``; ``data_json`` só com ids e
números): ``attempt_started``, ``baseline_completed``, ``run_classified``,
``hint_revealed``, ``attempt_submitted``, ``attempt_passed``, ``attempt_failed`` (``final``
indica a última submissão), ``attempt_abandoned`` e ``package_exported``.

Taxa de conclusão por cenário: ``100 · tentativas com attempt_passed / tentativas com
attempt_started`` (filtro de datas sobre o ``attempt_started``). Tentativas
``abandoned``, ``expired`` e ``failed_to_start`` ficam no denominador. A métrica do produto
(``completion_rate_base``) soma só os cenários base (premissa OQ-03 / D-REST-12).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from simremap.scenarios.contracts import ScenarioStats
from simremap.scenarios.repository import ScenarioRepository

__all__ = ["EVENT_KINDS", "EventLog", "compute_stats"]

EVENT_KINDS: Final[tuple[str, ...]] = (
    "attempt_started",
    "baseline_completed",
    "run_classified",
    "hint_revealed",
    "attempt_submitted",
    "attempt_passed",
    "attempt_failed",
    "attempt_abandoned",
    "package_exported",
)


def compute_stats(
    scenario_id: str, events: Sequence[tuple[str, str, dict[str, Any]]]
) -> ScenarioStats:
    """``ScenarioStats`` a partir de ``(kind, attempt_id, data)`` já filtrados por cenário.

    ``events`` traz os ``attempt_started`` do intervalo e todos os desfechos; desfechos de
    tentativas fora do intervalo são ignorados.
    """
    started = {a for k, a, _ in events if k == "attempt_started"}
    passed: dict[str, int] = {}
    failed_final: set[str] = set()
    abandoned: set[str] = set()
    for kind, attempt, data in events:
        if attempt not in started:
            continue
        if kind == "attempt_passed":
            passed.setdefault(attempt, int(data.get("submission_index", 1)))
        elif kind == "attempt_failed" and data.get("final"):
            failed_final.add(attempt)
        elif kind == "attempt_abandoned":
            abandoned.add(attempt)
    failed_final -= set(passed)
    abandoned -= set(passed) | failed_final
    n = len(started)
    rate = None if n == 0 else round(100.0 * len(passed) / n, 1)
    median = None if not passed else float(statistics.median(passed.values()))
    return ScenarioStats(
        scenario_id=scenario_id,
        started=n,
        passed=len(passed),
        failed_final=len(failed_final),
        abandoned=len(abandoned),
        completion_rate_pct=rate,
        median_submissions_to_pass=median,
    )


class EventLog:
    """Gravação e consulta dos eventos locais."""

    def __init__(self, repo: ScenarioRepository) -> None:
        self.repo = repo

    async def record(
        self, kind: str, scenario_id: str, attempt_id: str, data: dict[str, Any] | None = None
    ) -> None:
        if kind not in EVENT_KINDS:
            raise ValueError(f"evento desconhecido: {kind}")
        await self.repo.add_event(kind, scenario_id, attempt_id, data)

    async def _rows(
        self, scenario_ids: Sequence[str], start: datetime | None, end: datetime | None
    ) -> list[tuple[str, str, dict[str, Any]]]:
        started = await self.repo.events(
            scenario_ids=scenario_ids, kinds=("attempt_started",), start=start, end=end
        )
        outcomes = await self.repo.events(
            scenario_ids=scenario_ids,
            kinds=("attempt_passed", "attempt_failed", "attempt_abandoned"),
        )
        return [(r.kind, r.attempt_id, dict(r.data_json)) for r in (*started, *outcomes)]

    async def stats(
        self, scenario_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> ScenarioStats:
        return compute_stats(scenario_id, await self._rows([scenario_id], start, end))

    async def completion_rate_base(
        self, base_ids: Sequence[str], start: datetime | None = None, end: datetime | None = None
    ) -> float | None:
        """Taxa de conclusão agregada dos cenários base (métrica G-03 do PRD)."""
        stats = compute_stats("base", await self._rows(list(base_ids), start, end))
        return stats.completion_rate_pct

    async def kinds_for(self, attempt_id: str) -> list[str]:
        return [r.kind for r in await self.repo.events(attempt_id=attempt_id)]
