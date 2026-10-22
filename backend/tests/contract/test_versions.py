"""``GET /api/v1/version`` e constantes de formato (T079, T227; RF-08, RF-21)."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from simremap.core import versions
from simremap.core.errors import catalog_sha256
from simremap.core.versions import FORMAT_CHANGELOG, alembic_head

SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
BACKEND = Path(__file__).resolve().parents[2]


async def test_version_matches_constants(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/version")).json()
    assert body["api_version"] == versions.API_VERSION == "v1"
    assert body["ws_envelope_version"] == versions.WS_ENVELOPE_VERSION == 1
    assert body["package_format_version"] == versions.PACKAGE_FORMAT_VERSION == 1
    assert body["datalog_format_version"] == versions.DATALOG_FORMAT_VERSION == 1
    assert body["alembic_head"] == alembic_head()
    assert body["error_catalog_sha256"] == catalog_sha256()
    assert SEMVER.fullmatch(body["app_version"])
    assert body["python_version"] == ".".join(map(str, sys.version_info[:3]))
    assert body["git_sha"] is None and body["build_time_utc"] is None


def test_alembic_head_equals_cli() -> None:
    out = subprocess.run(  # noqa: S603 - comando fixo do próprio venv
        [sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), "heads"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    heads = [line.split()[0] for line in out.splitlines() if line.strip()]
    assert heads == [alembic_head()]


def test_changelog_tracks_every_format_constant() -> None:
    current = {
        "api_version": int(versions.API_VERSION.removeprefix("v")),
        "ws_envelope_version": versions.WS_ENVELOPE_VERSION,
        "package_format_version": versions.PACKAGE_FORMAT_VERSION,
        "datalog_format_version": versions.DATALOG_FORMAT_VERSION,
    }
    assert set(FORMAT_CHANGELOG) == set(current)
    for name, value in current.items():
        history = FORMAT_CHANGELOG[name]
        assert max(history) == value, f"{name}={value} sem entrada no FORMAT_CHANGELOG"
        assert sorted(history) == list(range(1, value + 1))
        assert all(text.strip() for text in history.values())


async def test_version_build_metadata(settings_factory: object) -> None:
    from asgi_lifespan import LifespanManager

    from simremap.api.main import create_app

    settings = settings_factory(  # type: ignore[operator]
        app_version="1.2.3-rc.1", git_sha="0123abc", build_time_utc="2026-10-18T10:00:00Z"
    )
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            body = (await ac.get("/api/v1/version")).json()
    assert body["app_version"] == "1.2.3-rc.1"
    assert body["git_sha"] == "0123abc"
    assert body["build_time_utc"].startswith("2026-10-18T10:00:00")


async def test_version_latency_p95_under_20ms(client: httpx.AsyncClient) -> None:
    samples = []
    for _ in range(40):
        t0 = time.perf_counter()
        await client.get("/api/v1/version")
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    assert samples[int(0.95 * len(samples)) - 1] < 20
