"""Migração 0001_foundation_base e cadeia Alembic (RF-10, D-10)."""

from __future__ import annotations

import warnings
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from simremap.db.base import NAMING_CONVENTION, metadata
from simremap.db.migrate import alembic_config, downgrade, script_head, script_heads, upgrade
from simremap.db.models import loaded_model_modules


def _tables(db_file: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_file}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_single_alembic_head() -> None:
    assert len(script_heads()) == 1
    assert script_head() == script_heads()[0]


def test_round_trip_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    db_file = tmp_path / "rt.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    upgrade(url)
    assert {"app_meta", "alembic_version"} <= _tables(db_file)
    downgrade(url, "base")
    assert "app_meta" not in _tables(db_file)
    upgrade(url)
    assert "app_meta" in _tables(db_file)
    engine = sa.create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        pk = sa.inspect(conn).get_pk_constraint("app_meta")
    engine.dispose()
    assert version == script_head()
    assert pk["constrained_columns"] == ["key"]


def test_0001_is_base_of_chain() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    base = script.get_revision("0001_foundation_base")
    assert base is not None
    assert base.down_revision is None


def test_metadata_naming_convention_and_models() -> None:
    assert metadata.naming_convention == NAMING_CONVENTION
    assert "app_meta" in metadata.tables
    assert loaded_model_modules()[0] == "simremap.db.models.foundation"


async def test_lifespan_applies_migrations(app: FastAPI, client: httpx.AsyncClient) -> None:
    engine: AsyncEngine = app.state.engine
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
        journal = (await conn.execute(sa.text("PRAGMA journal_mode"))).scalar_one()
        fks = (await conn.execute(sa.text("PRAGMA foreign_keys"))).scalar_one()
    assert {"app_meta", "alembic_version"} <= names
    assert journal == "wal"
    assert fks == 1


# --------------------------------------------------------------------------- cadeia 0002..0008
# (contracts-db: T044, T049, T052, T058, T063, T074; data-model 2.2 a 2.7 e 6.1)

CHAIN: list[tuple[str, set[str]]] = [
    ("0001_foundation_base", {"app_meta"}),
    ("0002_dyno_sessions_runs", {"simulation_session", "dyno_run"}),
    ("0003_damage_health_reports", {"engine_health", "failure_event", "forensic_report"}),
    ("0004_ecu_calibrations", {"calibration", "calibration_version", "session_calibration"}),
    ("0005_profiles_session_state", {"ecu_session_state", "ecu_base_setup_version"}),
    ("0006_telemetry_datalog", {"datalog"}),
    (
        "0007_scenarios_base",
        {
            "player_profile",
            "scenario",
            "attempt",
            "attempt_run",
            "evaluation",
            "scenario_event",
            "imported_package",
        },
    ),
    ("0008_career", {"career_profiles", "career_jobs"}),
]

EXPECTED_INDEXES: dict[str, set[str]] = {
    "simulation_session": {
        "ix_simulation_session_vehicle_id",
        "ix_simulation_session_state",
        "ix_simulation_session_attempt_id",
    },
    "dyno_run": {"ix_dyno_run_session_id_created_at", "ix_dyno_run_curve_sha256"},
    "failure_event": {"ix_failure_event_session_id_t_sim_s", "ix_failure_event_run_id"},
    "forensic_report": {"ix_forensic_report_session_id"},
    "calibration": {"ix_calibration_vehicle_id_profile_id"},
    "calibration_version": {"ix_calibration_version_content_hash"},
    "ecu_base_setup_version": {"ix_ecu_base_setup_version_setup_hash"},
    "datalog": {"ix_datalog_run_id", "ix_datalog_vehicle_id"},
    "scenario": {"ix_scenario_scenario_sha256"},
    "attempt": {"ix_attempt_scenario_id_origin_started_at", "ix_attempt_profile_id"},
    "scenario_event": {"ix_scenario_event_scenario_id_kind_created_at"},
    "career_jobs": {"ix_career_jobs_attempt_id", "ix_career_jobs_profile_id_status"},
}

EXPECTED_UNIQUES: dict[str, set[str]] = {
    "forensic_report": {"uq_forensic_report_run_id"},
    "datalog": {"uq_datalog_sha256"},
    "attempt": {"uq_attempt_package_sha256"},
    "evaluation": {"uq_evaluation_attempt_id_submission_index"},
}


def _sync(db_file: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{db_file}")

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn: object, _record: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    return engine


@pytest.fixture
def migrated(tmp_path: Path) -> tuple[str, Path]:
    db_file = tmp_path / "chain.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    upgrade(url)
    return url, db_file


def test_chain_is_linear_with_fixed_names() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    previous: str | None = None
    for revision, _ in CHAIN:
        rev = script.get_revision(revision)
        assert rev is not None
        assert rev.down_revision == previous
        previous = revision
    assert script_head() == CHAIN[-1][0]


def test_full_chain_creates_all_tables(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    expected = set().union(*(tables for _, tables in CHAIN)) | {"alembic_version"}
    assert _tables(db_file) == expected
    assert len(expected) == 22  # 19 tabelas (data-model 1.1) + 2 da carreira + alembic_version


def test_indexes_and_uniques(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    engine = _sync(db_file)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        for table, names in EXPECTED_INDEXES.items():
            found = {ix["name"] for ix in insp.get_indexes(table)}
            assert names <= found, (table, found)
        for table, names in EXPECTED_UNIQUES.items():
            found = {uq["name"] for uq in insp.get_unique_constraints(table)}
            assert names <= found, (table, found)
        functional = conn.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE name = 'uq_player_profile_nickname_lower'")
        ).scalar_one()
        assert "lower(nickname)" in functional
        assert "UNIQUE" in functional.upper()
        fks = insp.get_foreign_keys("forensic_report")
        assert {fk["referred_table"] for fk in fks} == {
            "dyno_run",
            "simulation_session",
            "failure_event",
        }
        assert all(fk["options"].get("ondelete") == "RESTRICT" for fk in fks)
        sc_fk = insp.get_foreign_keys("session_calibration")[0]
        assert sc_fk["constrained_columns"] == ["calibration_id", "version"]
        assert insp.get_pk_constraint("attempt_run")["constrained_columns"] == [
            "attempt_id",
            "run_id",
            "pull_index",
        ]
    engine.dispose()


def test_models_match_migrations(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    engine = _sync(db_file)
    with engine.connect() as conn, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, metadata)
    engine.dispose()
    assert diff == []
    assert len(loaded_model_modules()) == 8


@pytest.mark.parametrize("index", range(1, len(CHAIN)))
def test_step_downgrade_removes_only_own_tables(tmp_path: Path, index: int) -> None:
    db_file = tmp_path / f"step{index}.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    target, own = CHAIN[index]
    previous = CHAIN[index - 1][0]
    upgrade(url, target)
    before = _tables(db_file)
    assert own <= before
    downgrade(url, previous)
    assert _tables(db_file) == before - own
    upgrade(url, target)
    assert own <= _tables(db_file)


def test_full_downgrade_and_reupgrade(migrated: tuple[str, Path]) -> None:
    url, db_file = migrated
    downgrade(url, "base")
    assert _tables(db_file) == {"alembic_version"}
    upgrade(url)
    assert len(_tables(db_file)) == 22


def _insert_session(conn: sa.Connection, session_id: str = "s" * 32) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO simulation_session (session_id, vehicle_id, data_version, "
            "catalog_sha256, calibration_id, fuel_id, seed, config_json) VALUES "
            "(:sid, 'hatch-20t-gdi', 1, :sha, 'stock-hatch-20t-gdi-oem-stage', 'e27', 7, '{}')"
        ),
        {"sid": session_id, "sha": "a" * 64},
    )


def test_defaults_checks_and_restrict(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    engine = _sync(db_file)
    with engine.begin() as conn:
        _insert_session(conn)
        row = conn.execute(
            sa.text("SELECT profile_id, sim_hz, state, created_at FROM simulation_session")
        ).one()
        assert (row.profile_id, row.sim_hz, row.state) == ("oem-stage", 1000, "ready")
        assert row.created_at is not None
        conn.execute(
            sa.text(
                "INSERT INTO dyno_run (run_id, session_id, run_type, calibration_id, "
                "calibration_hash, request_json, started_at_tick) VALUES "
                "('01JAB0000000000000000000AB', :sid, 'sweep_pull', 'c', :sha, '{}', 0)"
            ),
            {"sid": "s" * 32, "sha": "b" * 64},
        )
        run = conn.execute(sa.text("SELECT state, curve_raw_json FROM dyno_run")).one()
        assert run.state == "idle"
        assert run.curve_raw_json == "[]"
    bad_statements = [
        "UPDATE simulation_session SET state = 'queued'",
        "UPDATE simulation_session SET sim_hz = 50",
        "UPDATE simulation_session SET fuel_id = 'e85'",
        "UPDATE dyno_run SET abort_reason = 'boom'",
        "DELETE FROM simulation_session",
        "INSERT INTO dyno_run (run_id, session_id, run_type, calibration_id, calibration_hash, "
        "request_json, started_at_tick) VALUES ('X', 'missing', 'sweep_pull', 'c', 'h', '{}', 0)",
    ]
    for statement in bad_statements:
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text(statement))
    engine.dispose()


def test_nickname_unique_case_insensitive(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    engine = _sync(db_file)
    insert = sa.text("INSERT INTO player_profile (id, nickname) VALUES (:id, :nick)")
    with engine.begin() as conn:
        conn.execute(insert, {"id": "p1", "nick": "Lucas"})
        assert conn.execute(sa.text("SELECT role FROM player_profile")).scalar_one() == "student"
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"id": "p2", "nick": "LUCAS"})
    engine.dispose()


def test_attempt_package_sha_allows_many_nulls(migrated: tuple[str, Path]) -> None:
    _, db_file = migrated
    engine = _sync(db_file)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO scenario (id, kind, scenario_sha256, content_json) "
                "VALUES ('stage1-oem', 'base', :sha, '{}')"
            ),
            {"sha": "c" * 64},
        )
        for attempt_id in ("a1", "a2"):
            conn.execute(
                sa.text(
                    "INSERT INTO attempt (id, scenario_id, nickname, calibration_id, seed) "
                    "VALUES (:id, 'stage1-oem', 'lucas', 'cal', 1)"
                ),
                {"id": attempt_id},
            )
        conn.execute(
            sa.text(
                "INSERT INTO attempt_run (attempt_id, run_id, run_type, valid, trace_json) "
                "VALUES ('a1', 'r1', 'sweep_pull', 1, '[]')"
            )
        )
        pull = conn.execute(sa.text("SELECT pull_index FROM attempt_run")).scalar_one()
        assert pull == 0
        states = conn.execute(sa.text("SELECT DISTINCT state, replay_status FROM attempt")).all()
        assert states == [("preparing", "not_run")]
    engine.dispose()


async def test_orm_round_trip_all_models(app: FastAPI, client: httpx.AsyncClient) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from simremap.db.models.calibration import (
        CalibrationRow,
        CalibrationVersionRow,
        SessionCalibrationRow,
    )
    from simremap.db.models.damage import EngineHealthRow, FailureEventRow, ForensicReportRow
    from simremap.db.models.datalog import DatalogRow
    from simremap.db.models.dyno import DynoRunRow, SimulationSessionRow
    from simremap.db.models.profiles import EcuBaseSetupVersionRow, EcuSessionStateRow
    from simremap.db.models.scenarios import (
        AttemptRow,
        AttemptRunRow,
        EvaluationRow,
        ImportedPackageRow,
        PlayerProfileRow,
        ScenarioEventRow,
        ScenarioRow,
    )

    sid, rid, sha = "s" * 32, "01JAB0000000000000000000AB", "f" * 64
    rows: list[object] = [
        SimulationSessionRow(
            session_id=sid,
            vehicle_id="hatch-20t-gdi",
            data_version=1,
            catalog_sha256=sha,
            calibration_id="cal",
            fuel_id="e27",
            seed=2**63 - 1,
            config_json={"damage_enabled": True},
        ),
        DynoRunRow(
            run_id=rid,
            session_id=sid,
            run_type="sweep_pull",
            calibration_id="cal",
            calibration_hash=sha,
            request_json={"run_type": "sweep_pull"},
            started_at_tick=0,
        ),
        EngineHealthRow(
            session_id=sid, components_json=[], rod_weights_json=[1.0], updated_at_tick=0
        ),
        FailureEventRow(
            failure_event_id="01JAB0000000000000000000EF",
            session_id=sid,
            run_id=rid,
            tick=1,
            t_sim_s=0.001,
            component_id="bearings",
            mode="rod_failure",
            mechanism="bearing_spin",
            catastrophic=True,
            health_after=0.0,
            causal_json={},
        ),
        ForensicReportRow(
            report_id="01JAB0000000000000000000GH",
            run_id=rid,
            session_id=sid,
            failure_event_id="01JAB0000000000000000000EF",
            report_kind="failure",
            report_json={},
            report_sha256=sha,
            generator_version="1.0.0",
        ),
        CalibrationRow(
            calibration_id="cal", vehicle_id="hatch-20t-gdi", profile_id="oem-stage", name="n"
        ),
        CalibrationVersionRow(calibration_id="cal", version=1, content_hash=sha, payload_json="{}"),
        SessionCalibrationRow(
            session_id=sid, calibration_id="cal", version=1, content_hash=sha, applied_t_sim_s=0.0
        ),
        EcuSessionStateRow(session_id=sid, profile_id="ft-pro"),
        EcuBaseSetupVersionRow(
            session_id=sid, version=1, profile_id="ft-pro", payload_json="{}", setup_hash=sha
        ),
        DatalogRow(
            log_id=rid,
            run_id=rid,
            vehicle_id="hatch-20t-gdi",
            sha256=sha,
            sim_hz=1000,
            n_samples=10,
            n_channels=5,
            compressed_bytes=100,
            path=f"logs/{rid}.simlog.gz",
            terminal_state="completed",
        ),
        PlayerProfileRow(id="p1", nickname="lucas"),
        ScenarioRow(id="cenario-teste-orm", kind="base", scenario_sha256=sha, content_json={}),
        AttemptRow(
            id="a1",
            scenario_id="cenario-teste-orm",
            profile_id="p1",
            nickname="lucas",
            calibration_id="cal",
            seed=1,
        ),
        AttemptRunRow(
            attempt_id="a1", run_id=rid, run_type="sweep_pull", valid=True, trace_json={}
        ),
        EvaluationRow(id="e1", attempt_id="a1", submission_index=1, result_json={}),
        ScenarioEventRow(
            id="ev1",
            kind="attempt_started",
            scenario_id="cenario-teste-orm",
            attempt_id="a1",
            data_json={},
        ),
        ImportedPackageRow(
            sha256=sha, kind="challenge", scenario_id="cenario-teste-orm", size_bytes=10
        ),
    ]
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    async with maker() as session:
        for row in rows:
            session.add(row)
            await session.flush()
        await session.commit()
    async with maker() as session:
        loaded = await session.get(SimulationSessionRow, sid)
        assert loaded is not None
        assert loaded.seed == 2**63 - 1
        assert loaded.config_json == {"damage_enabled": True}
        assert loaded.created_at.tzinfo is not None
        attempt_row = await session.get(AttemptRow, "a1")
        assert attempt_row is not None
        assert attempt_row.hints_revealed_json == []
        assert attempt_row.state == "preparing"
        evaluation_row = await session.get(EvaluationRow, "e1")
        assert evaluation_row is not None and evaluation_row.evaluation_mismatch is False
