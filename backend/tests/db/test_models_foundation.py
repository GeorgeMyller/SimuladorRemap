"""Modelo AppMeta e tipos base (data-model 2.1, 1.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from simremap.db.base import UTCDateTime, new_uuid, utcnow
from simremap.db.models.foundation import APP_META_KEYS, AppMeta


async def test_app_meta_roundtrip_utc(db_session: AsyncSession) -> None:
    db_session.add(AppMeta(key="probe_uuid", value=new_uuid()))
    await db_session.commit()
    row = (
        await db_session.execute(select(AppMeta).where(AppMeta.key == "probe_uuid"))
    ).scalar_one()
    assert len(row.value) == 36
    db_session.expunge_all()
    fresh = (
        await db_session.execute(select(AppMeta).where(AppMeta.key == "probe_uuid"))
    ).scalar_one()
    assert fresh.updated_at.tzinfo is not None
    assert fresh.updated_at.utcoffset() == timedelta(0)


async def test_session_rollback_discards(db_session: AsyncSession) -> None:
    db_session.add(AppMeta(key="probe_rollback", value="x"))
    await db_session.rollback()
    rows = (await db_session.execute(select(AppMeta))).scalars().all()
    assert "probe_rollback" not in {r.key for r in rows}
    assert {r.key for r in rows} == set(APP_META_KEYS)


def test_utc_datetime_type() -> None:
    col = UTCDateTime()
    aware = datetime(2026, 10, 18, 12, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert col.process_bind_param(aware, None) == datetime(2026, 10, 18, 15, 0, tzinfo=UTC)  # type: ignore[arg-type]
    assert col.process_bind_param(None, None) is None  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fuso"):
        col.process_bind_param(datetime(2026, 1, 1), None)  # type: ignore[arg-type]
    naive = datetime(2026, 1, 1, 0, 0)
    assert col.process_result_value(naive, None) == naive.replace(tzinfo=UTC)  # type: ignore[arg-type]
    assert col.process_result_value(aware, None).utcoffset() == timedelta(0)  # type: ignore[arg-type, union-attr]
    assert col.process_result_value(None, None) is None  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        col.process_result_value("2026-01-01", None)  # type: ignore[arg-type]
    assert utcnow().tzinfo is UTC
