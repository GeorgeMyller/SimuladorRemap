"""Catálogo de canais expandido por cilindro (T161, T330; tel RF-04, RF-06; D-20; E-26)."""

from __future__ import annotations

import httpx
import pytest

from simremap.catalog.service import get_catalog
from simremap.telemetry.channels import (
    COMPOSITE_CHANNELS,
    build_catalog,
    catalog_for_vehicle,
)
from simremap.telemetry.contracts import Aggregation, ChannelKind, TelemetryChannel


def test_hatch_catalog_expands_four_cylinders() -> None:
    catalog = catalog_for_vehicle(get_catalog().get_vehicle("hatch-20t-gdi"))
    names = set(catalog.names)
    assert {f"lambda_cyl{k}" for k in range(1, 5)} <= names
    assert "lambda_cyl5" not in names
    for base in ("knock_sensor_v", "knock_intensity", "egt_c", "injector_pw_ms", "spark_deg"):
        assert {f"{base}_cyl{k}" for k in range(1, 5)} <= names
    assert "health_turbine_pct" in names  # turbo
    assert len(catalog.names) == len(names)  # sem repetidos


def test_v8_catalog_and_naturally_aspirated_turbo_channels() -> None:
    v8 = catalog_for_vehicle(get_catalog().get_vehicle("muscle-v8-sc"))
    assert {f"egt_c_cyl{k}" for k in range(1, 9)} <= set(v8.names)
    assert "egt_c_cyl9" not in v8
    # Sem turbo: turbo_rpm e wastegate_duty_pct existem (nulos), saúde da turbina não.
    assert v8.get("turbo_rpm") is not None and v8.get("turbo_rpm").nullable  # type: ignore[union-attr]
    assert "health_turbine_pct" not in v8


@pytest.mark.parametrize(
    ("name", "aggregation", "decimals", "unit"),
    [
        ("rpm", Aggregation.LAST, 0, "rpm"),
        ("knock_intensity_cyl2", Aggregation.MAX, 3, "-"),
        ("knock_sensor_v_cyl1", Aggregation.MAX, 3, "V"),
        ("egt_c", Aggregation.MAX, 0, "°C"),
        ("health_min_pct", Aggregation.MIN, 1, "%"),
        ("fuel_cut", Aggregation.ANY, 0, "flag"),
        ("overrun_afterfire", Aggregation.SUM, 0, "contagem"),
        ("boost_bar", Aggregation.LAST, 2, "bar"),
        ("injector_pw_ms_cyl3", Aggregation.MAX, 2, "ms"),
        ("lambda_measured", Aggregation.LAST, 3, "-"),
    ],
)
def test_channel_rules(name: str, aggregation: Aggregation, decimals: int, unit: str) -> None:
    channel = build_catalog(4, True).get(name)
    assert channel is not None
    assert channel.aggregation == aggregation
    assert channel.decimals == decimals
    assert channel.unit == unit
    TelemetryChannel.model_validate(channel.model_dump())


def test_kinds_and_cylinder_index() -> None:
    catalog = build_catalog(6, False)
    egt3 = catalog.get("egt_c_cyl3")
    assert egt3 is not None and egt3.kind == ChannelKind.PER_CYLINDER and egt3.cylinder == 3
    assert catalog.get("fuel_cut").kind == ChannelKind.FLAG  # type: ignore[union-attr]
    assert catalog.get("rpm").kind == ChannelKind.SCALAR  # type: ignore[union-attr]
    assert catalog.index["rpm"] == 0
    assert catalog.unknown(["rpm", "egt_c_cyl7", "knock_spectrum", "nope"]) == [
        "egt_c_cyl7",
        "nope",
    ]
    assert COMPOSITE_CHANNELS == {"knock_spectrum", "cyl_pressure_trace"}
    assert len(catalog) == len(catalog.agg) == len(catalog.decimals)


def test_invalid_cylinder_count() -> None:
    with pytest.raises(ValueError, match="n_cyl"):
        build_catalog(9, False)


async def test_e26_endpoint(tel_client: httpx.AsyncClient) -> None:
    resp = await tel_client.get(
        "/api/v1/telemetry/channels", params={"vehicle_id": "hatch-20t-gdi"}
    )
    assert resp.status_code == 200, resp.text
    names = [c["name"] for c in resp.json()]
    assert "lambda_cyl4" in names and "lambda_cyl5" not in names
    v8 = await tel_client.get("/api/v1/telemetry/channels", params={"vehicle_id": "muscle-v8-sc"})
    assert "egt_c_cyl8" in [c["name"] for c in v8.json()]
    missing = await tel_client.get(
        "/api/v1/telemetry/channels", params={"vehicle_id": "nao-existe"}
    )
    assert missing.status_code == 404 and missing.json()["code"] == "VEHICLE_NOT_FOUND"
    invalid = await tel_client.get("/api/v1/telemetry/channels")
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_FAILED"
