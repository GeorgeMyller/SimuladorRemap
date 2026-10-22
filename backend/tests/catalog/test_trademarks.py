"""RF-07 / D-34: lista de bloqueio de marcas em textos exibidos."""

from __future__ import annotations

import pytest

from simremap.catalog.loader import Catalog
from simremap.catalog.trademarks import BLOCKED_TERMS, find_trademarks, normalize_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hatch EA888", ["ea888"]),
        ("hatch ea888", ["ea888"]),
        ("Motor 2JZ-GTE", ["2jz", "2jz-gte"]),
        ("Turbo GARRETT", ["garrett"]),
        ("Coupé B58", ["b58"]),
        ("Muscle (Coyote)", ["coyote"]),
        ("ŠKODA", ["skoda"]),
        ("ECU M1", ["m1"]),
    ],
)
def test_detects_whole_word_case_insensitive(text: str, expected: list[str]) -> None:
    assert find_trademarks(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Clássico 2.0 turbo de swap",  # "ls" dentro de palavra
        "Inspirado em arquitetura 2.0 8v",
        "Hatch 2.0 turbo GDI",
        "apenas texto",  # "ap" dentro de palavra
        "elitismo",  # "elite" dentro de palavra
        "M10",
    ],
)
def test_no_false_positive(text: str) -> None:
    assert find_trademarks(text) == []


def test_restrict_terms() -> None:
    assert find_trademarks("Bosch Garrett", terms=["garrett"]) == ["garrett"]


def test_normalize() -> None:
    assert normalize_text("  Coupé   ÇÃO ") == "coupe cao"


def test_list_matches_appendix() -> None:
    assert len(BLOCKED_TERMS) == len(set(BLOCKED_TERMS)) == 51
    assert {"ea888", "bmw", "fueltech", "nexus", "shelby"} <= set(BLOCKED_TERMS)


def test_package_texts_have_zero_hits(real_catalog: Catalog) -> None:
    texts: list[str] = []
    for entry in real_catalog.vehicles.values():
        texts += [entry.spec.display_name, entry.spec.architecture_note]
        texts += [c.source for c in entry.curves]
        texts += [p.note for p in entry.spec.provenance.values()]
        for payload in entry.calibrations.values():
            meta = payload["metadata"]
            texts += [meta["name"], meta["notes"]]
    texts += [f.display_name for f in real_catalog.fuels.values()]
    hits = {t: find_trademarks(t) for t in texts if find_trademarks(t)}
    assert hits == {}
