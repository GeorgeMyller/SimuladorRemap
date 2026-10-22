"""Dicas progressivas (training-scenarios RF-15).

Regras de desbloqueio de ``Hint.unlock`` (todas as condições presentes têm de valer; sem
condição a dica é livre):

- ``after_failed_submissions = n``: pelo menos ``n`` avaliações concluídas reprovadas;
- ``after_sim_time_s = t``: tempo simulado da sessão da tentativa ≥ ``t``;
- ``after_event``: ``knock_retard`` (retardo de knock > 0 numa puxada), ``engine_failed``
  (puxada ``engine_failed``), ``egt_limit`` (aborto por EGT ou critério de EGT reprovado),
  ``invalid_run`` (pelo menos 1 puxada inválida).

As dicas são reveladas pela ordem (``order`` 1..n). Revelar não altera ``passed`` nem a
pontuação; ``hints_revealed`` aparece na ``Evaluation``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from simremap.scenarios.contracts import Hint, HintReveal, Scenario
from simremap.scenarios.errors import scenario_error

__all__ = ["HintFacts", "is_unlocked", "next_hint", "reveal"]


@dataclass(frozen=True, slots=True)
class HintFacts:
    """Factos da tentativa usados nas regras de desbloqueio."""

    failed_submissions: int = 0
    sim_time_s: float = 0.0
    events: frozenset[str] = field(default_factory=frozenset)


def is_unlocked(hint: Hint, facts: HintFacts) -> bool:
    rule = hint.unlock
    if rule.after_failed_submissions is not None and (
        facts.failed_submissions < rule.after_failed_submissions
    ):
        return False
    if rule.after_sim_time_s is not None and facts.sim_time_s < rule.after_sim_time_s:
        return False
    return rule.after_event is None or rule.after_event in facts.events


def next_hint(scenario: Scenario, revealed: Sequence[int]) -> Hint | None:
    done = set(revealed)
    pending = sorted((h for h in scenario.hints if h.order not in done), key=lambda h: h.order)
    return pending[0] if pending else None


def reveal(scenario: Scenario, revealed: Sequence[int], facts: HintFacts) -> HintReveal:
    """Próxima dica (409 ``HINTS_EXHAUSTED`` sem dicas; 409 ``HINT_LOCKED`` se bloqueada)."""
    hint = next_hint(scenario, revealed)
    if hint is None:
        raise scenario_error("HINTS_EXHAUSTED", "Não há mais dicas neste cenário.")
    if not is_unlocked(hint, facts):
        raise scenario_error(
            "HINT_LOCKED",
            f"A dica {hint.order} ainda está bloqueada.",
            order=hint.order,
            unlock=hint.unlock.model_dump(mode="json", exclude_none=True),
        )
    remaining = len(scenario.hints) - len(set(revealed)) - 1
    return HintReveal(order=hint.order, text=hint.text, remaining=max(0, remaining))
