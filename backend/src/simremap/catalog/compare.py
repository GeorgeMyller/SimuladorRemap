"""Comparação determinística com o ``Reference Benchmark Baseline v1`` (RF-22, RF-29; D-30).

Regras (vehicle-catalog seção 9, "Regras de comparação"):
- Para cada grandeza ``q`` de ``curve.quantities``, a série simulada é interpolada
  linearmente nos RPM de referência que caem dentro do intervalo simulado; pontos fora
  do intervalo não contam.
- ``dev_pct = |sim − ref| / |ref| · 100``; a EGT compara em °C (convenção da física).
- ``passed`` exige, em todas as grandezas declaradas, ``max dev_pct < tolerance_pct`` e
  ``points_compared ≥ 8``. Uma grandeza declarada que a simulação não traz (menos de
  2 pontos com valor) vai para ``not_compared`` e reprova a comparação; as grandezas não
  declaradas pela curva vão para ``not_compared`` sem reprovar (Fluxo Alternativo C).
- Função pura em ``float`` do Python, com ordem fixa de operações: a mesma entrada dá
  resultado idêntico bit a bit.
- D-17 do data-model: a correção ``none`` do ``dyno-bench`` equivale a ``uncorrected``.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Final, get_args

from simremap.catalog.contracts import (
    Quantity,
    QuantityDeviation,
    ReferenceComparison,
    ReferenceCurve,
    ReferenceCurvePoint,
)
from simremap.catalog.grids import interp_linear

__all__ = ["ALL_QUANTITIES", "MIN_POINTS_COMPARED", "compare_to_reference", "reference_correction"]

ALL_QUANTITIES: Final[tuple[Quantity, ...]] = get_args(Quantity)
MIN_POINTS_COMPARED: Final = 8
_CORRECTION_ALIASES: Final[dict[str, str]] = {"none": "uncorrected"}


def reference_correction(correction: str) -> str:
    """Nome da correção no vocabulário do catálogo (``none`` → ``uncorrected``)."""
    return _CORRECTION_ALIASES.get(correction, correction)


def _series(
    simulated: Sequence[ReferenceCurvePoint], quantity: Quantity
) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for point in simulated:
        value = getattr(point, quantity)
        if value is not None:
            xs.append(point.rpm)
            ys.append(float(value))
    return xs, ys


def _deviation(
    curve: ReferenceCurve, quantity: Quantity, xs: list[float], ys: list[float]
) -> QuantityDeviation:
    max_dev = 0.0
    rpm_at_max = curve.points[0].rpm
    count = 0
    for point in curve.points:
        ref = getattr(point, quantity)
        if ref is None or ref == 0.0 or not xs[0] <= point.rpm <= xs[-1]:
            continue
        sim = interp_linear(xs, ys, point.rpm)
        dev = abs(sim - ref) / abs(ref) * 100.0
        if count == 0 or dev > max_dev:
            max_dev, rpm_at_max = dev, point.rpm
        count += 1
    return QuantityDeviation(
        quantity=quantity, max_deviation_pct=max_dev, rpm_at_max=rpm_at_max, points_compared=count
    )


def compare_to_reference(
    curve: ReferenceCurve,
    simulated: Sequence[ReferenceCurvePoint],
    *,
    simulated_correction: str | None = None,
) -> ReferenceComparison:
    """Desvio máximo por grandeza da série ``simulated`` face à curva ``curve``.

    ``simulated`` deve ter RPM estritamente crescente. ``simulated_correction`` (opcional)
    é a norma de correção da puxada (``sae_j1349``, ``din_70020``, ``none``); se diferir da
    curva, lança ``ValueError`` com ``REFERENCE_CORRECTION_MISMATCH``.
    """
    rpms = [p.rpm for p in simulated]
    if any(b <= a for a, b in itertools.pairwise(rpms)):
        raise ValueError("a série simulada deve ter rpm estritamente crescente")
    if simulated_correction is not None:
        sim_corr = reference_correction(simulated_correction)
        if sim_corr != curve.conditions.correction:
            raise ValueError(
                f"REFERENCE_CORRECTION_MISMATCH: puxada '{sim_corr}' e curva "
                f"'{curve.conditions.correction}'"
            )
    deviations: list[QuantityDeviation] = []
    missing: list[Quantity] = []
    for quantity in curve.quantities:
        xs, ys = _series(simulated, quantity)
        if len(xs) < 2:  # noqa: PLR2004
            missing.append(quantity)
            continue
        deviations.append(_deviation(curve, quantity, xs, ys))
    not_compared = [q for q in ALL_QUANTITIES if q not in curve.quantities or q in missing]
    passed = (
        not missing
        and bool(deviations)
        and all(
            d.max_deviation_pct < curve.tolerance_pct and d.points_compared >= MIN_POINTS_COMPARED
            for d in deviations
        )
    )
    return ReferenceComparison(
        curve_id=curve.curve_id, deviations=deviations, not_compared=not_compared, passed=passed
    )
