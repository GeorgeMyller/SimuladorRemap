"""Serviço do Modo Carreira (002 RF-25, RN-07; D-15).

1. Aceite: perfil de jogador existente, ordem existente, nenhum job ``accepted`` do perfil
   (409 ``CAREER_JOB_ALREADY_OPEN``) e reputação ≥ ``min_reputation`` (409
   ``CAREER_REPUTATION_TOO_LOW``); a tentativa do cenário nasce pelo ``AttemptService``.
2. Liquidação: lê a tentativa (com a mesma atualização do ``GET /attempts/{id}``); ativa ⇒
   409 ``CAREER_ATTEMPT_NOT_FINISHED``. Motor quebrado (falha catastrófica numa puxada ou
   motor restaurado) ⇒ ``engine_broken``: debita o custo do motor (e credita o pagamento só
   se a tentativa foi aprovada). Senão ``passed`` ⇒ ``paid``; ``failed_final``/``expired``
   ⇒ ``failed``; ``abandoned``/``failed_to_start`` ⇒ ``abandoned``. O saldo pode ficar
   negativo; a reputação fica entre 0 e 100. Job já liquidado ⇒ devolvido sem mudança.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import cache
from importlib import resources
from typing import Final

from simremap.career.contracts import CareerJob, CareerProfile, JobStatus, WorkOrder
from simremap.career.errors import career_error
from simremap.career.repository import CareerRepository, Settlement
from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.db.base import utcnow
from simremap.db.models.career import CareerJobRow
from simremap.scenarios.attempts import ACTIVE_STATES, AttemptService, StoredRun
from simremap.scenarios.contracts import AttemptView, PlayerProfile
from simremap.scenarios.profiles import ProfileService

__all__ = ["REPUTATION_CHANGE", "CareerService", "load_orders", "settlement_for"]

log = get_logger("simremap.career")

REPUTATION_CHANGE: Final[dict[JobStatus, int]] = {
    JobStatus.PAID: 5,
    JobStatus.FAILED: -5,
    JobStatus.ENGINE_BROKEN: -10,
    JobStatus.ABANDONED: -3,
}
_FAILED_STATES: Final = frozenset({"failed_final", "expired"})


@cache
def load_orders() -> dict[str, WorkOrder]:
    """Ordens de serviço fixas de ``career/orders.json``, por ``order_id``."""
    text = resources.files("simremap.career").joinpath("orders.json").read_text(encoding="utf-8")
    orders = [WorkOrder.model_validate(item) for item in json.loads(text)]
    return {order.order_id: order for order in orders}


def settlement_for(state: str, *, engine_broken: bool, job: CareerJob, now: datetime) -> Settlement:
    """Status, delta de saldo e mudança de reputação de uma tentativa terminada (RN-07)."""
    passed = state == "passed"
    if engine_broken:
        delta = (job.payout_brl if passed else 0) - job.engine_cost_brl
        return Settlement(
            JobStatus.ENGINE_BROKEN, delta, REPUTATION_CHANGE[JobStatus.ENGINE_BROKEN], now
        )
    if passed:
        return Settlement(JobStatus.PAID, job.payout_brl, REPUTATION_CHANGE[JobStatus.PAID], now)
    if state in _FAILED_STATES:
        return Settlement(JobStatus.FAILED, 0, REPUTATION_CHANGE[JobStatus.FAILED], now)
    blame = 0 if state == "failed_to_start" else REPUTATION_CHANGE[JobStatus.ABANDONED]
    return Settlement(JobStatus.ABANDONED, 0, blame, now)


class CareerService:
    def __init__(
        self,
        repo: CareerRepository,
        attempts: AttemptService,
        profiles: ProfileService,
        *,
        orders: Mapping[str, WorkOrder] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.repo = repo
        self.attempts = attempts
        self.profiles = profiles
        self.orders = load_orders() if orders is None else orders
        self.clock = clock
        self._lock = asyncio.Lock()  # aceite e liquidação em série (estação local)

    # ------------------------------------------------------------------ consulta
    def list_orders(self) -> list[WorkOrder]:
        return list(self.orders.values())

    async def _player(self, profile_id: str) -> PlayerProfile:
        player = await self.profiles.resolve(profile_id, required=True)
        if player is None:  # required=True nunca devolve None
            raise SimRemapError(
                f"O perfil {profile_id} não existe.", code="PLAYER_PROFILE_NOT_FOUND"
            )
        return player

    async def profile(self, profile_id: str) -> CareerProfile:
        player = await self._player(profile_id)
        return await self.repo.ensure_profile(player.profile_id)

    async def jobs(self, profile_id: str) -> list[CareerJob]:
        player = await self._player(profile_id)
        return await self.repo.list_jobs(player.profile_id)

    def _order(self, order_id: str) -> WorkOrder:
        order = self.orders.get(order_id)
        if order is None:
            raise career_error(
                "CAREER_ORDER_NOT_FOUND", f"A ordem {order_id} não existe.", order_id=order_id
            )
        return order

    # ------------------------------------------------------------------ aceite
    async def accept(self, profile_id: str, order_id: str) -> CareerJob:
        player = await self._player(profile_id)
        order = self._order(order_id)
        async with self._lock:
            career = await self.repo.ensure_profile(player.profile_id)
            await self._check_can_accept(career, order)
            attempt = await self.attempts.start(order.scenario_id, player)
            job = await self._record_job(player, order, attempt)
        log.info(
            "career.job_accepted",
            job_id=job.job_id,
            order_id=order.order_id,
            attempt_id=attempt.attempt_id,
        )
        return job

    async def _check_can_accept(self, career: CareerProfile, order: WorkOrder) -> None:
        open_job = await self.repo.open_job(career.profile_id)
        if open_job is not None:
            raise career_error(
                "CAREER_JOB_ALREADY_OPEN",
                f"Liquide o serviço {open_job.job_id} antes de aceitar outra ordem.",
                job_id=open_job.job_id,
            )
        if career.reputation < order.min_reputation:
            raise career_error(
                "CAREER_REPUTATION_TOO_LOW",
                f"A ordem {order.order_id} exige reputação {order.min_reputation}; "
                f"a sua é {career.reputation}.",
                min_reputation=order.min_reputation,
                reputation=career.reputation,
            )

    async def _record_job(
        self, player: PlayerProfile, order: WorkOrder, attempt: AttemptView
    ) -> CareerJob:
        row = CareerJobRow(
            job_id=str(uuid.uuid4()),
            profile_id=player.profile_id,
            order_id=order.order_id,
            scenario_id=order.scenario_id,
            attempt_id=attempt.attempt_id,
            session_id=attempt.session_id,
            status=JobStatus.ACCEPTED.value,
            payout_brl=order.payout_brl,
            engine_cost_brl=order.engine_cost_brl,
            accepted_at=self.clock(),
        )
        try:
            return await self.repo.add_job(row)
        except BaseException:
            await self.attempts.abandon(attempt.attempt_id, player)
            raise

    # ------------------------------------------------------------------ liquidação
    async def settle(self, job_id: str) -> CareerJob:
        async with self._lock:
            job = await self.repo.get_job(job_id.lower())
            if job is None:
                raise career_error("CAREER_JOB_NOT_FOUND", f"O serviço {job_id} não existe.")
            if job.status != JobStatus.ACCEPTED:
                return job
            attempt = await self.attempts.view(job.attempt_id)
            if attempt.state.value in ACTIVE_STATES:
                raise career_error(
                    "CAREER_ATTEMPT_NOT_FINISHED",
                    f"A tentativa {attempt.attempt_id} ainda está em {attempt.state.value}.",
                    attempt_id=attempt.attempt_id,
                    state=attempt.state.value,
                )
            broken = await self._engine_broken(attempt)
            settlement = settlement_for(
                attempt.state.value, engine_broken=broken, job=job, now=self.clock()
            )
            settled = await self.repo.settle(job.job_id, settlement)
        log.info(
            "career.job_settled",
            job_id=settled.job_id,
            status=settled.status.value,
            delta_balance_brl=settled.delta_balance_brl,
            delta_reputation=settled.delta_reputation,
        )
        return settled

    async def _engine_broken(self, attempt: AttemptView) -> bool:
        """Motor quebrado na tentativa: restaurado na sessão ou falha numa puxada."""
        if attempt.engine_restores > 0:
            return True
        rows = await self.attempts.repo.runs_of(attempt.attempt_id)
        return any(int(StoredRun.from_row(r).meta.get("failures", 0)) > 0 for r in rows)
