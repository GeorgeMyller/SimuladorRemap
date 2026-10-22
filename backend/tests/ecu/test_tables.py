"""Tabelas e interpolação com clamp (ecu-core RF-01 a RF-03, Apêndice A e B; T138)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simremap.ecu.contracts import Axis, EcuValidationError
from simremap.ecu.limits import TABLE_LIMITS, table_limit
from simremap.ecu.tables import (
    AnyTable,
    Table2D,
    Table3D,
    ecu_error_from_validation,
    interp1,
    interp2,
    table_view,
)

ANY_TABLE: TypeAdapter[Table2D | Table3D] = TypeAdapter(AnyTable)


def _code(exc: pytest.ExceptionInfo[ValidationError]) -> EcuValidationError:
    err = ecu_error_from_validation(exc.value)
    assert err is not None
    return err


# --------------------------------------------------------------------------- RF-01


def test_axis_non_monotonic_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Axis(quantity="rpm", values=[500, 1000, 1000])  # type: ignore[arg-type]
    assert _code(exc).code == "TABLE_AXIS_NOT_MONOTONIC"


def test_axis_33_points_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Axis(quantity="rpm", values=[float(i) for i in range(33)])  # type: ignore[arg-type]
    assert _code(exc).code == "TABLE_SIZE_EXCEEDED"


def test_axis_nan_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Axis(quantity="rpm", values=[1.0, float("nan")])  # type: ignore[arg-type]
    assert _code(exc).code == "TABLE_VALUE_NOT_FINITE"


def test_axis_32_points_accepted() -> None:
    axis = Axis(quantity="map_kpa", values=[float(i) for i in range(32)])  # type: ignore[arg-type]
    assert len(axis.values) == 32
    assert axis.unit == "kPa"


# --------------------------------------------------------------------------- RF-02


def test_ve_cell_151_out_of_range_with_row_col(tb: Any) -> None:
    data = tb.t3("ve", "ve", "%", 90.0)
    data["values"][4][9] = 151.0
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(data)
    err = _code(exc)
    assert err.code == "TABLE_VALUE_OUT_OF_RANGE"
    assert err.detail == {
        "table_id": "ve",
        "row": 4,
        "col": 9,
        "value": 151.0,
        "min": 0.0,
        "max": 150.0,
    }


def test_shape_mismatch_16x15_with_16_point_axis(tb: Any) -> None:
    data = tb.t3("ve", "ve", "%", 90.0)
    data["values"] = [[90.0] * 15 for _ in range(16)]
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(data)
    assert _code(exc).code == "TABLE_SHAPE_MISMATCH"


def test_2d_shape_mismatch(tb: Any) -> None:
    data = tb.t2("ign_corr_iat", "ign_corr_iat", "°", [0.0, 1.0], x=[0, 50, 100], xq="iat_c")
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(data)
    assert _code(exc).code == "TABLE_SHAPE_MISMATCH"


def test_unit_mismatch(tb: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(tb.t3("ve", "ve", "ms", 90.0))
    err = _code(exc)
    assert err.code == "TABLE_UNIT_MISMATCH"
    assert err.detail["expected"] == "%"


def test_value_not_finite(tb: Any) -> None:
    data = tb.t3("ve", "ve", "%", 90.0)
    data["values"][0][0] = float("inf")
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(data)
    assert _code(exc).code == "TABLE_VALUE_NOT_FINITE"


def test_dims_must_match_kind(tb: Any) -> None:
    data = tb.t2("ve", "ve", "%", 90.0, x=[1000, 2000], xq="rpm")
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(data)
    err = _code(exc)
    assert err.code == "TABLE_SHAPE_MISMATCH"
    assert err.detail["reason"] == "dims"


def test_cylinder_required_only_for_trim_kinds(tb: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(tb.t3("fuel_trim_1", "fuel_trim_cyl", "%", 0.0))
    assert _code(exc).detail["reason"] == "cylinder"
    with pytest.raises(ValidationError):
        ANY_TABLE.validate_python(tb.t3("ve", "ve", "%", 90.0, cylinder=1))
    ok = ANY_TABLE.validate_python(tb.t3("fuel_trim_1", "fuel_trim_cyl", "%", 0.0, cylinder=1))
    assert ok.cylinder == 1


def test_knock_threshold_uses_knock_intensity_scale(tb: Any) -> None:
    """D-BUS-05: limite de knock_threshold é 0,0–1,0."""
    assert (TABLE_LIMITS[table_limit("knock_threshold").kind].max) == 1.0
    with pytest.raises(ValidationError) as exc:
        ANY_TABLE.validate_python(
            tb.t2("kt", "knock_threshold", "adimensional", 1.5, x=[1000, 7000], xq="rpm")
        )
    assert _code(exc).code == "TABLE_VALUE_OUT_OF_RANGE"


def test_live_tunable_default_and_never_forced(tb: Any) -> None:
    ve = ANY_TABLE.validate_python(tb.t3("ve", "ve", "%", 90.0))
    assert ve.live_tunable is True
    off = ANY_TABLE.validate_python(tb.t3("ve", "ve", "%", 90.0, live_tunable=False))
    assert off.live_tunable is False
    duty = ANY_TABLE.validate_python(
        tb.t3(
            "bd",
            "boost_duty_base",
            "%",
            40.0,
            y=[100, 200],
            yq="boost_target_kpa",
            live_tunable=True,
        )
    )
    assert duty.live_tunable is False  # Apêndice A: boost_duty_base não é live-tunable


def test_discriminator_infers_dims(tb: Any) -> None:
    three = ANY_TABLE.validate_python(tb.t3("ve", "ve", "%", 90.0))
    two = ANY_TABLE.validate_python(
        tb.t2("inj_dead_time", "inj_dead_time", "ms", 0.9, x=[8, 16], xq="battery_v")
    )
    assert isinstance(three, Table3D) and three.dims == 3
    assert isinstance(two, Table2D) and two.dims == 2
    assert three.n_cells == 256 and two.n_cells == 2


def test_every_kind_has_limits() -> None:
    from simremap.ecu.contracts import TableKind

    assert set(TABLE_LIMITS) == set(TableKind)
    for lim in TABLE_LIMITS.values():
        assert lim.min < lim.max
        assert (lim.dims == 3) == (lim.y is not None)


# --------------------------------------------------------------------------- RF-03


def test_bilinear_reference_case() -> None:
    """Apêndice B: eixos (2000, 2500) × (50, 100), z ((10, 20), (30, 40)) ⇒ 25,0 em (2250, 75)."""
    assert abs(interp2([2000, 2500], [50, 100], [[10, 20], [30, 40]], 2250, 75) - 25.0) < 1e-9


def test_bilinear_clamps_outside_axes() -> None:
    xs, ys, z = [2000.0, 2500.0], [50.0, 100.0], [[10.0, 20.0], [30.0, 40.0]]
    assert interp2(xs, ys, z, 0, 0) == 10.0
    assert interp2(xs, ys, z, 9000, 0) == 20.0
    assert interp2(xs, ys, z, 0, 500) == 30.0
    assert interp2(xs, ys, z, 9000, 500) == 40.0
    assert interp2(xs, ys, z, 2250, 500) == pytest.approx(35.0)
    assert interp2(xs, ys, z, float("nan"), 50) == 10.0


def test_linear_with_clamp() -> None:
    xs, vs = [0.0, 10.0, 20.0], [0.0, 100.0, 50.0]
    assert interp1(xs, vs, 5.0) == 50.0
    assert interp1(xs, vs, 15.0) == 75.0
    assert interp1(xs, vs, -5.0) == 0.0
    assert interp1(xs, vs, 25.0) == 50.0
    assert interp1(xs, vs, 10.0) == 100.0
    assert interp1(xs, vs, float("nan")) == 0.0


def test_table_lookup_methods(tb: Any) -> None:
    data = tb.t3("ve", "ve", "%", [[10.0, 20.0], [30.0, 40.0]], x=[2000, 2500], y=[50, 100])
    table = ANY_TABLE.validate_python(data)
    assert isinstance(table, Table3D)
    assert table.lookup(2250, 75) == pytest.approx(25.0, abs=1e-9)
    two = ANY_TABLE.validate_python(
        tb.t2("inj_dead_time", "inj_dead_time", "ms", [1.5, 0.5], x=[8, 16], xq="battery_v")
    )
    assert isinstance(two, Table2D)
    assert two.lookup(12) == pytest.approx(1.0)


@given(
    st.lists(st.floats(-1e3, 1e3), min_size=2, max_size=8),
    st.floats(-1e4, 1e4),
)
def test_interp1_property_stays_within_values(vs: list[float], x: float) -> None:
    xs = [float(i * 100) for i in range(len(vs))]
    v = interp1(xs, vs, x)
    assert min(vs) - 1e-9 <= v <= max(vs) + 1e-9


@given(
    st.lists(st.lists(st.floats(-100, 100), min_size=3, max_size=3), min_size=2, max_size=2),
    st.floats(-1e4, 1e4),
    st.floats(-1e4, 1e4),
)
def test_interp2_property_stays_within_values(z: list[list[float]], x: float, y: float) -> None:
    flat = [v for row in z for v in row]
    v = interp2([0.0, 10.0, 20.0], [0.0, 5.0], z, x, y)
    assert min(flat) - 1e-9 <= v <= max(flat) + 1e-9


# --------------------------------------------------------------------------- vistas


def test_table_view_exposes_ui_fields(tb: Any) -> None:
    table = ANY_TABLE.validate_python(tb.t3("ve", "ve", "%", 90.0))
    view = table_view(table).model_dump(mode="json")
    assert view["min"] == 0.0 and view["max"] == 150.0
    assert view["x"]["unit"] == "rev/min" and view["x"]["source_channel"] == "rpm"
    assert view["y"]["unit"] == "kPa" and view["y"]["source_channel"] == "map_kpa"
    two = ANY_TABLE.validate_python(
        tb.t2("inj_dead_time", "inj_dead_time", "ms", 0.9, x=[8, 16], xq="battery_v")
    )
    assert table_view(two).model_dump()["x"]["unit"] == "V"


def test_ecu_error_from_validation_returns_none_for_plain_errors() -> None:
    with pytest.raises(ValidationError) as exc:
        Axis(quantity="rpm", values=[1.0])  # type: ignore[arg-type]
    assert ecu_error_from_validation(exc.value) is None
