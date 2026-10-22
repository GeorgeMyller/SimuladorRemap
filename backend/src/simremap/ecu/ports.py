"""Portas injetáveis do ecu-core para catálogo e perfis (integração da onda seguinte).

- ``VehicleLookup`` (vehicle-catalog): ``POST /api/v1/calibrations`` devolve 404
  ``VEHICLE_NOT_FOUND`` quando a porta existe e o veículo não. Sem porta instalada em
  ``app.state.ecu_vehicle_lookup`` qualquer ``vehicle_id`` válido é aceite.
- ``ProfileHooksProvider`` (ecu-profiles): hooks por ``profile_id`` em
  ``app.state.ecu_profile_hooks``; sem porta vale ``NullProfileHooks`` (Sprint 2).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from simremap.ecu.hooks import NullProfileHooks, ProfileHooks

__all__ = ["NullHooksProvider", "ProfileHooksProvider", "VehicleLookup"]


@runtime_checkable
class VehicleLookup(Protocol):
    async def vehicle_exists(self, vehicle_id: str) -> bool: ...


@runtime_checkable
class ProfileHooksProvider(Protocol):
    def hooks_for(self, profile_id: str) -> ProfileHooks: ...


class NullHooksProvider:
    def hooks_for(self, profile_id: str) -> ProfileHooks:
        return NullProfileHooks(profile_id)
