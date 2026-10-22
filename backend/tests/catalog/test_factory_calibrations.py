"""Calibrações de fábrica (RF-19, RF-20; T038): schema ``Calibration`` e lógica OEM por torque.

O modelo ``Calibration`` do ecu-core (``ecu/calibration.py``) ainda não existe nesta onda;
a estrutura é verificada contra os contratos já publicados em ``simremap.ecu.contracts``
(``Axis``, ``StrategyConfig``, ``TableKind``) e contra o Apêndice A do ecu-core.
"""

from __future__ import annotations

import itertools
import zlib
from typing import Any

import pytest
from pydantic import TypeAdapter

from simremap.catalog.canonical import canonical_sha256
from simremap.catalog.contracts import Grid2D
from simremap.catalog.grids import interp2d, interp_linear
from simremap.catalog.loader import Catalog
from simremap.ecu.contracts import Axis, StrategyConfig, TableKind

APPENDIX_A: dict[str, tuple[str, float, float]] = {
    "ve": ("%", 0, 150), "inj_base_ms": ("ms", 0, 50), "lambda_target": ("λ", 0.65, 1.30),
    "ignition_base": ("°BTDC", -20, 60), "ign_corr_iat": ("°", -15, 10),
    "fuel_corr_ect": ("%", -20, 100), "accel_enrich": ("%", 0, 200),
    "cranking_fuel": ("ms", 0, 50), "afterstart_enrich": ("%", 0, 100),
    "inj_dead_time": ("ms", 0, 5), "boost_target": ("kPa", 80, 400),
    "boost_target_gear": ("kPa", 80, 400), "boost_duty_base": ("%", 0, 100),
    "knock_threshold": ("adimensional", 0, 1), "oil_pressure_min": ("kPa", 0, 1000),
    "cam_intake_target": ("°", -60, 60), "cam_exhaust_target": ("°", -60, 60),
    "torque_request": ("N·m", 0, 1500), "torque_limit": ("N·m", 0, 1500),
    "torque_limit_gear": ("N·m", 0, 1500), "torque_optimal": ("N·m", 0, 1500),
    "ignition_optimal": ("°BTDC", -20, 60), "ignition_efficiency": ("adimensional", 0, 1),
    "oem_pressure_target": ("kPa", 80, 400), "friction_torque": ("N·m", 0, 300),
    "lambda_component_protection": ("λ", 0.65, 1.30),
}  # fmt: skip
OEM_REQUIRED = {
    "torque_request", "torque_limit", "torque_limit_gear", "torque_optimal", "ignition_optimal",
    "ignition_efficiency", "ignition_base", "oem_pressure_target", "friction_torque",
    "lambda_component_protection", "lambda_target", "ve", "inj_dead_time",
}  # fmt: skip
STRATEGY = TypeAdapter(StrategyConfig)


def _payloads(catalog: Catalog) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (vid, pid, dict(payload))
        for vid, entry in catalog.vehicles.items()
        for pid, payload in entry.calibrations.items()
    ]


def _plain(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _grid(table: dict[str, Any]) -> Grid2D:
    return Grid2D(
        x_name="rpm", x_values=list(table["x"]["values"]), y_name="map_kpa",
        y_values=list(table["y"]["values"]), z_values=[list(r) for r in table["values"]],
    )  # fmt: skip


@pytest.fixture(scope="module")
def calibrations(real_catalog: Catalog) -> list[tuple[str, str, dict[str, Any]]]:
    return [(vid, pid, _plain(p)) for vid, pid, p in _payloads(real_catalog)]


def test_inventory(calibrations: list[tuple[str, str, dict[str, Any]]]) -> None:
    assert sorted((v, p) for v, p, _ in calibrations) == [
        ("classic-20t-swap", "ft-pro"),
        ("classic-20t-swap", "oem-stage"),
        ("coupe-30t-i6", "oem-stage"),
        ("hatch-20t-gdi", "oem-stage"),
        ("muscle-v8-sc", "oem-stage"),
    ]


def test_schema(calibrations: list[tuple[str, str, dict[str, Any]]]) -> None:
    keys = {"calibration_id", "vehicle_id", "profile_id", "version", "parent_version",
            "fuel_model", "tables", "strategies", "profile_params", "metadata", "content_hash",
            "created_at"}  # fmt: skip
    for vid, pid, cal in calibrations:
        assert set(cal) == keys
        assert cal["calibration_id"] == f"stock-{vid}-{pid}"
        assert (cal["version"], cal["parent_version"]) == (1, None)
        assert cal["metadata"]["source"] == "oem_stock"
        assert len(cal["tables"]) <= 128
        for key, table in cal["tables"].items():
            assert key == table["table_id"] == table["kind"]
            TableKind(table["kind"])
            unit, low, high = APPENDIX_A[table["kind"]]
            assert table["unit"] == unit
            x = Axis.model_validate(table["x"])
            if table["dims"] == 3:
                y = Axis.model_validate(table["y"])
                assert len(table["values"]) == len(y.values)
                rows = table["values"]
            else:
                assert "y" not in table
                rows = [table["values"]]
            for row in rows:
                assert len(row) == len(x.values)
                assert all(low <= v <= high for v in row), (vid, pid, key)
        for key, strategy in cal["strategies"].items():
            assert STRATEGY.validate_python(strategy).kind == key


def test_content_hash_and_checksum(calibrations: list[tuple[str, str, dict[str, Any]]]) -> None:
    for _vid, pid, cal in calibrations:
        payload = {k: cal[k] for k in ("vehicle_id", "profile_id", "fuel_model", "tables",
                                       "strategies", "profile_params")}  # fmt: skip
        assert cal["content_hash"] == canonical_sha256(payload)
        if pid == "oem-stage":
            crc = zlib.crc32((cal["content_hash"] + ":oem-stage").encode()) & 0xFFFFFFFF
            assert cal["metadata"]["extra"]["oem_checksum"] == f"{crc:08x}"
            assert cal["profile_params"] == {
                "torque_monitoring": True, "component_protection": True,
                "knock_protection": True, "overboost_protection": True, "checksum_check": True,
            }  # fmt: skip


def test_oem_tables_and_strategies(calibrations: list[tuple[str, str, dict[str, Any]]]) -> None:
    for _vid, pid, cal in calibrations:
        if pid != "oem-stage":
            continue
        assert OEM_REQUIRED <= set(cal["tables"])
        assert cal["fuel_model"]["mode"] == "profile_air_model"
        assert not {"two_step", "antilag", "powershift"} & set(cal["strategies"])
        assert {"closed_loop", "knock_control", "boost_control", "rev_limiter", "failsafe"} <= set(
            cal["strategies"]
        )
        assert not {"torque_request"} - set(cal["tables"])


@pytest.mark.parametrize(
    "vid", ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]
)
def test_oem_torque_path_matches_reference(real_catalog: Catalog, vid: str) -> None:
    """Caminho de torque (ecu-profiles Apêndice C) a plena carga reproduz a curva de série."""
    entry = real_catalog.vehicles[vid]
    cal = _plain(entry.calibrations["oem-stage"])
    t = cal["tables"]
    curve = entry.curves[0]
    schedule = {p.rpm: p for p in entry.spec.reference_command_schedule.points}
    rpm_axis = t["torque_limit"]["x"]["values"]
    loads = t["torque_optimal"]["y"]["values"]
    rows_opt = t["torque_optimal"]["values"]
    for j in range(len(t["torque_optimal"]["x"]["values"])):  # crescente na carga
        column = [rows_opt[i][j] for i in range(len(loads))]
        assert all(b > a for a, b in itertools.pairwise(column))
    eff = t["ignition_efficiency"]
    assert all(b < a for a, b in itertools.pairwise(eff["values"]))
    lim = entry.spec.mechanical_limits
    assert cal["strategies"]["rev_limiter"]["hard_rpm"] == lim.rev_limit_rpm
    for point in curve.points:
        rpm = point.rpm
        assert point.torque_crank_nm is not None
        limit = interp_linear(rpm_axis, t["torque_limit"]["values"], rpm)
        assert limit == pytest.approx(point.torque_crank_nm, rel=0.01)
        # pedido a 100 % de pedal acima do limite: a limitação vence a plena carga
        request = t["torque_request"]["values"][-1][0]
        assert request > limit
        # carga alvo pela inversão de torque_optimal · η_base = T_lim + atrito (90 °C)
        friction = interp2d(_grid(t["friction_torque"]), rpm, 90.0)
        t_ind = limit + friction

        def possible(load: float, rpm: float = rpm) -> float:
            topt = interp2d(_grid(t["torque_optimal"]), rpm, load)
            delta = interp2d(_grid(t["ignition_optimal"]), rpm, load) - interp2d(
                _grid(t["ignition_base"]), rpm, load
            )
            assert delta >= -1e-9
            return topt * interp_linear(eff["x"]["values"], eff["values"], delta)

        lo, hi = loads[0], loads[-1]
        assert possible(hi) > t_ind
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if possible(mid) < t_ind else (lo, mid)
        pressure = interp2d(_grid(t["oem_pressure_target"]), rpm, lo)
        assert pressure == pytest.approx(schedule[rpm].map_target_kpa, rel=0.04)
        lam = interp2d(_grid(t["lambda_target"]), rpm, schedule[rpm].map_target_kpa)
        assert lam == pytest.approx(schedule[rpm].lambda_target, abs=0.02)


def test_ftpro_base_map(real_catalog: Catalog) -> None:
    entry = real_catalog.vehicles["classic-20t-swap"]
    cal = _plain(entry.calibrations["ft-pro"])
    assert cal["fuel_model"]["mode"] == "direct_pulse_ms"
    assert {"ve", "inj_base_ms", "lambda_target", "ignition_base", "inj_dead_time"} <= set(
        cal["tables"]
    )
    strategies = cal["strategies"]
    assert not strategies["two_step"]["enabled"]
    assert not strategies["antilag"]["enabled"]
    assert strategies["antilag"]["activation"] == "switch"
    assert not strategies["powershift"]["enabled"]
    assert not strategies["overrun"]["pops_enabled"]
    assert strategies["boost_control"]["overboost_kpa"] == 260.0
    assert strategies["rev_limiter"]["hard_rpm"] == 7500.0
    rpm_axis = cal["tables"]["inj_base_ms"]["x"]["values"]
    assert (rpm_axis[0], rpm_axis[-1]) == (500.0, 7500.0)
    inj = cal["tables"]["inj_base_ms"]["values"]
    duty = max(inj[-1]) / (120_000.0 / rpm_axis[-1]) * 100.0
    assert duty < 85.0  # bico de 2000 cm³/min não satura no mapa base
    ign = cal["tables"]["ignition_base"]
    assert all(5.0 <= v <= 35.0 for row in ign["values"] for v in row)
