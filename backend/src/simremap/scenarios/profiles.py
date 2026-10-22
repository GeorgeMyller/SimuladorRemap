"""Perfis locais de jogador (training-scenarios RF-01 a RF-03; D-16, NG-01).

- ``nickname`` ``^[-_0-9A-Za-z]{3,24}$`` (sem espaço nem ``@``), único por estação sem
  distinção de maiúsculas (índice ``uq_player_profile_nickname_lower``); nenhum outro dado
  pessoal. Limite de 100 perfis (o 101.º ⇒ 409 ``PROFILE_LIMIT_REACHED``).
- O perfil ativo vem do cabeçalho ``X-Player-Profile-Id`` (UUID4): ausente em endpoint
  obrigatório ⇒ 400 ``PLAYER_PROFILE_REQUIRED``; inexistente ⇒ 404
  ``PLAYER_PROFILE_NOT_FOUND``.
- O ``role`` controla só regras pedagógicas e a UI; não é controle de segurança (NG-01).
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from simremap.db.base import utcnow
from simremap.scenarios.contracts import PlayerProfile, PlayerProfileCreate, Role
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.repository import ScenarioRepository

__all__ = [
    "MAX_PROFILES",
    "PROFILE_HEADER",
    "ProfileService",
    "require_instructor",
]

MAX_PROFILES: Final = 100
PROFILE_HEADER: Final = "X-Player-Profile-Id"
_UUID_RE: Final = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def require_instructor(profile: PlayerProfile, action: str) -> None:
    """403 ``INSTRUCTOR_ROLE_REQUIRED`` para perfis ``student`` (RF-03)."""
    if profile.role != Role.INSTRUCTOR:
        raise scenario_error("INSTRUCTOR_ROLE_REQUIRED", f"Só o perfil de instrutor pode {action}.")


class ProfileService:
    def __init__(self, repo: ScenarioRepository) -> None:
        self.repo = repo

    async def list(self) -> list[PlayerProfile]:
        return await self.repo.list_profiles()

    async def create(self, body: PlayerProfileCreate) -> PlayerProfile:
        if await self.repo.count_profiles() >= MAX_PROFILES:
            raise scenario_error(
                "PROFILE_LIMIT_REACHED", f"A estação já tem {MAX_PROFILES} perfis."
            )
        profile = PlayerProfile(
            profile_id=str(uuid.uuid4()),
            nickname=body.nickname,
            role=body.role,
            created_at=utcnow(),
        )
        return await self.repo.add_profile(profile)

    async def resolve(self, header: str | None, *, required: bool) -> PlayerProfile | None:
        """Perfil do cabeçalho ``X-Player-Profile-Id`` (``None`` só se opcional e ausente)."""
        value = (header or "").strip().lower()
        if not value:
            if required:
                raise scenario_error(
                    "PLAYER_PROFILE_REQUIRED",
                    f"Envie o cabeçalho {PROFILE_HEADER} com o perfil ativo.",
                )
            return None
        profile = await self.repo.get_profile(value) if _UUID_RE.fullmatch(value) else None
        if profile is None:
            raise scenario_error(
                "PLAYER_PROFILE_NOT_FOUND", f"O perfil {value[:36]} não existe nesta estação."
            )
        return profile
