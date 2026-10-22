"""Estratégia ``vvt`` e compensação flex no ``EcuRuntime`` (002 RF-11, RF-18; T020, T023).

- sem a estratégia, os alvos de came são as tabelas (RF-31 preservado);
- com a estratégia: alvos 0 com ECT abaixo do limiar, offsets somados e limite de taxa;
- sensor flex: pulso escalado por ``AFR_stock / AFR_blend``; ``flex_ign_add`` e
  ``flex_boost_add`` somam-se ao avanço e ao alvo de boost; sem sensor nada muda.
"""

from __future__ import annotations

from typing import Any

import pytest

from simremap.ecu.limits import (
    FLEX_AFR_E27,
    FLEX_AFR_E100,
    FLEX_DENSITY_E27_G_CC,
    FLEX_DENSITY_E100_G_CC,
)
from simremap.ecu.runtime import EcuRuntime
from simremap.physics.fuel_blend import blend_afr_stoich, blend_density

DT = 0.001
ETH_AXIS = [27.0, 50.0, 85.0, 100.0]


def _cams(tb: Any) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = tb.base_tables()
    tables["cam_intake_target"] = tb.t3("cam_intake_target", "cam_intake_target", "°", 30.0)
    tables["cam_exhaust_target"] = tb.t3("cam_exhaust_target", "cam_exhaust_target", "°", 12.0)
    return tables


def _run(rt: EcuRuntime, sensors: Any, n: int, **over: Any) -> Any:
    result = None
    for i in range(n):
        result = rt.step(sensors(t_sim_s=i * DT, tick=i, **over), DT)
    return result


def test_without_strategy_targets_follow_tables(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = runtime_factory(content_factory(_cams(tb)))
    res = _run(rt, sensors, 1, ect_c=10.0)
    assert res.commands.vvt_intake_target_deg == pytest.approx(30.0)
    assert res.commands.vvt_exhaust_target_deg == pytest.approx(12.0)
    assert "vvt" not in res.status.active_strategies


def test_cold_engine_parks_cams(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    strategies = {"vvt": {"kind": "vvt", "min_ect_c": 60.0}}
    rt = runtime_factory(content_factory(_cams(tb), strategies))
    res = _run(rt, sensors, 500, ect_c=20.0)
    assert res.commands.vvt_intake_target_deg == 0.0
    assert res.commands.vvt_exhaust_target_deg == 0.0
    assert "vvt" in res.status.active_strategies


def test_warm_engine_reaches_table_plus_offset_with_rate_limit(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    strategies = {
        "vvt": {
            "kind": "vvt",
            "min_ect_c": 60.0,
            "max_rate_deg_s": 100.0,
            "intake_offset_deg": 4.0,
            "exhaust_offset_deg": -2.0,
        }
    }
    rt = runtime_factory(content_factory(_cams(tb), strategies))
    first = _run(rt, sensors, 1, ect_c=90.0)
    assert first.commands.vvt_intake_target_deg == pytest.approx(100.0 * DT)
    settled = _run(rt, sensors, 400, ect_c=90.0)
    assert settled.commands.vvt_intake_target_deg == pytest.approx(34.0)
    assert settled.commands.vvt_exhaust_target_deg == pytest.approx(10.0)


def test_disabled_strategy_keeps_tables(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = runtime_factory(content_factory(_cams(tb), {"vvt": {"kind": "vvt", "enabled": False}}))
    res = _run(rt, sensors, 1, ect_c=10.0)
    assert res.commands.vvt_intake_target_deg == pytest.approx(30.0)


def _flex_tables(tb: Any) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = tb.base_tables()
    tables["flex_ign_add"] = tb.t2(
        "flex_ign_add", "flex_ign_add", "°", [0.0, 2.0, 5.0, 6.0], x=ETH_AXIS, xq="ethanol_pct"
    )
    tables["flex_boost_add"] = tb.t2(
        "flex_boost_add", "flex_boost_add", "kPa", [0.0, 5.0, 20.0, 25.0], x=ETH_AXIS,
        xq="ethanol_pct",
    )  # fmt: skip
    tables["boost_target"] = tb.t3(
        "boost_target", "boost_target", "kPa", 180.0, y=[0, 50, 100], yq="tps_pct"
    )
    return tables


def test_flex_scales_pulse_by_stoich_ratio(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    content = content_factory(tb.base_tables())
    base = _run(runtime_factory(content), sensors, 5, ect_c=90.0)
    e27 = _run(runtime_factory(content), sensors, 5, ect_c=90.0, ethanol_pct=27.0)
    e85 = _run(runtime_factory(content), sensors, 5, ect_c=90.0, ethanol_pct=85.0)
    # Hardware de série em E27 (AFR 13,2): o sensor em 27 % não muda nada.
    assert e27.status.fuel_mass_mg == pytest.approx(base.status.fuel_mass_mg)
    ratio = FLEX_AFR_E27 / blend_afr_stoich(85.0, FLEX_AFR_E27, FLEX_AFR_E100)
    assert e85.status.fuel_mass_mg[0] == pytest.approx(base.status.fuel_mass_mg[0] * ratio)
    assert e85.commands.injector_pw_ms[0] > e27.commands.injector_pw_ms[0]
    # Abertura do bico: massa ×ratio e volume ×ρ_E27/ρ_E85 (o bico mede volume).
    rho = blend_density(85.0, FLEX_DENSITY_E27_G_CC, FLEX_DENSITY_E100_G_CC)
    dead = e27.commands.injector_pw_ms[0] - (
        base.status.fuel_mass_mg[0] / 1000.0 / (550.0 * 0.745 / 60000.0)
    )
    open_e85 = e85.commands.injector_pw_ms[0] - dead
    open_e27 = e27.commands.injector_pw_ms[0] - dead
    assert open_e85 == pytest.approx(open_e27 * ratio * FLEX_DENSITY_E27_G_CC / rho)


def test_flex_tables_add_ignition_and_boost(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    content = content_factory(_flex_tables(tb))
    plain = _run(runtime_factory(content), sensors, 3, ect_c=90.0, tps_pct=100.0)
    flex = _run(runtime_factory(content), sensors, 3, ect_c=90.0, tps_pct=100.0, ethanol_pct=85.0)
    assert flex.commands.ignition_advance_deg[0] == pytest.approx(
        plain.commands.ignition_advance_deg[0] + 5.0
    )
    assert flex.status.boost_target_kpa == pytest.approx(plain.status.boost_target_kpa + 20.0)
