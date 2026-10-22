"""Fábricas partilhadas pelos testes do ecu-core (calibrações de fixture, sensores, hardware).

As calibrações são construídas aqui (sem depender do catálogo, ainda em criação):

- ``t2``/``t3``: dicionários de ``Table2D``/``Table3D`` com valor constante ou matriz;
- ``content_factory``: ``CalibrationContent`` validado a partir de tabelas e estratégias;
- ``full_content``: 8 cilindros com todas as estratégias e tabelas (benchmark, arbitragem);
- ``sensors``: ``SensorReadings`` válido com overrides;
- ``runtime_factory``: ``EcuRuntime`` compilado para um ``EcuHardwareConfig``;
- ``app``: app da API isolada do catálogo real (``ecu_stock_sources = []``: sem seed das
  calibrações de série) e com ``NullHooksProvider`` (regras do ecu-core sem a matriz de
  perfis; a integração com o ecu-profiles é testada em ``tests/profiles``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI

from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.ecu.calibration import CalibrationContent, parse_content
from simremap.ecu.compiled import EcuHardwareConfig, compile_calibration
from simremap.ecu.hooks import ProfileHooks
from simremap.ecu.limits import default_failsafe_rules
from simremap.ecu.ports import NullHooksProvider
from simremap.ecu.runtime import EcuRuntime
from simremap.physics.contracts import SensorReadings

RPM_AXIS = [1000.0 + 500.0 * i for i in range(16)]
MAP_AXIS = [20.0 + 25.0 * i for i in range(16)]

ContentFactory = Callable[..., CalibrationContent]
SensorFactory = Callable[..., SensorReadings]
RuntimeFactory = Callable[..., EcuRuntime]


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    application.state.ecu_stock_sources = []
    application.state.ecu_profile_hooks = NullHooksProvider()
    return application


def t3(
    table_id: str,
    kind: str,
    unit: str,
    value: float | list[list[float]],
    *,
    x: list[float] | None = None,
    y: list[float] | None = None,
    xq: str = "rpm",
    yq: str = "map_kpa",
    **extra: Any,
) -> dict[str, Any]:
    xs = x if x is not None else RPM_AXIS
    ys = y if y is not None else MAP_AXIS
    values = value if isinstance(value, list) else [[value] * len(xs) for _ in ys]
    return {
        "table_id": table_id,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": xq, "values": xs},
        "y": {"quantity": yq, "values": ys},
        "values": values,
        **extra,
    }


def t2(
    table_id: str,
    kind: str,
    unit: str,
    value: float | list[float],
    *,
    x: list[float],
    xq: str,
    **extra: Any,
) -> dict[str, Any]:
    values = value if isinstance(value, list) else [value] * len(x)
    return {
        "table_id": table_id,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": xq, "values": x},
        "values": values,
        **extra,
    }


def base_tables() -> dict[str, dict[str, Any]]:
    return {
        "ve": t3("ve", "ve", "%", 90.0),
        "lambda_target": t3("lambda_target", "lambda_target", "λ", 0.85),
        "ignition_base": t3("ignition_base", "ignition_base", "°BTDC", 25.0),
    }


def full_tables(n_cyl: int = 8) -> dict[str, dict[str, Any]]:
    tables = base_tables()
    tables.update(
        {
            "boost_target": t3(
                "boost_target", "boost_target", "kPa", 200.0, y=[0, 25, 50, 75, 100], yq="tps_pct"
            ),
            "boost_target_gear": t2(
                "boost_target_gear", "boost_target_gear", "kPa", 250.0, x=[1, 2, 3, 4], xq="gear"
            ),
            "boost_duty_base": t3(
                "boost_duty_base",
                "boost_duty_base",
                "%",
                40.0,
                y=[100, 200, 300],
                yq="boost_target_kpa",
            ),
            "ign_corr_iat": t2(
                "ign_corr_iat", "ign_corr_iat", "°", 0.0, x=[0, 50, 100], xq="iat_c"
            ),
            "ign_corr_ect": t2(
                "ign_corr_ect", "ign_corr_ect", "°", 0.0, x=[0, 50, 100], xq="ect_c"
            ),
            "fuel_corr_ect": t2(
                "fuel_corr_ect", "fuel_corr_ect", "%", 0.0, x=[0, 50, 100], xq="ect_c"
            ),
            "fuel_corr_iat": t2(
                "fuel_corr_iat", "fuel_corr_iat", "%", 0.0, x=[0, 50, 100], xq="iat_c"
            ),
            "accel_enrich": t2(
                "accel_enrich", "accel_enrich", "%", 10.0, x=[0, 500, 1000], xq="tps_rate_pct_s"
            ),
            "cranking_fuel": t2(
                "cranking_fuel", "cranking_fuel", "ms", 8.0, x=[-20, 80], xq="ect_c"
            ),
            "afterstart_enrich": t2(
                "afterstart_enrich", "afterstart_enrich", "%", 0.0, x=[-20, 80], xq="ect_c"
            ),
            "knock_threshold": t2(
                "knock_threshold", "knock_threshold", "adimensional", 0.3, x=[1000, 8000], xq="rpm"
            ),
            "inj_dead_time": t2(
                "inj_dead_time", "inj_dead_time", "ms", 0.9, x=[8, 16], xq="battery_v"
            ),
            "oil_pressure_min": t2(
                "oil_pressure_min", "oil_pressure_min", "kPa", 100.0, x=[1000, 7000], xq="rpm"
            ),
            "cam_intake_target": t3("cam_intake_target", "cam_intake_target", "°", 20.0),
            "cam_exhaust_target": t3("cam_exhaust_target", "cam_exhaust_target", "°", -10.0),
        }
    )
    for c in range(1, n_cyl + 1):
        tables[f"fuel_trim_{c}"] = t3(f"fuel_trim_{c}", "fuel_trim_cyl", "%", 0.0, cylinder=c)
        tables[f"ign_trim_{c}"] = t3(f"ign_trim_{c}", "ignition_trim_cyl", "°", 0.0, cylinder=c)
    return tables


def all_strategies(egt_max_c: float = 950.0) -> dict[str, dict[str, Any]]:
    strategies: dict[str, dict[str, Any]] = {
        kind: {"kind": kind}
        for kind in (
            "closed_loop",
            "knock_control",
            "boost_control",
            "rev_limiter",
            "two_step",
            "antilag",
            "powershift",
        )
    }
    strategies["overrun"] = {"kind": "overrun", "pops_enabled": True}
    strategies["failsafe"] = {
        "kind": "failsafe",
        "rules": [r.model_dump() for r in default_failsafe_rules(egt_max_c)],
    }
    return strategies


SENSOR_DEFAULTS: dict[str, Any] = {
    "t_sim_s": 0.0,
    "tick": 0,
    "rpm": 3000.0,
    "crank_angle_deg": 0.0,
    "cam_intake_deg": 0.0,
    "cam_exhaust_deg": 0.0,
    "map_kpa": 100.0,
    "baro_kpa": 100.0,
    "boost_pre_throttle_kpa": 100.0,
    "iat_c": 40.0,
    "ect_c": 90.0,
    "oil_temp_c": 95.0,
    "tps_pct": 50.0,
    "lambda_measured": 0.85,
    "egt_collector_c": 700.0,
    "fuel_pressure_kpa": 300.0,
    "battery_v": 14.0,
    "pedal_pct": 50.0,
    "gear": 3,
    "oil_pressure_kpa": 400.0,
}


@pytest.fixture
def content_factory() -> ContentFactory:
    def make(
        tables: dict[str, dict[str, Any]] | None = None,
        strategies: dict[str, dict[str, Any]] | None = None,
        **extra: Any,
    ) -> CalibrationContent:
        data: dict[str, Any] = {
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "ft-pro",
            "tables": tables if tables is not None else base_tables(),
            "strategies": strategies or {},
        }
        data.update(extra)
        return parse_content(data)

    return make


@pytest.fixture
def full_content(content_factory: ContentFactory) -> CalibrationContent:
    return content_factory(full_tables(8), all_strategies(), vehicle_id="muscle-v8-sc")


@pytest.fixture
def sensors() -> SensorFactory:
    def make(n_cyl: int = 4, **overrides: Any) -> SensorReadings:
        data = {
            **SENSOR_DEFAULTS,
            "egt_c": [650.0] * n_cyl,
            "knock_sensor_v": [0.05] * n_cyl,
            "knock_intensity": [0.0] * n_cyl,
        }
        data.update(overrides)
        return SensorReadings(**data)

    return make


def hardware(n_cyl: int = 4, **overrides: Any) -> EcuHardwareConfig:
    values: dict[str, Any] = {
        "n_cyl": n_cyl,
        "displacement_cc": 496.0 * n_cyl,
        "injector_flow_cc_min": 550.0,
        "afr_stoich": 13.2,
        "fuel_density_g_cc": 0.745,
    }
    values.update(overrides)
    return EcuHardwareConfig(**values)


@pytest.fixture
def runtime_factory() -> RuntimeFactory:
    def make(
        content: CalibrationContent,
        n_cyl: int = 4,
        hooks: ProfileHooks | None = None,
        hw: EcuHardwareConfig | None = None,
        **kwargs: Any,
    ) -> EcuRuntime:
        compiled = compile_calibration(content, n_cyl, calibration_id="cal-test")
        return EcuRuntime(compiled, hooks, hw or hardware(n_cyl), **kwargs)

    return make


class Builders:
    """Acesso às fábricas nos módulos de teste (``--import-mode=importlib``)."""

    t2 = staticmethod(t2)
    t3 = staticmethod(t3)
    base_tables = staticmethod(base_tables)
    full_tables = staticmethod(full_tables)
    all_strategies = staticmethod(all_strategies)
    hardware = staticmethod(hardware)
    rpm_axis = RPM_AXIS
    map_axis = MAP_AXIS


@pytest.fixture
def tb() -> type[Builders]:
    return Builders
