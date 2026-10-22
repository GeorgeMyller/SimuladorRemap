"""Estratégias de controle da ECU genérica (ecu-core seção 8): um módulo por estratégia.

Cada estratégia lê o ``TickContext`` do tick e escreve o seu ``StrategyRequest``; a
combinação final é feita por ``simremap.ecu.arbitration.arbitrate``.
"""

from simremap.ecu.strategies.antilag import Antilag
from simremap.ecu.strategies.base import TickContext
from simremap.ecu.strategies.boost import BoostControl
from simremap.ecu.strategies.closed_loop import ClosedLoop
from simremap.ecu.strategies.failsafe import Failsafe
from simremap.ecu.strategies.fuel import FuelStrategy, speed_density_air_g
from simremap.ecu.strategies.ignition import Ignition, KnockControl
from simremap.ecu.strategies.overrun import Overrun
from simremap.ecu.strategies.powershift import Powershift
from simremap.ecu.strategies.rev_limiter import RevLimiter
from simremap.ecu.strategies.two_step import TwoStep

__all__ = [
    "Antilag",
    "BoostControl",
    "ClosedLoop",
    "Failsafe",
    "FuelStrategy",
    "Ignition",
    "KnockControl",
    "Overrun",
    "Powershift",
    "RevLimiter",
    "TickContext",
    "TwoStep",
    "speed_density_air_g",
]
