"""``Calibration``: hash canónico, versões imutáveis, reversão e ``profile_params``.

Fontes: RF-04, RF-05, RF-32; D-11; T139.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.ecu.calibration import (
    CONTENT_FIELDS,
    Calibration,
    CalibrationContent,
    CalibrationMetadata,
    TablePatch,
    apply_table_patch,
    build_calibration,
    canonical_json,
    compute_content_hash,
    diff_calibrations,
    parse_content,
    round_floats,
    validate_stock_calibration,
)
from simremap.ecu.contracts import EcuValidationError
from simremap.ecu.tables import Table3D

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


def _build(content: CalibrationContent, name: str = "Stage 1", version: int = 1) -> Calibration:
    return build_calibration(
        content,
        calibration_id="cal-1",
        version=version,
        parent_version=None if version == 1 else version - 1,
        metadata=CalibrationMetadata(name=name),
        created_at=NOW,
    )


def test_hash_ignores_metadata_version_and_created_at(content_factory: Any) -> None:
    content = content_factory()
    a = _build(content, "A", 1)
    b = build_calibration(
        content,
        calibration_id="other",
        version=7,
        parent_version=6,
        metadata=CalibrationMetadata(name="B", notes="x", author_nickname="lucas"),
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert a.content_hash == b.content_hash
    assert a.verify_hash() and b.verify_hash()


def test_hash_changes_with_one_cell(content_factory: Any, tb: Any) -> None:
    tables = tb.base_tables()
    a = compute_content_hash(content_factory(tables))
    tables["ve"]["values"][3][3] = 91.0
    assert compute_content_hash(content_factory(tables)) != a


def test_hash_matches_canonical_recipe(content_factory: Any) -> None:
    content = content_factory()
    payload = round_floats(content.model_dump(mode="json", include=set(CONTENT_FIELDS)))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert compute_content_hash(content) == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert set(payload) == set(CONTENT_FIELDS)


def test_hash_rounds_floats_to_six_decimals(content_factory: Any, tb: Any) -> None:
    tables = tb.base_tables()
    tables["ve"]["values"][0][0] = 90.0000001
    assert compute_content_hash(content_factory(tables)) == compute_content_hash(content_factory())
    tables["ve"]["values"][0][0] = 90.00001
    assert compute_content_hash(content_factory(tables)) != compute_content_hash(content_factory())


def test_round_floats_normalizes_negative_zero_and_keeps_bools() -> None:
    assert round_floats({"a": -0.0, "b": [True, 1, 1.23456789]}) == {
        "a": 0.0,
        "b": [True, 1, 1.234568],
    }
    assert canonical_json({"b": 1, "a": "λ"}) == '{"a":"λ","b":1}'


def test_profile_params_enter_hash_and_key_order_does_not(content_factory: Any) -> None:
    on = content_factory(profile_params={"torque_monitoring": True, "checksum_check": True})
    off = content_factory(profile_params={"torque_monitoring": False, "checksum_check": True})
    reordered = content_factory(profile_params={"checksum_check": True, "torque_monitoring": True})
    assert compute_content_hash(on) != compute_content_hash(off)
    assert compute_content_hash(on) == compute_content_hash(reordered)


def test_profile_params_types_and_limits(content_factory: Any) -> None:
    content = content_factory(profile_params={"a": True, "b": 1.5, "c": "x", "d": 2})
    assert content.profile_params == {"a": True, "b": 1.5, "c": "x", "d": 2.0}
    with pytest.raises(ValidationError):
        content_factory(profile_params={f"k{i}": 1.0 for i in range(65)})
    with pytest.raises(ValidationError):
        content_factory(profile_params={"nan": float("nan")})


def test_default_fields_do_not_change_hash(content_factory: Any) -> None:
    implicit = content_factory(strategies={"knock_control": {"kind": "knock_control"}})
    explicit = content_factory(
        strategies={"knock_control": {"kind": "knock_control", "retard_step_deg": 2.0}}
    )
    assert compute_content_hash(implicit) == compute_content_hash(explicit)


def test_calibration_is_immutable(content_factory: Any) -> None:
    cal = _build(content_factory())
    with pytest.raises(ValidationError):
        cal.version = 2


def test_content_round_trip_keeps_hash(content_factory: Any) -> None:
    cal = _build(content_factory())
    again = Calibration.model_validate_json(cal.model_dump_json())
    assert again.content_hash == cal.content_hash == compute_content_hash(again.content())


# --------------------------------------------------------------------------- validação


def test_table_key_must_equal_table_id(content_factory: Any, tb: Any) -> None:
    tables = {"ve_main": tb.t3("ve", "ve", "%", 90.0)}
    with pytest.raises(EcuValidationError) as exc:
        content_factory(tables)
    assert exc.value.code == "TABLE_ID_MISMATCH"


def test_strategy_key_must_equal_kind(content_factory: Any) -> None:
    with pytest.raises(EcuValidationError) as exc:
        content_factory(strategies={"knock": {"kind": "knock_control"}})
    assert exc.value.code == "STRATEGY_KIND_MISMATCH"


def test_duplicated_kind_and_cylinder_rejected(content_factory: Any, tb: Any) -> None:
    tables = {**tb.base_tables(), "ve2": tb.t3("ve2", "ve", "%", 80.0)}
    with pytest.raises(EcuValidationError) as exc:
        content_factory(tables)
    assert exc.value.detail["reason"] == "kind_duplicated"
    tables = {
        **tb.base_tables(),
        "ft_a": tb.t3("ft_a", "fuel_trim_cyl", "%", 1.0, cylinder=2),
        "ft_b": tb.t3("ft_b", "fuel_trim_cyl", "%", 2.0, cylinder=2),
    }
    with pytest.raises(EcuValidationError) as exc:
        content_factory(tables)
    assert exc.value.detail["reason"] == "cylinder_duplicated"


def test_two_step_target_must_be_below_hard_limit(content_factory: Any) -> None:
    """EC-13."""
    with pytest.raises(EcuValidationError) as exc:
        content_factory(
            strategies={
                "two_step": {"kind": "two_step", "target_rpm": 7000.0},
                "rev_limiter": {"kind": "rev_limiter", "hard_rpm": 7000.0},
            }
        )
    assert exc.value.code == "STRATEGY_CONFIG_INVALID"


def test_fuel_mode_requires_table(content_factory: Any, tb: Any) -> None:
    tables = tb.base_tables()
    with pytest.raises(EcuValidationError) as exc:
        content_factory(tables, fuel_model={"mode": "direct_pulse_ms"})
    assert exc.value.code == "STRATEGY_CONFIG_INVALID"
    del tables["ve"]
    with pytest.raises(EcuValidationError):
        content_factory(tables)
    assert content_factory(tables, fuel_model={"mode": "profile_air_model"}).fuel_model.mode == (
        "profile_air_model"
    )


def test_too_many_tables(content_factory: Any, tb: Any) -> None:
    tables = tb.base_tables()
    for i in range(1, 9):
        tables[f"ft_{i}"] = tb.t3(f"ft_{i}", "fuel_trim_cyl", "%", 0.0, cylinder=i)
    assert len(content_factory(tables).tables) == 11
    huge = {f"t{i:03d}": tb.t3(f"t{i:03d}", "ve", "%", 1.0) for i in range(129)}
    with pytest.raises(EcuValidationError) as exc:
        parse_content({"vehicle_id": "hatch-20t-gdi", "profile_id": "ft-pro", "tables": huge})
    assert exc.value.code == "TABLE_SIZE_EXCEEDED"


def test_export_example_from_file_formats_is_accepted() -> None:
    """file-formats seção 3: só ``ignition_base`` e estratégia parcial, modo profile_air_model."""
    data = {
        "calibration_id": "0f5e9c2a",
        "vehicle_id": "hatch-20t-gdi",
        "profile_id": "oem-stage",
        "version": 4,
        "parent_version": 3,
        "fuel_model": {"mode": "profile_air_model"},
        "tables": {
            "ignition_base": {
                "table_id": "ignition_base",
                "kind": "ignition_base",
                "dims": 3,
                "unit": "°BTDC",
                "live_tunable": True,
                "decimals": 1,
                "x": {"quantity": "rpm", "values": [1000, 2000]},
                "y": {"quantity": "map_kpa", "values": [30, 250]},
                "values": [[10.0, 25.0], [5.0, 12.0]],
            }
        },
        "strategies": {"knock_control": {"kind": "knock_control", "max_retard_deg": 8.0}},
        "profile_params": {"torque_monitoring": True},
        "metadata": {
            "name": "Stage 1",
            "author_nickname": "lucas",
            "extra": {"oem_checksum": "a1b2"},
        },
        "content_hash": "0" * 64,
        "created_at": "2026-10-18T10:00:00Z",
    }
    cal = Calibration.model_validate(data)
    assert not cal.verify_hash()  # o servidor recalcula o hash (import)
    assert compute_content_hash(cal) == _build(cal.content()).content_hash


def test_validate_stock_calibration(content_factory: Any) -> None:
    payload = content_factory().model_dump(mode="json")
    payload["metadata"] = {"name": "Série", "source": "user"}
    cal = validate_stock_calibration(
        payload, vehicle_id="hatch-20t-gdi", profile_id="oem-stage", created_at=NOW
    )
    assert cal.calibration_id == "stock-hatch-20t-gdi-oem-stage"
    assert cal.metadata.source == "oem_stock"
    assert cal.profile_id.value == "oem-stage"
    payload["tables"]["ve"]["x"]["values"][1] = payload["tables"]["ve"]["x"]["values"][0]
    with pytest.raises(EcuValidationError) as exc:
        validate_stock_calibration(
            payload, vehicle_id="hatch-20t-gdi", profile_id="oem-stage", created_at=NOW
        )
    assert exc.value.code == "TABLE_AXIS_NOT_MONOTONIC"


# --------------------------------------------------------------------------- PATCH (RF-26)


def _ve(content: CalibrationContent) -> Table3D:
    table = content.tables["ve"]
    assert isinstance(table, Table3D)
    return table


def test_patch_add_four_cells(content_factory: Any) -> None:
    ve = _ve(content_factory())
    cells = [{"row": r, "col": c, "value": 2.0} for r, c in ((0, 0), (1, 1), (2, 2), (3, 3))]
    new = apply_table_patch(
        ve, TablePatch.model_validate({"base_version": 1, "op": "add", "cells": cells})
    )
    assert isinstance(new, Table3D)
    changed = [(r, c) for r in range(16) for c in range(16) if new.values[r][c] != ve.values[r][c]]
    assert changed == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert new.values[2][2] == 92.0


def test_patch_set_and_scale(content_factory: Any) -> None:
    ve = _ve(content_factory())
    new = apply_table_patch(
        ve,
        TablePatch(base_version=1, op="scale", cells=[{"row": 0, "col": 1, "value": 0.5}]),  # type: ignore[list-item]
    )
    assert isinstance(new, Table3D) and new.values[0][1] == 45.0
    new = apply_table_patch(
        ve,
        TablePatch(base_version=1, cells=[{"row": 5, "col": 6, "value": 100.0}]),  # type: ignore[list-item]
    )
    assert isinstance(new, Table3D) and new.values[5][6] == 100.0


def test_patch_limits(content_factory: Any, tb: Any) -> None:
    ve = _ve(content_factory())
    too_many = [{"row": 0, "col": 0, "value": 1.0}] * 1025
    with pytest.raises(EcuValidationError) as exc:
        apply_table_patch(ve, TablePatch.model_validate({"base_version": 1, "cells": too_many}))
    assert exc.value.code == "PATCH_TOO_LARGE"
    with pytest.raises(EcuValidationError) as exc:
        apply_table_patch(
            ve,
            TablePatch.model_validate(
                {"base_version": 1, "cells": [{"row": 16, "col": 0, "value": 1}]}
            ),
        )
    assert exc.value.code == "PATCH_CELL_OUT_OF_BOUNDS"
    with pytest.raises(EcuValidationError) as exc:
        apply_table_patch(
            ve,
            TablePatch.model_validate(
                {"base_version": 1, "cells": [{"row": 0, "col": 0, "value": 200}]}
            ),
        )
    assert exc.value.code == "TABLE_VALUE_OUT_OF_RANGE"
    bad_axis = [1000.0, 900.0, *tb.rpm_axis[2:]]
    with pytest.raises(EcuValidationError) as exc:
        apply_table_patch(ve, TablePatch(base_version=1, x_values=bad_axis))
    assert exc.value.code == "TABLE_AXIS_NOT_MONOTONIC"
    with pytest.raises(EcuValidationError) as exc:
        apply_table_patch(ve, TablePatch(base_version=1, y_values=[1.0, 2.0]))
    assert exc.value.code == "TABLE_SHAPE_MISMATCH"


def test_patch_axis_and_2d(content_factory: Any, tb: Any) -> None:
    ve = _ve(content_factory())
    new_axis = [v + 100.0 for v in tb.rpm_axis]
    new = apply_table_patch(ve, TablePatch(base_version=1, x_values=new_axis))
    assert new.x.values == new_axis
    two = parse_content(
        {
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "ft-pro",
            "tables": {
                **tb.base_tables(),
                "inj_dead_time": tb.t2(
                    "inj_dead_time", "inj_dead_time", "ms", 0.9, x=[8, 16], xq="battery_v"
                ),
            },
        }
    ).tables["inj_dead_time"]
    out = apply_table_patch(
        two,
        TablePatch.model_validate(
            {"base_version": 1, "cells": [{"row": 0, "col": 1, "value": 1.2}]}
        ),
    )
    assert out.values == [0.9, 1.2]
    with pytest.raises(EcuValidationError):
        apply_table_patch(two, TablePatch(base_version=1, y_values=[1.0, 2.0]))


# --------------------------------------------------------------------------- diff (RF-28)


def test_diff_live_only_ve_cells(content_factory: Any, tb: Any) -> None:
    tables = tb.full_tables(4)
    old = content_factory(tables)
    tables["ve"]["values"][2][2] = 95.0
    diff = diff_calibrations(old, content_factory(tables))
    assert diff.changed_tables == ["ve"] and diff.live_compatible


def test_diff_flags_non_live_axes_strategies(content_factory: Any, tb: Any) -> None:
    tables = tb.full_tables(4)
    old = content_factory(tables, {"rev_limiter": {"kind": "rev_limiter"}})
    tables["boost_duty_base"]["values"][0][0] = 50.0
    tables["ve"]["x"]["values"] = [v + 10.0 for v in tb.rpm_axis]
    new = content_factory(
        tables,
        {"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6500.0}},
        profile_params={"a": True},
    )
    diff = diff_calibrations(old, new)
    assert not diff.live_compatible
    assert set(diff.not_live) == {
        "tables.boost_duty_base",
        "tables.ve",
        "strategies.rev_limiter",
        "profile_params",
    }
    added = dict(tables)
    del added["cam_exhaust_target"]
    gone = diff_calibrations(old, content_factory(added, {"rev_limiter": {"kind": "rev_limiter"}}))
    assert "tables.cam_exhaust_target" in gone.not_live
    fuel = diff_calibrations(
        old,
        content_factory(
            tb.full_tables(4),
            {"rev_limiter": {"kind": "rev_limiter"}},
            fuel_model={"charge_temp_blend": 0.3},
        ),
    )
    assert fuel.not_live == ["fuel_model"]
