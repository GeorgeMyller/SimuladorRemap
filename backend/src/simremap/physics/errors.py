"""Códigos de erro do motor físico (rest-api 4.3; D-REST-11) e a exceção ``PhysicsError``.

Os códigos são registados no catálogo único do ``core`` ao importar este módulo
(carregado por ``load_component_errors`` a partir de ``COMPONENT_ERROR_MODULES``).
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = [
    "ACTUATOR_COMMAND_INVALID",
    "PHYSICS_CODES",
    "PHYSICS_CONFIG_INVALID",
    "PHYSICS_DT_MISMATCH",
    "PHYSICS_FUEL_CHANGE_WHILE_RUNNING",
    "PHYSICS_NUMERIC_DIVERGENCE",
    "PHYSICS_SNAPSHOT_INVALID",
    "PHYSICS_UNAVAILABLE",
    "PhysicsError",
]

PHYSICS_CONFIG_INVALID: Final = "PHYSICS_CONFIG_INVALID"
ACTUATOR_COMMAND_INVALID: Final = "ACTUATOR_COMMAND_INVALID"
PHYSICS_NUMERIC_DIVERGENCE: Final = "PHYSICS_NUMERIC_DIVERGENCE"
PHYSICS_FUEL_CHANGE_WHILE_RUNNING: Final = "PHYSICS_FUEL_CHANGE_WHILE_RUNNING"
PHYSICS_DT_MISMATCH: Final = "PHYSICS_DT_MISMATCH"
PHYSICS_SNAPSHOT_INVALID: Final = "PHYSICS_SNAPSHOT_INVALID"
PHYSICS_UNAVAILABLE: Final = "PHYSICS_UNAVAILABLE"

PHYSICS_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    (PHYSICS_CONFIG_INVALID, 422, "Configuração da física inválida"),
    (ACTUATOR_COMMAND_INVALID, 422, "Comando de atuadores inválido"),
    (PHYSICS_NUMERIC_DIVERGENCE, 500, "Divergência numérica na física"),
    (PHYSICS_FUEL_CHANGE_WHILE_RUNNING, 409, "Troca de combustível com o motor em funcionamento"),
    (PHYSICS_DT_MISMATCH, 500, "Passo de tempo diferente de 1/sim_hz"),
    (PHYSICS_SNAPSHOT_INVALID, 422, "Snapshot da física inválido"),
    (PHYSICS_UNAVAILABLE, 503, "Física indisponível"),
)

for _code, _status, _title in PHYSICS_CODES:
    register_error(_code, _status, _title)


class PhysicsError(SimRemapError):
    """Erro do motor físico com ``code`` estável (engine-physics-core seção 8).

    ``code`` e ``detail`` ficam disponíveis na instância, como pede a API pública::

        raise PhysicsError(PHYSICS_DT_MISMATCH, "dt=0.002 difere de 1/sim_hz=0.001")
    """

    def __init__(self, code: str, detail: str, **extra: object) -> None:
        super().__init__(detail, code=code, headers=None, **extra)
        # A instância expõe ``code`` (atributo de instância sobrepõe o da classe base).
        self.__dict__["code"] = code
