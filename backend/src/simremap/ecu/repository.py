"""Persistência de calibrações com versões imutáveis (ecu-core RF-04, RF-05, RF-25, RF-26; D-15).

- Cada ``PUT``/``PATCH`` aceite cria uma versão nova; nenhuma versão é alterada.
- Reversão (``revert_to_version``) grava uma versão nova com o conteúdo da antiga
  (``metadata.source = "revert"``, ``parent_version = base_version``).
- Concorrência otimista: ``UPDATE calibration SET latest_version = n + 1 WHERE
  latest_version = base_version``; 0 linhas ⇒ 409 ``CALIBRATION_VERSION_CONFLICT`` com
  ``latest_version`` e sem versão nova. Acima de 1000 versões: 409
  ``CALIBRATION_VERSION_LIMIT``.
- Transação única por operação; falha de I/O ⇒ 503 ``DATABASE_UNAVAILABLE`` com
  ``Retry-After: 2`` e nada gravado (EC-09).
- ``payload_json`` guarda a calibração sem ``calibration_id``/``version`` em JSON
  canónico (D-08).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from simremap.db.base import utcnow
from simremap.db.models.calibration import (
    CalibrationRow,
    CalibrationVersionRow,
    SessionCalibrationRow,
)
from simremap.ecu.calibration import (
    CONTENT_FIELDS,
    Calibration,
    CalibrationContent,
    CalibrationMetadata,
    CalibrationPage,
    CalibrationSummary,
    CalibrationVersionInfo,
    TablePatch,
    apply_table_patch,
    build_calibration,
    canonical_json,
    parse_content,
)
from simremap.ecu.errors import database_unavailable, ecu_error
from simremap.ecu.limits import MAX_CALIBRATION_VERSIONS
from simremap.ecu.tables import Table2D, Table3D

__all__ = ["CalibrationRepository", "SessionCalibrationState"]

T = TypeVar("T")


def _payload_json(cal: Calibration) -> str:
    return canonical_json(cal.model_dump(mode="json", exclude={"calibration_id", "version"}))


def _from_row(row: CalibrationVersionRow) -> Calibration:
    data: dict[str, Any] = json.loads(row.payload_json)
    return Calibration.model_validate(
        {**data, "calibration_id": row.calibration_id, "version": row.version}
    )


def _version_info(row: CalibrationVersionRow) -> CalibrationVersionInfo:
    return CalibrationVersionInfo(
        version=row.version,
        parent_version=row.parent_version,
        content_hash=row.content_hash,
        source=row.source,
        author_nickname=row.author_nickname,
        change_summary=row.change_summary,
        created_at=row.created_at,
    )


class SessionCalibrationState:
    """Calibração ativa de uma sessão (``session_calibration``)."""

    __slots__ = ("applied_t_sim_s", "calibration_id", "content_hash", "session_id", "version")

    def __init__(self, row: SessionCalibrationRow) -> None:
        self.session_id = row.session_id
        self.calibration_id = row.calibration_id
        self.version = row.version
        self.content_hash = row.content_hash
        self.applied_t_sim_s = row.applied_t_sim_s


class CalibrationRepository:
    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utcnow) -> None:
        self.session = session
        self.clock = clock

    # ------------------------------------------------------------------ infraestrutura

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

    async def _header(self, calibration_id: str) -> CalibrationRow:
        row = await self.session.get(CalibrationRow, calibration_id)
        if row is None:
            raise ecu_error(
                "CALIBRATION_NOT_FOUND",
                f"A calibração {calibration_id} não existe.",
                calibration_id=calibration_id,
            )
        return row

    async def _version_row(self, calibration_id: str, version: int) -> CalibrationVersionRow:
        row = await self.session.get(CalibrationVersionRow, (calibration_id, version))
        if row is None:
            raise ecu_error(
                "CALIBRATION_VERSION_NOT_FOUND",
                f"A calibração {calibration_id} não tem a versão {version}.",
                calibration_id=calibration_id,
                version=version,
            )
        return row

    # ------------------------------------------------------------------ leitura

    async def exists(self, calibration_id: str) -> bool:
        async def op() -> bool:
            return await self.session.get(CalibrationRow, calibration_id) is not None

        return await self._guard(op, write=False)

    async def get(self, calibration_id: str, version: int | None = None) -> Calibration:
        async def op() -> Calibration:
            header = await self._header(calibration_id)
            row = await self._version_row(calibration_id, version or header.latest_version)
            return _from_row(row)

        return await self._guard(op, write=False)

    async def versions(self, calibration_id: str) -> list[CalibrationVersionInfo]:
        async def op() -> list[CalibrationVersionInfo]:
            await self._header(calibration_id)
            rows = await self.session.scalars(
                select(CalibrationVersionRow)
                .where(col(CalibrationVersionRow.calibration_id) == calibration_id)
                .order_by(col(CalibrationVersionRow.version))
            )
            return [_version_info(r) for r in rows]

        return await self._guard(op, write=False)

    async def list(
        self,
        vehicle_id: str | None = None,
        profile_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CalibrationPage:
        async def op() -> CalibrationPage:
            conds: list[ColumnElement[bool]] = []
            if vehicle_id is not None:
                conds.append(col(CalibrationRow.vehicle_id) == vehicle_id)
            if profile_id is not None:
                conds.append(col(CalibrationRow.profile_id) == profile_id)
            total = await self.session.scalar(
                select(func.count()).select_from(CalibrationRow).where(*conds)
            )
            stmt = (
                select(CalibrationRow, col(CalibrationVersionRow.content_hash))
                .join(
                    CalibrationVersionRow,
                    (
                        col(CalibrationVersionRow.calibration_id)
                        == col(CalibrationRow.calibration_id)
                    )
                    & (col(CalibrationVersionRow.version) == col(CalibrationRow.latest_version)),
                )
                .where(*conds)
                .order_by(col(CalibrationRow.updated_at).desc(), col(CalibrationRow.calibration_id))
                .limit(limit)
                .offset(offset)
            )
            rows = (await self.session.execute(stmt)).all()
            items = [
                CalibrationSummary(
                    calibration_id=row.calibration_id,
                    vehicle_id=row.vehicle_id,
                    profile_id=row.profile_id,
                    name=row.name,
                    latest_version=row.latest_version,
                    content_hash=content_hash,
                    updated_at=row.updated_at,
                )
                for row, content_hash in rows
            ]
            return CalibrationPage(items=items, total=int(total or 0))

        return await self._guard(op, write=False)

    # ------------------------------------------------------------------ escrita

    async def create(
        self,
        content: CalibrationContent,
        metadata: CalibrationMetadata,
        calibration_id: str | None = None,
    ) -> Calibration:
        """Grava a versão 1 de uma calibração nova (``calibration_id`` UUID se omitido)."""
        cal_id = calibration_id or str(uuid.uuid4())
        now = self.clock()
        cal = build_calibration(
            content,
            calibration_id=cal_id,
            version=1,
            parent_version=None,
            metadata=metadata,
            created_at=now,
        )

        async def op() -> Calibration:
            self.session.add(
                CalibrationRow(
                    calibration_id=cal_id,
                    vehicle_id=content.vehicle_id,
                    profile_id=content.profile_id.value,
                    name=metadata.name,
                    latest_version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await self.session.flush()
            self.session.add(self._version_from(cal))
            await self.session.flush()
            return cal

        return await self._guard(op, write=True)

    def _version_from(self, cal: Calibration) -> CalibrationVersionRow:
        return CalibrationVersionRow(
            calibration_id=cal.calibration_id,
            version=cal.version,
            parent_version=cal.parent_version,
            content_hash=cal.content_hash,
            payload_json=_payload_json(cal),
            author_nickname=cal.metadata.author_nickname,
            source=cal.metadata.source,
            change_summary=cal.metadata.change_summary,
            created_at=cal.created_at,
        )

    @staticmethod
    def _check_base(header: CalibrationRow, base_version: int) -> None:
        if base_version != header.latest_version:
            raise ecu_error(
                "CALIBRATION_VERSION_CONFLICT",
                f"A versão de base {base_version} está desatualizada; "
                f"a última é {header.latest_version}. Releia e repita.",
                latest_version=header.latest_version,
                base_version=base_version,
            )

    async def _append(
        self,
        header: CalibrationRow,
        base_version: int,
        content: CalibrationContent,
        metadata: CalibrationMetadata,
    ) -> Calibration:
        self._check_base(header, base_version)
        new_version = base_version + 1
        if new_version > MAX_CALIBRATION_VERSIONS:
            raise ecu_error(
                "CALIBRATION_VERSION_LIMIT",
                f"A calibração atingiu {MAX_CALIBRATION_VERSIONS} versões; clone-a para continuar.",
                latest_version=header.latest_version,
            )
        now = self.clock()
        cal = build_calibration(
            content,
            calibration_id=header.calibration_id,
            version=new_version,
            parent_version=base_version,
            metadata=metadata,
            created_at=now,
        )
        result = await self.session.execute(
            update(CalibrationRow)
            .where(col(CalibrationRow.calibration_id) == header.calibration_id)
            .where(col(CalibrationRow.latest_version) == base_version)
            .values(latest_version=new_version, name=metadata.name, updated_at=now)
        )
        if getattr(result, "rowcount", 0) != 1:
            latest = await self.session.scalar(
                select(col(CalibrationRow.latest_version)).where(
                    col(CalibrationRow.calibration_id) == header.calibration_id
                )
            )
            raise ecu_error(
                "CALIBRATION_VERSION_CONFLICT",
                "Outro cliente gravou uma versão nova; releia e repita.",
                latest_version=int(latest or 0),
                base_version=base_version,
            )
        self.session.add(self._version_from(cal))
        await self.session.flush()
        return cal

    async def replace(
        self,
        calibration_id: str,
        base_version: int,
        content: CalibrationContent,
        metadata: CalibrationMetadata,
    ) -> Calibration:
        """``PUT`` com o conteúdo completo: nova versão (``parent_version = base_version``)."""

        async def op() -> Calibration:
            header = await self._header(calibration_id)
            if content.profile_id.value != header.profile_id:
                raise ecu_error(
                    "CALIBRATION_PROFILE_IMMUTABLE",
                    f"O perfil {header.profile_id} da calibração não pode mudar.",
                    profile_id=header.profile_id,
                )
            if content.vehicle_id != header.vehicle_id:
                raise ecu_error(
                    "CALIBRATION_VEHICLE_MISMATCH",
                    f"O veículo {header.vehicle_id} da calibração não pode mudar.",
                    vehicle_id=header.vehicle_id,
                )
            return await self._append(header, base_version, content, metadata)

        return await self._guard(op, write=True)

    async def revert(
        self,
        calibration_id: str,
        base_version: int,
        revert_to_version: int,
        *,
        change_summary: str = "",
        author_nickname: str | None = None,
    ) -> Calibration:
        """Undo por versões: nova versão com o conteúdo de ``revert_to_version`` (Fluxo B)."""

        async def op() -> Calibration:
            header = await self._header(calibration_id)
            old = _from_row(await self._version_row(calibration_id, revert_to_version))
            meta = old.metadata.model_copy(
                update={
                    "source": "revert",
                    "change_summary": change_summary or f"revert para a versão {revert_to_version}",
                    "author_nickname": author_nickname,
                }
            )
            return await self._append(header, base_version, old.content(), meta)

        return await self._guard(op, write=True)

    async def patch_table(
        self, calibration_id: str, table_id: str, patch: TablePatch
    ) -> tuple[Calibration, Table2D | Table3D]:
        """``PATCH`` de uma tabela: nova versão com a tabela alterada (RF-26)."""

        async def op() -> tuple[Calibration, Table2D | Table3D]:
            header = await self._header(calibration_id)
            self._check_base(header, patch.base_version)
            current = _from_row(await self._version_row(calibration_id, header.latest_version))
            table = current.tables.get(table_id)
            if table is None:
                raise ecu_error(
                    "TABLE_NOT_FOUND",
                    f"A tabela {table_id} não existe na calibração.",
                    table_id=table_id,
                )
            new_table = apply_table_patch(table, patch)
            data = current.model_dump(include=set(CONTENT_FIELDS))
            data["tables"] = {**data["tables"], table_id: new_table.model_dump()}
            content = parse_content(data)
            summary = patch.change_summary or f"{table_id}: {len(patch.cells)} células"
            meta = current.metadata.model_copy(update={"source": "user", "change_summary": summary})
            cal = await self._append(header, patch.base_version, content, meta)
            return cal, new_table

        return await self._guard(op, write=True)

    # ------------------------------------------------------------------ sessão

    async def get_session_calibration(self, session_id: str) -> SessionCalibrationState | None:
        async def op() -> SessionCalibrationState | None:
            row = await self.session.get(SessionCalibrationRow, session_id)
            return SessionCalibrationState(row) if row is not None else None

        return await self._guard(op, write=False)

    async def set_session_calibration(
        self, session_id: str, cal: Calibration, applied_t_sim_s: float
    ) -> None:
        async def op() -> None:
            row = await self.session.get(SessionCalibrationRow, session_id)
            if row is None:
                self.session.add(
                    SessionCalibrationRow(
                        session_id=session_id,
                        calibration_id=cal.calibration_id,
                        version=cal.version,
                        content_hash=cal.content_hash,
                        applied_t_sim_s=applied_t_sim_s,
                    )
                )
            else:
                row.calibration_id = cal.calibration_id
                row.version = cal.version
                row.content_hash = cal.content_hash
                row.applied_t_sim_s = applied_t_sim_s
            await self.session.flush()

        await self._guard(op, write=True)
