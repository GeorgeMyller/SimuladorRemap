"""Swap OEM → standalone, volta ao OEM, base versionada e guarda de partida (T154; RF-17 a RF-20).

Os endpoints falam com a ``FakeSessionPort`` (dyno-bench em memória, ``conftest.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from simremap.catalog.service import get_catalog
from simremap.core.errors import SimRemapError
from simremap.ecu.repository import CalibrationRepository
from simremap.profiles.repository import ProfileRepository
from simremap.profiles.service import ProfileService
from simremap.profiles.setup import ProfileSessionGuard, SessionSetupState

CLASSIC = "classic-20t-swap"
REQUIRED = {
    "trigger.wheel",
    "injectors.flow",
    "injectors.dead_time",
    "fuel.type",
    "sensors.map",
    "base_map",
}


async def swap(api: Any, target: str = "ft-pro", **extra: Any) -> Any:
    body = {"target_profile_id": target, "confirm_snapshot": True, **extra}
    return await api.client.post(api.url("swap"), json=body)


def missing(checklist: dict[str, Any]) -> set[str]:
    return {i["id"] for i in checklist["items"] if i["required"] and i["status"] == "missing"}


async def put_base(api: Any, base: dict[str, Any], version: int | None, **extra: Any) -> Any:
    body = {"base_version": version, "base_setup": base, **extra}
    return await api.client.put(api.url("base-setup"), json=body)


async def test_swap_oem_to_ft_pro(api: Any) -> None:
    """RF-17: 200 com ``awaiting_base_setup``, snapshot OEM e os 6 obrigatórios em ``missing``."""
    api.port.add(CLASSIC)
    resp = await swap(api)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["previous_profile_id"] == "oem-stage" and data["profile_id"] == "ft-pro"
    assert data["ecu_state"] == "awaiting_base_setup"
    snap = data["oem_snapshot"]
    assert (
        snap["calibration_id"] == f"stock-{CLASSIC}-oem-stage" and len(snap["content_hash"]) == 64
    )
    assert missing(data["checklist"]) == REQUIRED
    assert data["checklist"]["minimum_valid"] is False
    assert data["calibration_id"] is None and data["base_setup_version"] is None
    sheet = data["hardware_sheet"]
    assert sheet["trigger_wheel"] == "60-2" and sheet["tdc_offset_nominal_deg"] == 90.0
    cmd = api.port.commands[-1]
    assert cmd.profile_id == "ft-pro" and cmd.ecu_state == "awaiting_base_setup"
    assert cmd.calibration_payload_json is None
    guard: ProfileSessionGuard = api.app.state.profiles_guard
    assert set(guard.can_start_run(cmd.session_id)) == REQUIRED
    with pytest.raises(SimRemapError) as exc:
        guard.require_can_start(cmd.session_id)
    assert exc.value.error_code == "ECU_SETUP_INCOMPLETE" and exc.value.error_status == 409
    pending = exc.value.extra["pending"]
    assert isinstance(pending, list) and set(pending) == REQUIRED


async def test_swap_errors(api: Any) -> None:
    """EC-01, EC-02, RF-17: puxada ativa 409, sem confirmação 422, mesmo perfil 422."""
    api.port.add(CLASSIC, run_active=True)
    resp = await swap(api)
    assert resp.status_code == 409 and resp.json()["code"] == "RUN_IN_PROGRESS"
    api.port.set(api.port.add(CLASSIC), run_active=False)
    resp = await swap(api, confirm_snapshot=False)
    assert resp.status_code == 422 and resp.json()["code"] == "SWAP_CONFIRMATION_REQUIRED"
    resp = await swap(api, target="oem-stage")
    assert resp.status_code == 422 and resp.json()["code"] == "SWAP_TARGET_INVALID"
    resp = await swap(api, target="xx-pro")
    assert resp.status_code == 422  # fora do enum do SwapRequest
    resp = await api.client.post(
        api.url("swap", "ffffffffffffffffffffffffffffffff"),
        json={"target_profile_id": "ft-pro", "confirm_snapshot": True},
    )
    assert resp.status_code == 404 and resp.json()["code"] == "SESSION_NOT_FOUND"
    api.port.set(api.port.add(CLASSIC), closed=True)
    resp = await swap(api)
    assert resp.status_code == 409 and resp.json()["code"] == "SESSION_CLOSED"
    assert api.port.commands == []


async def test_swap_disabled_profile(api: Any) -> None:
    api.port.add(CLASSIC)
    api.app.state.settings = api.app.state.settings.model_copy(
        update={"ecu_profiles_enabled": frozenset({"oem-stage", "ht-elite"})}
    )
    resp = await swap(api, target="ft-pro")
    assert resp.status_code == 404 and resp.json()["code"] == "ECU_PROFILE_NOT_FOUND"


async def test_swap_not_supported_for_vehicle(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """EC-13: veículo sem ficheiro de hardware ⇒ 422 ``SWAP_NOT_SUPPORTED_FOR_VEHICLE``."""
    from simremap.profiles import service as service_mod

    api.port.add(CLASSIC)
    monkeypatch.setattr(service_mod, "load_vehicle_hardware", lambda _vid: None)
    resp = await swap(api)
    assert resp.status_code == 422 and resp.json()["code"] == "SWAP_NOT_SUPPORTED_FOR_VEHICLE"


async def test_idempotent_swap(api: Any) -> None:
    """EC-03: o mesmo ``request_id`` devolve o mesmo resultado sem novo comando."""
    api.port.add(CLASSIC)
    first = await swap(api, request_id="req-1")
    second = await swap(api, request_id="req-1")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(api.port.commands) == 1


async def test_base_setup_partial_conflict_invalid(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-19: só roda ⇒ 5 obrigatórios em falta; ``base_version`` antiga ⇒ 409; vazão 0 ⇒ 422."""
    api.port.add(CLASSIC)
    assert (await swap(api)).status_code == 200
    only_trigger = {"trigger": base_payload()["trigger"]}
    resp = await put_base(api, only_trigger, None)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ecu_state"] == "awaiting_base_setup" and data["base_setup_version"] == 1
    assert len(missing(data["checklist"])) == 5
    assert len(data["setup_hash"]) == 64 and data["editable"] is True
    stale = await put_base(api, only_trigger, None)
    assert stale.status_code == 409 and stale.json()["code"] == "BASE_SETUP_VERSION_CONFLICT"
    assert stale.json()["latest_version"] == 1
    bad = base_payload()
    bad["injectors"]["flow_cc_min"] = 0
    resp = await put_base(api, bad, 1)
    assert resp.status_code == 422
    problem = resp.json()
    assert problem["code"] == "BASE_SETUP_INVALID" and problem["field"] == "injectors.flow_cc_min"
    order = base_payload()
    order["trigger"]["firing_order"] = [1, 3, 2]
    resp = await put_base(api, order, 1)
    assert resp.status_code == 422 and resp.json()["field"] == "trigger.firing_order"
    bad_model = base_payload()
    bad_model["trigger"]["firing_order"] = [1, 3, 3, 2]
    resp = await put_base(api, bad_model, 1)
    assert resp.status_code == 422 and resp.json()["reason"].endswith("FIRING_ORDER_INVALID")
    wiz = await put_base(api, base_payload(), 1, generate_base_map=True, wizard={"grid": 7})
    assert wiz.status_code == 422 and wiz.json()["code"] == "WIZARD_INPUT_INVALID"


async def test_flow_b_setup_without_injectors(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """Fluxo B: base sem bicos ⇒ ``awaiting_base_setup`` e pendentes de bicos e mapa base."""
    api.port.add(CLASSIC)
    await swap(api)
    base = base_payload()
    del base["injectors"]
    resp = await put_base(api, base, None, generate_base_map=True)
    assert resp.status_code == 200
    assert resp.json()["ecu_state"] == "awaiting_base_setup"
    assert resp.json()["calibration_id"] is None
    guard: ProfileSessionGuard = api.app.state.profiles_guard
    pending = guard.can_start_run(next(iter(api.port.sessions)))
    assert pending == ["injectors.flow", "injectors.dead_time", "base_map"]


async def test_complete_setup_then_back_to_oem(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-18: base completa ⇒ ``standalone_ready``; volta ao OEM repõe o mesmo ``content_hash``."""
    sid = api.port.add(CLASSIC)
    first = (await swap(api)).json()
    resp = await put_base(
        api, base_payload(), None, generate_base_map=True, wizard={"max_map_kpa": 250.0}
    )
    assert resp.status_code == 200, resp.text
    ready = resp.json()
    assert ready["ecu_state"] == "standalone_ready"
    assert ready["calibration_id"] and ready["calibration_version"] == 1
    assert ready["estimated_peak_duty_pct"] > 0
    cal = (await api.client.get(f"/api/v1/calibrations/{ready['calibration_id']}")).json()
    assert cal["metadata"]["source"] == "wizard" and cal["profile_id"] == "ft-pro"
    assert cal["metadata"]["extra"]["base_setup_hash"] == ready["setup_hash"]
    cmd = api.port.commands[-1]
    assert cmd.ecu_state == "standalone_ready" and cmd.calibration_payload_json
    assert api.app.state.profiles_guard.can_start_run(sid) == []

    back = await swap(api, target="oem-stage", confirm_snapshot=False)
    assert back.status_code == 200, back.text
    oem = back.json()
    assert oem["ecu_state"] == "oem"
    assert oem["oem_snapshot"]["content_hash"] == first["oem_snapshot"]["content_hash"]
    assert oem["calibration_id"] == first["oem_snapshot"]["calibration_id"]
    assert api.port.commands[-1].base_setup_json is None
    base_get = (await api.client.get(api.url("base-setup"))).json()
    assert base_get["editable"] is False and base_get["ecu_state"] == "oem"

    # De novo ao ft-pro: a base e a calibração standalone guardadas são reaproveitadas.
    again = (await swap(api)).json()
    assert again["ecu_state"] == "standalone_ready"
    assert again["calibration_id"] == ready["calibration_id"]


async def test_swap_between_standalone_generates_map(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-18: ``ft-pro`` → ``ht-elite`` com setup completo ⇒ mapa novo (``source = wizard``)."""
    api.port.add(CLASSIC)
    await swap(api)
    ready = (await put_base(api, base_payload(), None, generate_base_map=True)).json()
    resp = await swap(api, target="ht-elite")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ecu_state"] == "standalone_ready" and data["oem_snapshot"] is not None
    assert data["calibration_id"] not in (None, ready["calibration_id"])
    cal = (await api.client.get(f"/api/v1/calibrations/{data['calibration_id']}")).json()
    assert cal["profile_id"] == "ht-elite" and cal["metadata"]["source"] == "wizard"
    assert data["base_setup_version"] == 1
    m1 = (await swap(api, target="m1-race", feature_package="race")).json()
    assert m1["base_setup_version"] == 2  # pacote race gravado na base
    cal_m1 = (await api.client.get(f"/api/v1/calibrations/{m1['calibration_id']}")).json()
    assert cal_m1["profile_params"]["feature_package"] == "race"


async def test_setup_removed_after_ready_ec06(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    api.port.add(CLASSIC)
    await swap(api)
    await put_base(api, base_payload(), None, generate_base_map=True)
    base = base_payload()
    del base["injectors"]
    resp = await put_base(api, base, 1)
    assert resp.json()["ecu_state"] == "awaiting_base_setup"
    assert api.port.commands[-1].ecu_state == "awaiting_base_setup"
    assert api.port.commands[-1].calibration_payload_json is None


async def test_prefill_from_hardware_sheet(api: Any) -> None:
    api.port.add(CLASSIC)
    data = (await swap(api, prefill_from_hardware_sheet=True)).json()
    assert data["base_setup_version"] == 1
    assert missing(data["checklist"]) == {"base_map"}
    base = (await api.client.get(api.url("base-setup"))).json()["base_setup"]
    assert base["trigger"]["wheel"] == "60-2" and base["fuel"]["fuel_id"] == "e100"
    assert base["injectors"]["flow_cc_min"] == data["hardware_sheet"]["injector_label_cc_min"]


async def test_apply_timeout_keeps_base_ec05(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """EC-05: sem ``ack`` em 100 ms ⇒ 504, base gravada e ``base_map`` em ``invalid``."""
    api.port.add(CLASSIC)
    await swap(api)
    api.port.hang = True
    resp = await put_base(api, base_payload(), None, generate_base_map=True)
    assert resp.status_code == 504 and resp.json()["code"] == "CALIBRATION_APPLY_TIMEOUT"
    assert api.port.cancelled
    api.port.hang = False
    got = (await api.client.get(api.url("base-setup"))).json()
    assert got["base_setup_version"] == 1 and got["ecu_state"] == "awaiting_base_setup"
    base_map = next(i for i in got["checklist"]["items"] if i["id"] == "base_map")
    assert base_map["status"] == "invalid"
    swap_hang = await swap(api, target="ht-elite")
    assert swap_hang.status_code == 200


async def test_put_with_run_and_oem(api: Any, base_payload: Callable[..., dict[str, Any]]) -> None:
    """RF-13: PUT no OEM ⇒ 409 ``BASE_SETUP_NOT_EDITABLE_OEM``; com puxada ⇒ 409."""
    sid = api.port.add(CLASSIC)
    resp = await put_base(api, base_payload(), None)
    assert resp.status_code == 409 and resp.json()["code"] == "BASE_SETUP_NOT_EDITABLE_OEM"
    await swap(api)
    api.port.set(sid, run_active=True)
    resp = await put_base(api, base_payload(), None)
    assert resp.status_code == 409 and resp.json()["code"] == "RUN_IN_PROGRESS"


async def test_guard_and_pending_from_db(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    sid = api.port.add(CLASSIC)
    await swap(api)
    guard = ProfileSessionGuard()
    assert guard.can_start_run(sid) == []
    guard.update(sid, SessionSetupState("ft-pro", "awaiting_base_setup"))
    assert guard.can_start_run(sid) == ["base_map"]
    assert sid in guard.snapshot()
    guard.forget(sid)
    assert guard.state(sid) is None
    async with api.maker() as session:
        repo = ProfileRepository(session)
        state = await repo.get_state(sid)
        assert state is not None and state.ecu_state == "awaiting_base_setup"
        svc = ProfileService(
            port=api.port,
            repo=repo,
            calibrations=CalibrationRepository(session),
            registry=api.app.state.profiles_registry,
            catalog=get_catalog(),
            guard=guard,
            idempotency=api.app.state.profiles_idempotency,
        )
        assert set(await svc.pending_for(sid)) == REQUIRED
        assert await svc.pending_for("nope") == []


async def test_database_unavailable(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    api.port.add(CLASSIC)

    async def boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(AsyncSession, "get", boom)
    resp = await swap(api)
    assert resp.status_code == 503
    assert resp.json()["code"] == "DATABASE_UNAVAILABLE"
    assert resp.headers["retry-after"] == "2"
