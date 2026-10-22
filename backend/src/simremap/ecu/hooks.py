"""Hooks de perfil consumidos pelo runtime genérico.

Fontes: ecu-core RF-29, Apêndice G; simulation-bus 3.2.

Implementados pela spec ecu-profiles. No Sprint 2 o núcleo usa ``NullProfileHooks``:
todas as estratégias suportadas, sem validação extra, massa de ar por speed-density e
nenhum ajuste de pedidos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from simremap.ecu.contracts import StrategyKind

if TYPE_CHECKING:
    from simremap.ecu.calibration import CalibrationContent

__all__ = ["ALL_STRATEGIES", "NullProfileHooks", "ProfileHooks"]

ALL_STRATEGIES: frozenset[str] = frozenset(kind.value for kind in StrategyKind)


@runtime_checkable
class ProfileHooks(Protocol):
    """Contrato do Apêndice G.

    - ``supported_strategies``: estratégias aceites pelo perfil (RF-29, EC-10).
    - ``validate_calibration``: pares ``(code, detail)``; lista vazia = válida.
    - ``air_charge_mg``: massa de ar por cilindro e ciclo (mg) no modo
      ``profile_air_model``; ``None`` = usar speed-density. Recebe ``SensorReadings`` e a
      ``CompiledCalibration``.
    - ``adjust_requests``: pode alterar os pedidos (``EcuRequests``) antes da
      arbitragem, sem alocação.
    """

    profile_id: str

    def supported_strategies(self) -> frozenset[str]: ...

    def validate_calibration(
        self, cal: CalibrationContent, options: dict[str, bool]
    ) -> list[tuple[str, str]]: ...

    def air_charge_mg(self, sensors: object, compiled: object) -> float | None: ...

    def adjust_requests(self, sensors: object, requests: object) -> None: ...


class NullProfileHooks:
    """Hook nulo do Sprint 2 (ecu-core seção 10)."""

    def __init__(self, profile_id: str = "ft-pro") -> None:
        self.profile_id = profile_id

    def supported_strategies(self) -> frozenset[str]:
        return ALL_STRATEGIES

    def validate_calibration(
        self, cal: CalibrationContent, options: dict[str, bool]
    ) -> list[tuple[str, str]]:
        return []

    def air_charge_mg(self, sensors: object, compiled: object) -> float | None:
        return None

    def adjust_requests(self, sensors: object, requests: object) -> None:
        return None
