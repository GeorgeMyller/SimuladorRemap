"""Limites e padrões da ECU genérica (ecu-core Apêndice A, Apêndice E, RNF-05; D-BUS-05).

- ``TABLE_LIMITS``: dimensões, eixos padrão, unidade, mín/máx e live-tunable padrão por
  ``TableKind``. ``knock_threshold`` usa a escala de ``SensorReadings.knock_intensity``
  (0,0–1,0, D-BUS-05), não 0–10.
- Constantes de capacidade (128 tabelas, 1000 versões, 1024 células por PATCH).
- Faixas de sensores (EC-04, EC-15) e clamps finais dos comandos.
- ``default_failsafe_rules``: regras padrão do Apêndice E.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from simremap.ecu.contracts import AxisQuantity, FailsafeAction, FailsafeRule, TableKind

__all__ = [
    "ACTION_DEFAULTS",
    "CRANK_STOP_RPM",
    "DEFAULT_KNOCK_THRESHOLD",
    "FAILSAFE_RELEASE_HYSTERESIS",
    "FLEX_AFR_E27",
    "FLEX_AFR_E100",
    "FLEX_DENSITY_E27_G_CC",
    "FLEX_DENSITY_E100_G_CC",
    "IGNITION_MAX_DEG",
    "IGNITION_MIN_DEG",
    "LEAN_MIN_MAP_KPA",
    "LTFT_GRID_SIZE",
    "MAP_FALLBACK_KPA",
    "MAP_VALID_MAX_KPA",
    "MAP_VALID_MIN_KPA",
    "MAX_CALIBRATION_VERSIONS",
    "MAX_PATCH_CELLS",
    "MAX_PROFILE_PARAMS",
    "MAX_TABLES",
    "PARAMETRIC_ACTIONS",
    "PER_CYLINDER_KINDS",
    "PW_MAX_MS",
    "R_AIR_J_KG_K",
    "SENSOR_HOLD_S",
    "TABLE_LIMITS",
    "TEMP_MAX_C",
    "TEMP_MIN_C",
    "TableLimit",
    "ValueKind",
    "default_failsafe_rules",
    "table_limit",
]

# ----------------------------------------------------------------------------- capacidade
MAX_TABLES: Final = 128  # tabelas por calibração (RNF-05)
MAX_CALIBRATION_VERSIONS: Final = 1000  # versões por calibração (RNF-05, EC-14)
MAX_PATCH_CELLS: Final = 1024  # células por PATCH (RF-26)
MAX_PROFILE_PARAMS: Final = 64  # chaves de profile_params (RF-32)

# ----------------------------------------------------------------------------- física
R_AIR_J_KG_K: Final = 287.05  # J/(kg·K)
IGNITION_MIN_DEG: Final = -20.0  # ° BTDC (RF-11)
IGNITION_MAX_DEG: Final = 60.0  # ° BTDC (RF-11)
PW_MAX_MS: Final = 50.0  # ms, limite de ActuatorCommands.injector_pw_ms

# ----------------------------------------------------------------------------- sensores
MAP_VALID_MIN_KPA: Final = 5.0  # kPa abs (EC-04)
MAP_VALID_MAX_KPA: Final = 600.0  # kPa abs (EC-04)
MAP_FALLBACK_KPA: Final = 100.0  # kPa abs após SENSOR_HOLD_S (EC-04)
TEMP_MIN_C: Final = -40.0  # °C (EC-15)
TEMP_MAX_C: Final = 150.0  # °C (EC-15)
SENSOR_HOLD_S: Final = 0.05  # s de último valor válido antes da substituição
CRANK_STOP_RPM: Final = 500.0  # rev/min: motor parado para latch_until_stop

# ----------------------------------------------------------------------------- estratégias
DEFAULT_KNOCK_THRESHOLD: Final = 0.2  # (-) sem tabela knock_threshold (escala 0–1)
LTFT_GRID_SIZE: Final = 8  # grade RPM × MAP de 8×8 (RF-10)
LEAN_MIN_MAP_KPA: Final = 150.0  # kPa: regra lean_under_load só com carga (Apêndice E)

# ----------------------------------------------------------------------------- flex
# Âncoras do sensor flex (firmware da ECU): AFR estequiométrico e densidade de E27 e E100
# do catálogo (``catalog/data/fuels``; o teste de paridade garante a igualdade).
FLEX_AFR_E27: Final = 13.2  # (-)
FLEX_AFR_E100: Final = 9.0  # (-)
FLEX_DENSITY_E27_G_CC: Final = 0.745  # g/cc
FLEX_DENSITY_E100_G_CC: Final = 0.789  # g/cc

Dims = Literal[2, 3]


@dataclass(frozen=True, slots=True)
class TableLimit:
    """Linha do Apêndice A."""

    kind: TableKind
    dims: Dims
    x: AxisQuantity
    y: AxisQuantity | None
    unit: str
    min: float
    max: float
    live_tunable: bool


def _l(
    kind: TableKind,
    x: AxisQuantity,
    y: AxisQuantity | None,
    unit: str,
    low: float,
    high: float,
    live: bool,
) -> TableLimit:
    return TableLimit(kind, 3 if y is not None else 2, x, y, unit, low, high, live)


_Q = AxisQuantity
_K = TableKind

TABLE_LIMITS: Final[dict[TableKind, TableLimit]] = {
    lim.kind: lim
    for lim in (
        _l(_K.VE, _Q.RPM, _Q.MAP_KPA, "%", 0.0, 150.0, True),
        _l(_K.INJ_BASE_MS, _Q.RPM, _Q.MAP_KPA, "ms", 0.0, 50.0, True),
        _l(_K.LAMBDA_TARGET, _Q.RPM, _Q.MAP_KPA, "λ", 0.65, 1.30, True),
        _l(_K.IGNITION_BASE, _Q.RPM, _Q.MAP_KPA, "°BTDC", -20.0, 60.0, True),
        _l(_K.IGNITION_TRIM_CYL, _Q.RPM, _Q.MAP_KPA, "°", -15.0, 15.0, True),
        _l(_K.FUEL_TRIM_CYL, _Q.RPM, _Q.MAP_KPA, "%", -25.0, 25.0, True),
        _l(_K.IGN_CORR_IAT, _Q.IAT_C, None, "°", -15.0, 10.0, True),
        _l(_K.IGN_CORR_ECT, _Q.ECT_C, None, "°", -15.0, 10.0, True),
        _l(_K.FUEL_CORR_ECT, _Q.ECT_C, None, "%", -20.0, 100.0, False),
        _l(_K.FUEL_CORR_IAT, _Q.IAT_C, None, "%", -30.0, 30.0, False),
        _l(_K.ACCEL_ENRICH, _Q.TPS_RATE_PCT_S, None, "%", 0.0, 200.0, False),
        _l(_K.CRANKING_FUEL, _Q.ECT_C, None, "ms", 0.0, 50.0, False),
        _l(_K.AFTERSTART_ENRICH, _Q.ECT_C, None, "%", 0.0, 100.0, False),
        _l(_K.INJ_DEAD_TIME, _Q.BATTERY_V, None, "ms", 0.0, 5.0, False),
        _l(_K.BOOST_TARGET, _Q.RPM, _Q.TPS_PCT, "kPa", 80.0, 400.0, True),
        _l(_K.BOOST_TARGET_GEAR, _Q.GEAR, None, "kPa", 80.0, 400.0, True),
        _l(_K.BOOST_DUTY_BASE, _Q.RPM, _Q.BOOST_TARGET_KPA, "%", 0.0, 100.0, False),
        # D-BUS-05: escala de knock_intensity (0–1), não 0–10.
        _l(_K.KNOCK_THRESHOLD, _Q.RPM, None, "adimensional", 0.0, 1.0, False),
        _l(_K.OIL_PRESSURE_MIN, _Q.RPM, None, "kPa", 0.0, 1000.0, False),
        _l(_K.CAM_INTAKE_TARGET, _Q.RPM, _Q.MAP_KPA, "°", -60.0, 60.0, True),
        _l(_K.CAM_EXHAUST_TARGET, _Q.RPM, _Q.MAP_KPA, "°", -60.0, 60.0, True),
        _l(_K.FLEX_IGN_ADD, _Q.ETHANOL_PCT, None, "°", -10.0, 15.0, True),
        _l(_K.FLEX_BOOST_ADD, _Q.ETHANOL_PCT, None, "kPa", -50.0, 100.0, True),
        _l(_K.TORQUE_REQUEST, _Q.RPM, _Q.PEDAL_PCT, "N·m", 0.0, 1500.0, True),
        _l(_K.TORQUE_LIMIT, _Q.RPM, None, "N·m", 0.0, 1500.0, True),
        _l(_K.TORQUE_LIMIT_GEAR, _Q.GEAR, None, "N·m", 0.0, 1500.0, True),
        _l(_K.TORQUE_OPTIMAL, _Q.RPM, _Q.LOAD_PCT, "N·m", 0.0, 1500.0, False),
        _l(_K.IGNITION_OPTIMAL, _Q.RPM, _Q.LOAD_PCT, "°BTDC", -20.0, 60.0, True),
        _l(_K.IGNITION_EFFICIENCY, _Q.IGN_DELTA_DEG, None, "adimensional", 0.0, 1.0, False),
        _l(_K.OEM_PRESSURE_TARGET, _Q.RPM, _Q.LOAD_PCT, "kPa", 80.0, 400.0, True),
        _l(_K.FRICTION_TORQUE, _Q.RPM, _Q.ECT_C, "N·m", 0.0, 300.0, False),
        _l(_K.LAMBDA_COMPONENT_PROTECTION, _Q.EGT_C, None, "λ", 0.65, 1.30, True),
    )
}

PER_CYLINDER_KINDS: Final = frozenset({TableKind.IGNITION_TRIM_CYL, TableKind.FUEL_TRIM_CYL})
"""Tipos com uma tabela por cilindro (campo ``cylinder`` obrigatório)."""


def table_limit(kind: TableKind | str) -> TableLimit:
    """Linha do Apêndice A do ``kind``."""
    return TABLE_LIMITS[TableKind(kind)]


# ----------------------------------------------------------------------------- failsafe

ValueKind = Literal["kpa", "ratio", "rpm", "lambda_delta", "deg"]

ACTION_DEFAULTS: Final[dict[str, dict[str, tuple[ValueKind, float]]]] = {
    "egt_high": {"boost_reduce": ("kpa", 30.0), "enrich": ("lambda_delta", -0.05)},
    "egt_critical": {"rev_limit_reduce": ("rpm", 4000.0)},
    "ect_high": {"boost_reduce": ("ratio", 0.5), "rev_limit_reduce": ("rpm", 4500.0)},
    "sensor_fault": {"rev_limit_reduce": ("rpm", 3000.0)},
    "*": {
        "boost_reduce": ("kpa", 30.0),
        "rev_limit_reduce": ("rpm", 4000.0),
        "enrich": ("lambda_delta", -0.05),
        "ignition_retard": ("deg", 5.0),
    },
}
"""Valores das ações parametrizadas por regra (Apêndice E).

``FailsafeRule`` tem um só ``action_value``: ele vale para a PRIMEIRA ação
parametrizada da regra (na unidade da ação: kPa, rpm, Δλ ou graus); as outras ações
usam estes padrões. ``ratio`` (só ``ect_high``) reduz o alvo de boost a uma fração.
"""

FAILSAFE_RELEASE_HYSTERESIS: Final[dict[str, float]] = {
    "egt_high": 20.0,  # °C: liberação abaixo do limiar − 20 °C
    "egt_critical": 0.0,
    "lean_under_load": 0.0,
    "ect_high": 5.0,  # °C: liberação abaixo de 105 °C com limiar 110 °C
    "oil_pressure_low": 0.0,
    "overspeed": 300.0,  # rev/min: liberação abaixo de overspeed_rpm − 300
    "sensor_fault": 0.0,
}

PARAMETRIC_ACTIONS: Final[frozenset[str]] = frozenset(
    {"boost_reduce", "rev_limit_reduce", "enrich", "ignition_retard"}
)


def _rule(
    rule_id: str,
    threshold: float,
    confirm_s: float,
    actions: list[FailsafeAction],
    action_value: float,
    release_s: float,
    *,
    latch: bool = False,
) -> FailsafeRule:
    return FailsafeRule.model_validate(
        {
            "rule_id": rule_id,
            "threshold": threshold,
            "confirm_s": confirm_s,
            "actions": actions,
            "action_value": action_value,
            "release_s": release_s,
            "latch_until_stop": latch,
        }
    )


def default_failsafe_rules(egt_max_c: float, overspeed_rpm: float = 7500.0) -> list[FailsafeRule]:
    """Regras padrão do Apêndice E (``egt_max_c`` vem de ``MechanicalLimits``)."""
    return [
        _rule("egt_high", egt_max_c, 0.5, ["boost_reduce", "enrich"], 30.0, 2.0),
        _rule(
            "egt_critical", egt_max_c + 30.0, 0.2, ["boost_cut", "rev_limit_reduce"], 4000.0, 5.0
        ),
        _rule("lean_under_load", 0.10, 0.3, ["boost_cut"], 0.0, 2.0),
        _rule("ect_high", 110.0, 1.0, ["rev_limit_reduce", "boost_reduce"], 4500.0, 10.0),
        _rule("oil_pressure_low", 0.0, 0.5, ["fuel_cut"], 0.0, 0.0, latch=True),
        _rule("overspeed", overspeed_rpm, 0.0, ["fuel_cut"], 0.0, 0.0),
        _rule("sensor_fault", 1.0, 0.05, ["boost_cut", "rev_limit_reduce"], 3000.0, 2.0),
    ]
