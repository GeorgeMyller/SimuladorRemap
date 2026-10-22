"""Contratos do Modo Carreira (002 RF-25, RN-07; interfaces/career.md; data-delta).

- ``CareerProfile``: saldo em centavos de BRL (começa em R$ 5.000,00, pode ficar negativo) e
  reputação 0–100 (começa em 50). O ``profile_id`` é o do perfil local de jogador; nenhum
  outro dado pessoal.
- ``WorkOrder``: ordem de serviço fixa (``career/orders.json``) vinculada a um cenário.
- ``CareerJob``: ordem aceita por um perfil, ligada a uma tentativa do cenário; a
  liquidação preenche ``delta_balance_brl`` e ``delta_reputation``.
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import AwareDatetime, Field

from simremap.core.contracts import ContractModel, SimStrEnum
from simremap.dyno.contracts import UuidText

__all__ = [
    "INITIAL_BALANCE_BRL",
    "INITIAL_REPUTATION",
    "REPUTATION_MAX",
    "CareerJob",
    "CareerProfile",
    "JobAccept",
    "JobStatus",
    "OrderId",
    "WorkOrder",
]

INITIAL_BALANCE_BRL: Final = 500_000  # centavos (R$ 5.000,00)
INITIAL_REPUTATION: Final = 50
REPUTATION_MAX: Final = 100

OrderId = Annotated[str, Field(pattern=r"^[0-9a-z][-0-9a-z]{2,63}$")]
Cents = Annotated[int, Field(ge=1, le=100_000_000)]  # centavos de BRL
Reputation = Annotated[int, Field(ge=0, le=REPUTATION_MAX)]


class JobStatus(SimStrEnum):
    ACCEPTED = "accepted"
    PAID = "paid"
    FAILED = "failed"
    ENGINE_BROKEN = "engine_broken"
    ABANDONED = "abandoned"


class CareerProfile(ContractModel):
    profile_id: UuidText  # perfil local de jogador
    balance_brl: int  # centavos; pode ficar negativo (RN-07)
    reputation: Reputation
    created_at: AwareDatetime
    updated_at: AwareDatetime


class WorkOrder(ContractModel):
    order_id: OrderId
    title: str = Field(min_length=3, max_length=80)
    client: str = Field(min_length=2, max_length=80)
    briefing: str = Field(min_length=1, max_length=1000)
    scenario_id: OrderId
    payout_brl: Cents
    engine_cost_brl: Cents
    min_reputation: Reputation = 0


class JobAccept(ContractModel):
    order_id: OrderId


class CareerJob(ContractModel):
    job_id: UuidText
    profile_id: UuidText
    order_id: OrderId
    scenario_id: OrderId
    attempt_id: UuidText
    session_id: str | None = Field(None, max_length=36)
    status: JobStatus
    payout_brl: Cents
    engine_cost_brl: Cents
    delta_balance_brl: int | None = None  # centavos, preenchido na liquidação
    delta_reputation: int | None = None
    accepted_at: AwareDatetime
    settled_at: AwareDatetime | None = None
