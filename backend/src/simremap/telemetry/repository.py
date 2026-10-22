"""Persistência do datalog: arquivo em ``Settings.data_dir/logs`` e linha ``datalog`` (tel RF-15,
RF-18; EC-07, EC-08, EC-11; data-model 2.6).

- ``save``: grava ``logs/{log_id}.simlog.gz`` (escrita atómica numa thread, 3 novas tentativas
  com 0,2/0,5/1,0 s; persistindo a falha, ``STORAGE_FULL``) e insere a linha com ``path``
  relativo a ``data_dir``; ``sha256`` repetido devolve ``LOG_ALREADY_IMPORTED`` com o
  ``log_id`` existente (nenhuma escrita).
- ``load``: lê e valida o arquivo (``LOG_CORRUPTED`` em gzip inválido ou hash diferente do
  da linha). O nome do arquivo é sempre gerado pelo servidor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from simremap.core.logging import get_logger
from simremap.db.models.datalog import DatalogRow
from simremap.telemetry.datalog import LogData, read_simlog, write_simlog
from simremap.telemetry.errors import telemetry_error

__all__ = ["LOGS_DIR", "WRITE_RETRY_DELAYS_S", "DatalogRepository"]

log = get_logger("simremap.telemetry")

LOGS_DIR: Final = "logs"
WRITE_RETRY_DELAYS_S: Final = (0.2, 0.5, 1.0)

Sleep = Callable[[float], Awaitable[None]]


def _aware(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class DatalogRepository:
    """Arquivos ``.simlog.gz`` + tabela ``datalog``."""

    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        data_dir: Path,
        *,
        retry_delays: tuple[float, ...] = WRITE_RETRY_DELAYS_S,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.maker = maker
        self.data_dir = Path(data_dir)
        self.retry_delays = retry_delays
        self._sleep = sleep

    def relative_path(self, log_id: str) -> str:
        return f"{LOGS_DIR}/{log_id}.simlog.gz"

    def absolute_path(self, relative: str) -> Path:
        path = (self.data_dir / relative).resolve()
        root = (self.data_dir / LOGS_DIR).resolve()
        if root not in path.parents:
            raise telemetry_error("LOG_CORRUPTED", "Caminho de log fora de data_dir/logs.")
        return path

    # ------------------------------------------------------------------ leitura
    async def get(self, log_id: str) -> DatalogRow | None:
        async with self.maker() as session:
            return await session.get(DatalogRow, log_id)

    async def by_sha256(self, sha256: str) -> DatalogRow | None:
        async with self.maker() as session:
            result = await session.execute(
                select(DatalogRow).where(col(DatalogRow.sha256) == sha256)
            )
            return result.scalars().first()

    async def load(self, row: DatalogRow) -> LogData:
        """Log do arquivo da linha, validado contra o ``sha256`` registado."""
        path = self.absolute_path(row.path)
        if not path.exists():
            raise telemetry_error(
                "LOG_NOT_FOUND", f"O arquivo do log {row.log_id} não existe.", log_id=row.log_id
            )
        data = await asyncio.to_thread(read_simlog, path)
        if data.sha256 != row.sha256:
            log.error("datalog.corrupted", log_id=row.log_id, run_id=row.run_id)
            raise telemetry_error(
                "LOG_CORRUPTED",
                f"O SHA-256 do arquivo do log {row.log_id} difere do registado.",
                expected=row.sha256,
                computed=data.sha256,
            )
        data.log_id = row.log_id
        data.created_at = _aware(row.created_at)
        data.source = row.source
        return data

    # ------------------------------------------------------------------ escrita
    async def write_file(self, relative: str, data: LogData) -> int:
        """Escreve o arquivo com novas tentativas (EC-07); ``STORAGE_FULL`` se falhar."""
        path = self.data_dir / relative
        last: OSError | None = None
        for attempt in range(len(self.retry_delays) + 1):
            try:
                return await asyncio.to_thread(write_simlog, path, data)
            except OSError as exc:
                last = exc
                if attempt < len(self.retry_delays):
                    await self._sleep(self.retry_delays[attempt])
        log.error("datalog.write_failed", path=relative, reason=type(last).__name__)
        raise telemetry_error(
            "STORAGE_FULL", f"Não foi possível gravar o log: {last}"[:500], path=relative
        )

    async def save(self, data: LogData, *, log_id: str, source: str) -> DatalogRow:
        """Grava arquivo e linha; ``LOG_ALREADY_IMPORTED`` se o ``sha256`` já existe."""
        existing = await self.by_sha256(data.sha256)
        if existing is not None:
            raise telemetry_error(
                "LOG_ALREADY_IMPORTED",
                f"O log já existe com o log_id {existing.log_id}.",
                log_id=existing.log_id,
            )
        relative = self.relative_path(log_id)
        size = await self.write_file(relative, data)
        header = data.header
        row = DatalogRow(
            log_id=log_id,
            run_id=header.run_id,
            session_id=header.session_id,
            vehicle_id=header.vehicle_id,
            sha256=data.sha256,
            format_version=header.format_version,
            sim_hz=header.sim_hz,
            n_samples=header.n_samples,
            n_channels=len(header.channels),
            compressed_bytes=size,
            path=relative,
            terminal_state=header.terminal_state,
            truncated=header.truncated,
            source=source,
            created_at=datetime.now(UTC),
        )
        try:
            async with self.maker() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
        except IntegrityError as exc:
            if source == "imported":
                (self.data_dir / relative).unlink(missing_ok=True)
            again = await self.by_sha256(data.sha256)
            raise telemetry_error(
                "LOG_ALREADY_IMPORTED",
                "O log já existe.",
                log_id=None if again is None else again.log_id,
            ) from exc
        data.log_id = log_id
        data.created_at = _aware(row.created_at)
        data.source = source
        log.info(
            "datalog.written",
            log_id=log_id,
            run_id=header.run_id,
            sha256=data.sha256,
            bytes=size,
            source=source,
        )
        return row
