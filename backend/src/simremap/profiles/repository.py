"""Estado de ECU por sessão e versões da ``BaseSetup`` (data-model 2.5; RF-17 a RF-19).

- ``ecu_session_state``: perfil, ``ecu_state``, pacote, snapshot OEM, calibração standalone,
  última versão da base e ``hardware_override_json`` (nunca exposto pela API).
- ``ecu_base_setup_version``: versões imutáveis (``payload_json`` canônico + ``setup_hash``).
- Concorrência otimista da base: a versão nova é ``latest + 1``; ``base_version`` diferente
  da última ⇒ 409 ``BASE_SETUP_VERSION_CONFLICT`` com ``latest_version``.
- Uma transação por caso de uso (``commit`` explícito); falha de I/O ⇒ 503
  ``DATABASE_UNAVAILABLE`` com ``Retry-After: 2`` e rollback (EC-04).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from simremap.db.base import utcnow
from simremap.db.models.profiles import EcuBaseSetupVersionRow, EcuSessionStateRow
from simremap.ecu.calibration import canonical_json, round_floats
from simremap.profiles.contracts import BaseSetup, EcuState, FeaturePackage, HardwareOverride
from simremap.profiles.errors import database_unavailable, profile_error
from simremap.profiles.setup import setup_hash

__all__ = ["BaseSetupVersion", "EcuSessionState", "ProfileRepository"]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class EcuSessionState:
    session_id: str
    profile_id: str
    ecu_state: EcuState
    feature_package: FeaturePackage = "base"
    oem_snapshot_calibration_id: str | None = None
    oem_snapshot_version: int | None = None
    standalone_calibration_id: str | None = None
    latest_base_setup_version: int | None = None
    hardware_override: HardwareOverride | None = None


@dataclass(frozen=True, slots=True)
class BaseSetupVersion:
    session_id: str
    version: int
    profile_id: str
    base_setup: BaseSetup
    setup_hash: str
    created_at: datetime


def _state(row: EcuSessionStateRow) -> EcuSessionState:
    override = (
        HardwareOverride.model_validate_json(row.hardware_override_json)
        if row.hardware_override_json
        else None
    )
    return EcuSessionState(
        session_id=row.session_id,
        profile_id=row.profile_id,
        ecu_state=row.ecu_state,  # type: ignore[arg-type]
        feature_package=row.feature_package,  # type: ignore[arg-type]
        oem_snapshot_calibration_id=row.oem_snapshot_calibration_id,
        oem_snapshot_version=row.oem_snapshot_version,
        standalone_calibration_id=row.standalone_calibration_id,
        latest_base_setup_version=row.latest_base_setup_version,
        hardware_override=override,
    )


def _payload(base: BaseSetup) -> str:
    return canonical_json(round_floats(base.model_dump(mode="json")))


class ProfileRepository:
    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utcnow) -> None:
        self.session = session
        self.clock = clock

    async def _guard(self, op: Callable[[], Awaitable[T]], *, write: bool) -> T:
        try:
            result = await op()
            if write:
                await self.session.commit()
            return result
        except (OperationalError, DBAPIError) as exc:
            await self.session.rollback()
            raise database_unavailable() from exc
        except BaseException:
            if write:
                await self.session.rollback()
            raise

    # ------------------------------------------------------------------ estado

    async def get_state(self, session_id: str) -> EcuSessionState | None:
        async def op() -> EcuSessionState | None:
            row = await self.session.get(EcuSessionStateRow, session_id)
            return _state(row) if row is not None else None

        return await self._guard(op, write=False)

    async def save_state(
        self,
        state: EcuSessionState,
        base: BaseSetup | None = None,
        *,
        base_version: int | None = None,
    ) -> BaseSetupVersion | None:
        """Grava o estado e, com ``base``, uma versão nova da base (mesma transação).

        ``base_version`` é a versão sobre a qual o cliente editou (``None`` só na primeira).
        """

        async def op() -> BaseSetupVersion | None:
            row = await self.session.get(EcuSessionStateRow, state.session_id)
            now = self.clock()
            if row is None:
                row = EcuSessionStateRow(session_id=state.session_id, profile_id=state.profile_id)
                self.session.add(row)
                await self.session.flush()  # FK de ecu_base_setup_version (D-09)
            created: BaseSetupVersion | None = None
            latest = row.latest_base_setup_version
            if base is not None:
                if base_version != latest:
                    raise profile_error(
                        "BASE_SETUP_VERSION_CONFLICT",
                        f"A base foi alterada: versão atual {latest}, enviada {base_version}.",
                        latest_version=latest,
                        base_version=base_version,
                    )
                version = (latest or 0) + 1
                digest = setup_hash(base)
                self.session.add(
                    EcuBaseSetupVersionRow(
                        session_id=state.session_id,
                        version=version,
                        profile_id=state.profile_id,
                        payload_json=_payload(base),
                        setup_hash=digest,
                        created_at=now,
                    )
                )
                latest = version
                created = BaseSetupVersion(
                    state.session_id, version, state.profile_id, base, digest, now
                )
            row.profile_id = state.profile_id
            row.ecu_state = state.ecu_state
            row.feature_package = state.feature_package
            row.oem_snapshot_calibration_id = state.oem_snapshot_calibration_id
            row.oem_snapshot_version = state.oem_snapshot_version
            row.standalone_calibration_id = state.standalone_calibration_id
            row.latest_base_setup_version = latest
            row.hardware_override_json = (
                state.hardware_override.model_dump_json() if state.hardware_override else None
            )
            row.updated_at = now
            await self.session.flush()
            return created

        return await self._guard(op, write=True)

    async def set_hardware_override(
        self, session_id: str, profile_id: str, override: HardwareOverride | None
    ) -> None:
        """Defeito oculto do training-scenarios (RF-29); cria o estado se faltar."""

        async def op() -> None:
            row = await self.session.get(EcuSessionStateRow, session_id)
            if row is None:
                row = EcuSessionStateRow(session_id=session_id, profile_id=profile_id)
                self.session.add(row)
            row.hardware_override_json = override.model_dump_json() if override else None
            row.updated_at = self.clock()
            await self.session.flush()

        await self._guard(op, write=True)

    # ------------------------------------------------------------------ base

    async def get_base(
        self, session_id: str, version: int | None = None
    ) -> BaseSetupVersion | None:
        async def op() -> BaseSetupVersion | None:
            stmt = select(EcuBaseSetupVersionRow).where(
                col(EcuBaseSetupVersionRow.session_id) == session_id
            )
            if version is not None:
                stmt = stmt.where(col(EcuBaseSetupVersionRow.version) == version)
            stmt = stmt.order_by(col(EcuBaseSetupVersionRow.version).desc()).limit(1)
            row = (await self.session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return BaseSetupVersion(
                session_id=row.session_id,
                version=row.version,
                profile_id=row.profile_id,
                base_setup=BaseSetup.model_validate_json(row.payload_json),
                setup_hash=row.setup_hash,
                created_at=row.created_at,
            )

        return await self._guard(op, write=False)

    async def count_base_versions(self, session_id: str) -> int:
        async def op() -> int:
            stmt = select(col(EcuBaseSetupVersionRow.version)).where(
                col(EcuBaseSetupVersionRow.session_id) == session_id
            )
            return len((await self.session.execute(stmt)).scalars().all())

        return await self._guard(op, write=False)
