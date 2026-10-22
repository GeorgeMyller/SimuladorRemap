"""``Settings`` completo (T080, T225; RF-04; D-04, D-27, D-31, D-32)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "SIMREMAP_DATABASE_URL",
        "ECU_STRATEGIES_ENABLED",
        "ECU_PROFILES_ENABLED",
        "SIMREMAP_ECU_STRATEGIES_ENABLED",
        "SIMREMAP_ECU_PROFILES_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_spec_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.env == "prod"
    assert s.data_dir == Path("/data")
    assert s.static_dir == Path("/app/static")
    assert s.db_url == "sqlite+aiosqlite:////data/simremap.db"
    assert s.db_auto_migrate is True
    assert s.db_pool_size == 5
    assert s.redis_url is None
    assert s.cache_max_keys == 10_000
    assert s.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.bind_public is False
    assert s.log_level == "INFO"
    assert s.max_body_bytes == 16 * 1024 * 1024
    assert s.sim_hz == 1000
    assert s.ws_fps == 50
    assert s.worker_mode == "process"
    assert s.max_active_sessions == 1
    assert s.db_connect_retries == 5


def test_prefix_simremap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_SIM_HZ", "500")
    monkeypatch.setenv("SIMREMAP_WORKER_MODE", "thread")
    monkeypatch.setenv("SIMREMAP_MAX_ACTIVE_SESSIONS", "2")
    monkeypatch.setenv("SIMREMAP_BIND_PUBLIC", "true")
    monkeypatch.setenv("SIMREMAP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SIM_HZ", "200")  # sem prefixo: ignorado
    s = Settings(_env_file=None)
    assert (s.sim_hz, s.worker_mode, s.max_active_sessions) == (500, "thread", 2)
    assert s.bind_public is True
    assert s.log_level == "DEBUG"


def test_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("SIMREMAP_WS_FPS=60\nSIMREMAP_ENV=dev\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.ws_fps == 60
    assert s.env == "dev"


def test_database_url_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@pg:5432/db")
    assert Settings(_env_file=None).db_url == "postgresql+asyncpg://u:p@pg:5432/db"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sim_hz", 99),
        ("sim_hz", 1001),
        ("ws_fps", 29),
        ("ws_fps", 61),
        ("max_active_sessions", 0),
        ("max_active_sessions", 3),
        ("db_pool_size", 0),
        ("db_pool_size", 21),
        ("cache_max_keys", 99),
        ("max_body_bytes", 1023),
        ("max_body_bytes", 256 * 1024 * 1024 + 1),
        ("worker_mode", "asyncio"),
        ("env", "qa"),
        ("log_level", "TRACE"),
        ("app_version", "1.0"),
        ("git_sha", "XYZ"),
    ],
)
def test_limits_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make: Any = Settings
        make(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    "url", ["mysql+aiomysql://x/y", "sqlite:///x.db", "postgresql://u@h/d", "redis://x"]
)
def test_unknown_driver_fails_at_startup(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "origin",
    ["http://localhost", "http://localhost:3000", "http://127.0.0.1:8000"],
)
def test_local_cors_origins_accepted(origin: str) -> None:
    assert Settings(_env_file=None, cors_origins=[origin]).cors_origins == [origin]


@pytest.mark.parametrize(
    "origin", ["http://192.168.0.10:5173", "http://localhost.evil:80", "*", "http://[::1]:5173"]
)
def test_non_local_cors_origin_rejected(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS"):
        Settings(_env_file=None, cors_origins=[origin])


def test_blank_build_args_are_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_GIT_SHA", "")
    monkeypatch.setenv("SIMREMAP_BUILD_TIME_UTC", " ")
    monkeypatch.setenv("SIMREMAP_REDIS_URL", "")
    s = Settings(_env_file=None)
    assert s.git_sha is None
    assert s.build_time_utc is None
    assert s.redis_url is None


def test_build_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_GIT_SHA", "abc1234")
    monkeypatch.setenv("SIMREMAP_BUILD_TIME_UTC", "2026-10-18T12:00:00Z")
    s = Settings(_env_file=None)
    assert s.git_sha == "abc1234"
    assert s.build_time_utc is not None
    assert s.build_time_utc.year == 2026


# --------------------------------------------------------------------------- flags D-27


def test_feature_flags_default_on() -> None:
    s = Settings(_env_file=None)
    assert s.feature_dyno and s.feature_telemetry and s.feature_scenarios
    assert s.feature_defect_wastegate
    assert s.ecu_strategies_enabled is None
    assert s.ecu_profiles_enabled is None
    assert s.ecu_strategy_enabled("antilag")
    assert s.ecu_profile_enabled("m1-race")


def test_feature_flags_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMREMAP_FEATURE_DYNO", "false")
    monkeypatch.setenv("SIMREMAP_FEATURE_TELEMETRY", "0")
    monkeypatch.setenv("SIMREMAP_FEATURE_SCENARIOS", "1")
    monkeypatch.setenv("SIMREMAP_FEATURE_DEFECT_WASTEGATE", "no")
    monkeypatch.setenv("ECU_STRATEGIES_ENABLED", "fuel, ignition ,closed_loop")
    monkeypatch.setenv("SIMREMAP_ECU_PROFILES_ENABLED", "oem-stage,ft-pro")
    s = Settings(_env_file=None)
    assert (s.feature_dyno, s.feature_telemetry, s.feature_scenarios) == (False, False, True)
    assert s.feature_defect_wastegate is False
    assert s.ecu_strategies_enabled == ("fuel", "ignition", "closed_loop")
    assert s.ecu_strategy_enabled("ignition")
    assert not s.ecu_strategy_enabled("antilag")
    assert s.ecu_profiles_enabled == ("oem-stage", "ft-pro")
    assert not s.ecu_profile_enabled("m1-race")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("all", None), ("*", None), ("", ()), (" , ", ()), ("a", ("a",))],
)
def test_feature_list_parsing(
    raw: str, expected: tuple[str, ...] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ECU_PROFILES_ENABLED", raw)
    assert Settings(_env_file=None).ecu_profiles_enabled == expected


def test_feature_list_from_python_values() -> None:
    make: Any = Settings
    assert make(_env_file=None, ecu_strategies_enabled=["a", "b"]).ecu_strategies_enabled == (
        "a",
        "b",
    )
    assert make(_env_file=None, ecu_strategies_enabled=["all"]).ecu_strategies_enabled is None


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()
