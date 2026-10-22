"""Settings mínimo da onda 0 (os testes completos de T080 vêm depois)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from simremap.core.config import Settings


def test_defaults_derive_sqlite_from_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIMREMAP_DATABASE_URL", raising=False)
    monkeypatch.setenv("SIMREMAP_DATA_DIR", "/tmp/simremap-x")
    settings = Settings(_env_file=None)
    assert settings.db_url == "sqlite+aiosqlite:////tmp/simremap-x/simremap.db"
    assert settings.sqlite_path == Path("/tmp/simremap-x/simremap.db")
    assert settings.is_sqlite
    assert settings.worker_mode == "process"
    assert settings.max_active_sessions == 1


def test_database_url_alias_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/simremap")
    settings = Settings(_env_file=None)
    assert settings.db_url.startswith("postgresql+asyncpg://")
    assert not settings.is_sqlite
    assert settings.sqlite_path is None


def test_memory_sqlite_has_no_path() -> None:
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    assert settings.sqlite_path is None


def test_invalid_driver_rejected() -> None:
    with pytest.raises(ValidationError, match="sqlite\\+aiosqlite ou postgresql\\+asyncpg"):
        Settings(_env_file=None, database_url="mysql://x")


def test_sim_hz_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_SIM_HZ", "50")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("origin", ["http://evil.example", "https://localhost:5173"])
def test_cors_only_localhost(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_settings_frozen() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ValidationError):
        settings.sim_hz = 500  # type: ignore[misc]
