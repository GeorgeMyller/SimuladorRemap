"""Registo de todos os modelos de tabela no ``metadata`` partilhado.

Ponto de registo fixo: cada componente declara as suas tabelas em
``simremap/db/models/<módulo>.py``. Os módulos ainda inexistentes são ignorados
(só ``ModuleNotFoundError`` do próprio módulo); um erro dentro de um módulo
existente propaga-se. O Alembic (``env.py``) usa ``metadata`` daqui.

Módulos e donos: ``foundation`` (platform-foundation), ``dyno`` (dyno-bench),
``damage`` (knock-and-failure-model), ``calibration`` (ecu-core), ``profiles``
(ecu-profiles), ``datalog`` (telemetry-datalogger), ``scenarios`` (training-scenarios),
``career`` (modo carreira, 002).
"""

from __future__ import annotations

import importlib
from typing import Final

from simremap.db.base import metadata
from simremap.db.models import foundation

__all__ = ["MODEL_MODULES", "loaded_model_modules", "metadata"]

MODEL_MODULES: Final[tuple[str, ...]] = (
    "simremap.db.models.foundation",
    "simremap.db.models.dyno",
    "simremap.db.models.damage",
    "simremap.db.models.calibration",
    "simremap.db.models.profiles",
    "simremap.db.models.datalog",
    "simremap.db.models.scenarios",
    "simremap.db.models.career",
)

_loaded: list[str] = [foundation.__name__]
for _name in MODEL_MODULES[1:]:
    try:
        importlib.import_module(_name)
    except ModuleNotFoundError as _exc:
        if _exc.name != _name:
            raise
    else:
        _loaded.append(_name)


def loaded_model_modules() -> tuple[str, ...]:
    """Módulos de modelo efetivamente importados (para diagnóstico e testes)."""
    return tuple(_loaded)
