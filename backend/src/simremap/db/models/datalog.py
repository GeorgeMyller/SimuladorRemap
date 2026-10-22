"""Tabela ``datalog`` do telemetry-datalogger (data-model 2.6, migração ``0006_telemetry_datalog``).

O conteúdo do log vive em ``/data/logs/{run_id}.simlog.gz``; a linha guarda os metadados.
``run_id`` e ``session_id`` são FKs lógicas (logs importados vêm de outra estação).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, UniqueConstraint, false, func, text
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import check_expr, check_in

__all__ = ["DATALOG_SOURCES", "TERMINAL_STATES", "DatalogRow"]

DATALOG_SOURCES: tuple[str, ...] = ("simulated", "imported")
TERMINAL_STATES: tuple[str, ...] = ("completed", "aborted", "engine_failed")


class DatalogRow(SQLModel, table=True):
    __tablename__ = "datalog"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        UniqueConstraint("sha256", name="uq_datalog_sha256"),
        check_expr("sim_hz >= 100 AND sim_hz <= 1000", "sim_hz_range"),
        check_expr("n_samples >= 0", "n_samples_non_negative"),
        check_expr("n_channels >= 1 AND n_channels <= 256", "n_channels_range"),
        check_in("terminal_state", TERMINAL_STATES),
        check_in("source", DATALOG_SOURCES),
    )

    log_id: str = Field(primary_key=True, max_length=36)
    run_id: str | None = Field(default=None, max_length=26, index=True)
    session_id: str | None = Field(default=None, max_length=36)
    vehicle_id: str = Field(max_length=48, index=True)
    sha256: str = Field(max_length=64)
    format_version: int = Field(default=1, sa_column_kwargs={"server_default": text("1")})
    sim_hz: int
    n_samples: int
    n_channels: int
    compressed_bytes: int = Field(sa_type=BigInteger)
    path: str = Field(max_length=255)
    terminal_state: str = Field(max_length=16)
    truncated: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    source: str = Field(
        default="simulated", max_length=16, sa_column_kwargs={"server_default": "simulated"}
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
