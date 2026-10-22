"""Contexto por pedido partilhado entre middleware, handlers de erro e logging."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Final

__all__ = ["REQUEST_ID_HEADER", "current_request_id", "request_id_var", "resolve_request_id"]

REQUEST_ID_HEADER: Final = "X-Request-ID"
_VALID_REQUEST_ID: Final = re.compile(r"^[0-9A-Za-z-]{1,64}$")

request_id_var: ContextVar[str | None] = ContextVar("simremap_request_id", default=None)


def resolve_request_id(received: str | None) -> str:
    """Aceita o valor recebido se tiver ≤ 64 caracteres ``[0-9A-Za-z-]``; senão gera UUID4."""
    if received is not None and _VALID_REQUEST_ID.fullmatch(received):
        return received
    return str(uuid.uuid4())


def current_request_id() -> str:
    """``request_id`` do pedido atual ou um UUID4 novo fora de um pedido."""
    value = request_id_var.get()
    return value if value is not None else str(uuid.uuid4())
