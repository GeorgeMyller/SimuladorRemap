"""Proveniência dos valores e lista ``estimated_fields`` (vehicle-catalog RF-05, RF-06).

Regras:
- ``provenance`` do ``VehicleSpec`` tem chave = ponteiro JSON (RFC 6901). A proveniência
  efetiva de um campo é a da chave mais específica que é ele próprio ou um ancestral
  (``/turbo`` cobre ``/turbo/rotor_inertia_kg_m2``).
- Um campo numérico é estimado quando a proveniência efetiva falta ou não é ``prd``,
  ``public_spec`` nem ``literature``.
- Unidade de campo: número escalar, lista de números (``/gear_ratios``), grelha
  ``Grid1D``/``Grid2D`` inteira (``/engine/true_ve``) ou lista de modelos com números
  (``/reference_command_schedule/points``). Campos calculados e metadados
  (``data_version``, ``validated_on``, ``provenance``) não entram.
- ``estimated_fields`` sai ordenada lexicograficamente.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Final

from pydantic import BaseModel

from simremap.catalog.contracts import Grid1D, Grid2D, Provenance, ProvenanceKind, VehicleSpec

__all__ = [
    "DOCUMENTED_KINDS",
    "effective_provenance",
    "estimated_fields",
    "invalid_provenance_pointers",
    "numeric_field_pointers",
    "resolve_pointer",
]

DOCUMENTED_KINDS: Final = frozenset(
    {ProvenanceKind.PRD, ProvenanceKind.PUBLIC_SPEC, ProvenanceKind.LITERATURE}
)
_SKIPPED_TOP_FIELDS: Final = frozenset({"provenance", "data_version", "validated_on"})
_MISSING: Final = object()


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _has_number(value: Any) -> bool:
    if _is_number(value):
        return True
    if isinstance(value, BaseModel):
        return any(_has_number(getattr(value, name)) for name in type(value).model_fields)
    if isinstance(value, list | tuple):
        return any(_has_number(item) for item in value)
    return False


def _walk(value: Any, pointer: str) -> Iterator[str]:
    if value is None:
        return
    if isinstance(value, Grid1D | Grid2D):
        yield pointer
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            if pointer == "" and name in _SKIPPED_TOP_FIELDS:
                continue
            yield from _walk(getattr(value, name), f"{pointer}/{_escape(name)}")
    elif isinstance(value, list | tuple):
        if value and _has_number(value):
            yield pointer
    elif _is_number(value):
        yield pointer


def numeric_field_pointers(spec: VehicleSpec) -> list[str]:
    """Ponteiros de todos os campos numéricos do veículo (unidades descritas acima)."""
    return sorted(_walk(spec, ""))


def effective_provenance(provenance: Mapping[str, Provenance], pointer: str) -> Provenance | None:
    """Proveniência da chave mais específica igual a ``pointer`` ou a um ancestral."""
    current = pointer
    while True:
        found = provenance.get(current)
        if found is not None:
            return found
        if not current:
            return None
        current = current.rsplit("/", 1)[0]


def estimated_fields(spec: VehicleSpec) -> list[str]:
    """RF-06: ponteiros numéricos sem proveniência documentada, ordenados."""
    result = []
    for pointer in numeric_field_pointers(spec):
        prov = effective_provenance(spec.provenance, pointer)
        if prov is None or prov.kind not in DOCUMENTED_KINDS:
            result.append(pointer)
    return sorted(result)


def resolve_pointer(model: BaseModel, pointer: str) -> Any:
    """Valor apontado por ``pointer`` no modelo; ``KeyError`` se não existir."""
    if pointer == "":
        return model
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    current: Any = model
    for raw in pointer[1:].split("/"):
        token = _unescape(raw)
        nxt: Any = _MISSING
        if isinstance(current, BaseModel) and token in type(current).model_fields:
            nxt = getattr(current, token)
        elif isinstance(current, list | tuple) and token.isdigit() and int(token) < len(current):
            nxt = current[int(token)]
        if nxt is _MISSING or nxt is None:
            raise KeyError(pointer)
        current = nxt
    return current


def invalid_provenance_pointers(spec: VehicleSpec) -> list[str]:
    """Chaves de ``provenance`` que não apontam para um campo presente do veículo."""
    bad = []
    for pointer in sorted(spec.provenance):
        top = pointer[1:].split("/", 1)[0] if pointer.startswith("/") else ""
        try:
            if top in _SKIPPED_TOP_FIELDS:
                raise KeyError(pointer)
            resolve_pointer(spec, pointer)
        except KeyError:
            bad.append(pointer)
    return bad
