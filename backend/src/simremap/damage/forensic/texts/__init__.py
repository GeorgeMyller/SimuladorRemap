"""Modelos de texto pt-BR versionados do laudo, sem LLM (RF-26; D-28; Apêndice C.4).

Os modelos ficam em ``texts/pt-BR/<audiência>.json`` (``string.Template``) e as frases
por mecanismo em ``phrases.json``. Mudar um texto exige subir ``GENERATOR_VERSION``,
porque o ``report_sha256`` depende do texto.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from importlib import resources
from string import Template
from typing import Any, Final, get_args

from simremap.damage.contracts import (
    Audience,
    CausalLink,
    EarlyWarning,
    FailureEvent,
    NarrativeText,
    Recommendation,
)

__all__ = ["AUDIENCES", "GENERATOR_VERSION", "TextContext", "render_texts"]

GENERATOR_VERSION: Final = "1.0.0"
AUDIENCES: Final[tuple[Audience, ...]] = get_args(Audience)
_LOCALE: Final = "pt-BR"
_LIMITS: Final = {"title": 80, "summary": 280, "explanation": 1200}
MAX_QUESTIONS: Final = 5


@cache
def _load(name: str) -> dict[str, Any]:
    raw = resources.files(__package__).joinpath(_LOCALE, f"{name}.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(raw)
    return data


@dataclass(frozen=True, slots=True)
class TextContext:
    kind: str  # failure | near_miss
    family: str  # knock | thermal | rod | preignition | overrev
    failure: FailureEvent | None
    component_kind: str  # piston | rod | ... | none
    t_end_s: float
    warnings: tuple[EarlyWarning, ...]
    recommendations: tuple[Recommendation, ...]
    chain: tuple[CausalLink, ...]
    knock_cylinders: tuple[int, ...]
    critical: dict[str, float]  # lw_end, theta_k, mapo, intensity, tu_max, octane, cylinder
    diff_txt: str


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None or math.isnan(value):
        return "n/d"
    return f"{value:.{digits}f}".replace(".", ",")


def _beginner_actions(ctx: TextContext, phrases: dict[str, Any]) -> str:
    lines: list[str] = []
    for rec in ctx.recommendations[:3]:
        template = phrases["action_beginner"].get(rec.rule_id)
        if template is None:
            continue
        text = Template(template).safe_substitute(
            cylinders=", ".join(map(str, rec.cylinders)) or "afetados",
            value_max=_num(rec.value_max, 0),
        )
        lines.append(f"{len(lines) + 1}. {text}")
    if not lines:
        lines.append("1. Volte a calibração de série e repita a puxada.")
    return "\n".join(lines)


def _values(ctx: TextContext) -> dict[str, str]:
    phrases = _load("phrases")
    failure = ctx.failure
    mode = "none" if failure is None else failure.mode.value
    mechanism = "none" if failure is None else failure.mechanism.value
    cylinder = None if failure is None else failure.cylinder
    component_label = Template(phrases["component"][ctx.component_kind]).safe_substitute(
        cylinder=cylinder if cylinder is not None else ""
    )
    none_txt = phrases["none_txt"]
    warnings_txt = (
        "; ".join(
            f"{w.signal} {_num(w.lead_time_s, 1)} s antes"
            + (f" (cil. {w.cylinder})" if w.cylinder else "")
            for w in ctx.warnings[:5]
        )
        or none_txt
    )
    tables = sorted({r.table_id for r in ctx.recommendations if r.table_id != "none"})
    critical = ctx.critical
    lead_max = max((w.lead_time_s for w in ctx.warnings), default=0.0)
    weak = next((link.variable for link in ctx.chain if link.kind == "calibration"), None)
    if weak is None:
        weak = ctx.chain[0].variable if ctx.chain else none_txt
    first_knock = ctx.knock_cylinders[0] if ctx.knock_cylinders else critical.get("cylinder")
    return {
        "headline": phrases["headline"][ctx.kind],
        "outcome_beginner": phrases["outcome_beginner"][ctx.kind],
        "component_label": component_label,
        "component_id": "motor" if failure is None else failure.component_id,
        "cause_beginner": phrases["cause_beginner"][ctx.family],
        "cause_intermediate": phrases["cause_intermediate"][ctx.family],
        "mode_label": phrases["mode"][mode],
        "mechanism_label": phrases["mechanism"][mechanism],
        "t_end": _num(ctx.t_end_s, 2),
        "actions_numbered": _beginner_actions(ctx, phrases),
        "actions_txt": "; ".join(f"{r.rule_id} {r.action}" for r in ctx.recommendations)
        or none_txt,
        "warnings_txt": warnings_txt,
        "knock_cyls_txt": ", ".join(map(str, ctx.knock_cylinders)) or none_txt,
        "tables_txt": ", ".join(tables) or none_txt,
        "diff_txt": ctx.diff_txt,
        "crit_cyl": _num(critical.get("cylinder"), 0),
        "lw_end": _num(critical.get("lw_end"), 2),
        "theta_k": _num(critical.get("theta_k"), 0),
        "mapo": _num(critical.get("mapo"), 0),
        "intensity": _num(critical.get("intensity"), 2),
        "tu_max": _num(critical.get("tu_max"), 0),
        "octane": _num(critical.get("octane"), 1),
        "chain_txt": " → ".join(link.kind for link in ctx.chain),
        "lead_max": _num(lead_max, 1),
        "first_knock_cyl": _num(float(first_knock) if first_knock is not None else None, 0),
        "weak_link": weak,
    }


def render_texts(ctx: TextContext) -> dict[Audience, NarrativeText]:
    """Textos das 3 audiências (``questions`` só em ``instructor``)."""
    values = _values(ctx)
    out: dict[Audience, NarrativeText] = {}
    for audience in AUDIENCES:
        template = _load(audience)
        fields = {
            key: _clip(Template(template[key]).safe_substitute(values), limit)
            for key, limit in _LIMITS.items()
        }
        questions = [
            _clip(Template(q).safe_substitute(values), 200) for q in template.get("questions", [])
        ][:MAX_QUESTIONS]
        out[audience] = NarrativeText(questions=questions, **fields)
    return out
