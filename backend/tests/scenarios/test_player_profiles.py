"""Perfis de jogador (T200; scenarios RF-01 a RF-03; D-16)."""

from __future__ import annotations

import uuid

import pytest
from scn_env import ScnEnv


async def test_create_and_list(scn: ScnEnv) -> None:
    resp = await scn.client.post("/api/v1/profiles", json={"nickname": "lucas_turbo"})
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"profile_id", "nickname", "role", "created_at"}
    assert body["role"] == "student"
    assert uuid.UUID(body["profile_id"]).version == 4
    listed = (await scn.client.get("/api/v1/profiles")).json()
    assert [p["nickname"] for p in listed] == ["lucas_turbo"]


@pytest.mark.parametrize("nickname", ["com espaco ", "lucas@turbo", "ab", "x" * 25, "ção"])
async def test_invalid_nickname_is_422(scn: ScnEnv, nickname: str) -> None:
    resp = await scn.client.post("/api/v1/profiles", json={"nickname": nickname})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_FAILED"


async def test_extra_personal_field_is_rejected(scn: ScnEnv) -> None:
    resp = await scn.client.post("/api/v1/profiles", json={"nickname": "lucas", "email": "a@b.c"})
    assert resp.status_code == 422


async def test_nickname_taken_case_insensitive(scn: ScnEnv) -> None:
    await scn.profile("Lucas_Turbo")
    resp = await scn.client.post(
        "/api/v1/profiles", json={"nickname": "lucas_turbo", "role": "instructor"}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "NICKNAME_TAKEN"


async def test_profile_limit_100(scn: ScnEnv) -> None:
    for i in range(100):
        await scn.profile(f"aluno_{i:03d}")
    resp = await scn.client.post("/api/v1/profiles", json={"nickname": "aluno_extra"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "PROFILE_LIMIT_REACHED"


async def test_header_required_and_not_found(scn: ScnEnv) -> None:
    missing = await scn.client.get("/api/v1/attempts")
    assert missing.status_code == 400
    assert missing.json()["code"] == "PLAYER_PROFILE_REQUIRED"
    unknown = await scn.client.get(
        "/api/v1/attempts", headers={"X-Player-Profile-Id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "PLAYER_PROFILE_NOT_FOUND"
    garbage = await scn.client.get(
        "/api/v1/scenarios", headers={"X-Player-Profile-Id": "nao-e-uuid"}
    )
    assert garbage.status_code == 404
    assert garbage.json()["code"] == "PLAYER_PROFILE_NOT_FOUND"
    # Opcional em E-32: sem cabeçalho funciona.
    assert (await scn.client.get("/api/v1/scenarios")).status_code == 200


async def test_student_cannot_create_scenario(scn: ScnEnv) -> None:
    from simremap.scenarios.catalog import example_challenge

    student = await scn.profile("lucas_turbo")
    resp = await scn.client.post(
        "/api/v1/scenarios", headers=student, json={"scenario": example_challenge()}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "INSTRUCTOR_ROLE_REQUIRED"
