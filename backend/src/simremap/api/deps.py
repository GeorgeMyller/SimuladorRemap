"""Dependências FastAPI partilhadas pelos routers dos componentes.

Uso::

    from typing import Annotated, Any
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from simremap.api.deps import SessionDep, SettingsDep

    @router.get("/coisas")
    async def listar(session: SessionDep, settings: SettingsDep) -> ...: ...
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from simremap.api.middleware import body_limit
from simremap.core.config import Settings
from simremap.core.errors import SimRemapError
from simremap.db.engine import get_session

__all__ = [
    "SessionDep",
    "SettingsDep",
    "body_limit",
    "get_app_settings",
    "get_session",
    "require_content_type",
]


def get_app_settings(request: Request) -> Settings:
    """``Settings`` da app atual (``app.state.settings``)."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def require_content_type(*accepted: str) -> Any:
    """Dependência que recusa ``Content-Type`` fora de ``accepted`` com 415.

    Uso: ``@router.post("/x", dependencies=[require_content_type("application/json")])``.
    """
    allowed = tuple(a.lower() for a in accepted)

    def _check(request: Request) -> None:
        raw = request.headers.get("content-type", "")
        media = raw.split(";", 1)[0].strip().lower()
        if media not in allowed:
            raise SimRemapError(
                f"Content-Type {media or 'ausente'!r} não aceite; use {', '.join(allowed)}.",
                code="UNSUPPORTED_MEDIA_TYPE",
            )

    return Depends(_check)
