"""Laudo forense do knock-and-failure-model (RF-22 a RF-27, RF-30, RF-31)."""

from __future__ import annotations

from simremap.damage.forensic.report import (
    build_forensic_report,
    build_minimal_report,
    canonical_json,
    report_sha256,
)
from simremap.damage.forensic.texts import GENERATOR_VERSION

__all__ = [
    "GENERATOR_VERSION",
    "build_forensic_report",
    "build_minimal_report",
    "canonical_json",
    "report_sha256",
]
