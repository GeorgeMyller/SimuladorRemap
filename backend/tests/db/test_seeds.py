"""Seeds idempotentes de ``app_meta`` (T407; data-model 6.3)."""

from __future__ import annotations

import uuid
from typing import Any

from simremap.db.engine import build_engine, build_sessionmaker
from simremap.db.migrate import upgrade_engine
from simremap.db.models.foundation import AppMeta
from simremap.db.seeds import has_app_meta, seed_app_meta


async def test_seed_app_meta_idempotent(settings_factory: Any) -> None:
    engine = build_engine(settings_factory())
    maker = build_sessionmaker(engine)
    try:
        assert await has_app_meta(engine) is False
        await upgrade_engine(engine)
        assert await has_app_meta(engine) is True
        first = await seed_app_meta(maker, "0.1.0")
        assert first.created is True
        assert uuid.UUID(first.install_id).version == 4
        again = await seed_app_meta(maker, "0.1.0")
        assert again.created is False
        assert again.install_id == first.install_id
        assert again.schema_created_at == first.schema_created_at
        upgraded = await seed_app_meta(maker, "0.3.0-rc.1")
        assert upgraded.last_boot_app_version == "0.3.0-rc.1"
        assert upgraded.install_id == first.install_id
        async with maker() as session:
            row = await session.get(AppMeta, "last_boot_app_version")
            assert row is not None and row.value == "0.3.0-rc.1"
    finally:
        await engine.dispose()
