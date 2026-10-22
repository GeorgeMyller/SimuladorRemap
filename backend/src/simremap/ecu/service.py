"""Casos de uso de calibração usados pelo router (E-15 a E-19; ecu-core RF-25, RF-26, RF-29).

- ``validate_with_profile``: estratégias ativas fora de ``supported_strategies()`` ⇒ 422
  ``STRATEGY_NOT_SUPPORTED_BY_PROFILE``; depois os pares ``(code, detail)`` do hook.
- ``create_calibration``: ``source = clone`` (copia a versão pedida, mesmo veículo e
  perfil), ``reference`` (copia a calibração de série ``stock-<vehicle_id>-<profile_id>``)
  ou ``payload`` (conteúdo do corpo; o ``content_hash`` é sempre recalculado).
"""

from __future__ import annotations

from typing import Any

from simremap.core.errors import SimRemapError
from simremap.ecu.calibration import (
    CONTENT_FIELDS,
    Calibration,
    CalibrationContent,
    CalibrationCreate,
    CalibrationReplace,
    parse_content,
)
from simremap.ecu.errors import ecu_error
from simremap.ecu.hooks import ProfileHooks
from simremap.ecu.repository import CalibrationRepository

__all__ = [
    "create_calibration",
    "replace_calibration",
    "stock_calibration_id",
    "validate_with_profile",
]


def stock_calibration_id(vehicle_id: str, profile_id: str) -> str:
    """Identificador da calibração de série (data-model D-04)."""
    return f"stock-{vehicle_id}-{profile_id}"


def validate_with_profile(
    content: CalibrationContent, hooks: ProfileHooks, options: dict[str, bool] | None = None
) -> None:
    supported = hooks.supported_strategies()
    for kind, strategy in sorted(content.strategies.items()):
        if strategy.enabled and kind not in supported:
            raise ecu_error(
                "STRATEGY_NOT_SUPPORTED_BY_PROFILE",
                strategy=kind,
                profile_id=content.profile_id.value,
            )
    problems = hooks.validate_calibration(content, dict(options or {}))
    if problems:
        code, detail = problems[0]
        raise ecu_error(code, detail, profile_id=content.profile_id.value)


def _overrides(body: CalibrationCreate | CalibrationReplace) -> dict[str, Any]:
    data = body.model_dump(include={"fuel_model", "tables", "strategies", "profile_params"})
    return {k: v for k, v in data.items() if v is not None}


async def create_calibration(
    repo: CalibrationRepository, body: CalibrationCreate, hooks: ProfileHooks
) -> Calibration:
    base: dict[str, Any] = {"vehicle_id": body.vehicle_id, "profile_id": body.profile_id}
    if body.source in ("clone", "reference"):
        if body.source == "clone":
            if body.clone_from_id is None:
                raise SimRemapError("source = clone exige clone_from_id.", code="VALIDATION_FAILED")
            source = await repo.get(body.clone_from_id, body.clone_from_version)
        else:
            ref_id = stock_calibration_id(body.vehicle_id, body.profile_id.value)
            if not await repo.exists(ref_id):
                raise ecu_error(
                    "CALIBRATION_NOT_FOUND",
                    f"Não há calibração de referência {ref_id}.",
                    calibration_id=ref_id,
                )
            source = await repo.get(ref_id)
        if source.vehicle_id != body.vehicle_id:
            raise ecu_error(
                "CALIBRATION_VEHICLE_MISMATCH",
                f"A calibração de origem é do veículo {source.vehicle_id}.",
            )
        if source.profile_id != body.profile_id:
            raise ecu_error(
                "CALIBRATION_PROFILE_MISMATCH",
                f"A calibração de origem é do perfil {source.profile_id.value}.",
            )
        base = {**source.model_dump(include=set(CONTENT_FIELDS)), **base}
    base.update(_overrides(body))
    content = parse_content(base)
    validate_with_profile(content, hooks)
    meta = body.metadata
    if body.source != "payload" and meta.source == "user":
        meta = meta.model_copy(update={"source": body.source})
    return await repo.create(content, meta)


async def replace_calibration(
    repo: CalibrationRepository,
    calibration_id: str,
    body: CalibrationReplace,
    hooks: ProfileHooks,
) -> Calibration:
    current = await repo.get(calibration_id)
    if body.profile_id is not None and body.profile_id != current.profile_id:
        raise ecu_error(
            "CALIBRATION_PROFILE_IMMUTABLE",
            f"O perfil {current.profile_id.value} da calibração não pode mudar.",
            profile_id=current.profile_id.value,
        )
    data = {
        "vehicle_id": body.vehicle_id or current.vehicle_id,
        "profile_id": current.profile_id,
        **_overrides(body),
    }
    content = parse_content(data)
    validate_with_profile(content, hooks)
    return await repo.replace(calibration_id, body.base_version, content, body.metadata)
