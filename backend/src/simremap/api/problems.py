"""Conversão de toda falha HTTP em ``application/problem+json`` (platform-foundation RF-05).

- ``SimRemapError`` → status e ``code`` do catálogo, mais campos extra e cabeçalhos.
- ``RequestValidationError`` → 422 ``VALIDATION_FAILED`` com ``errors``.
- ``HTTPException`` do Starlette → ``code`` por status (404 ``ROUTE_NOT_FOUND``,
  405 ``METHOD_NOT_ALLOWED``, 413, 415, ...).
- Exceção não tratada → 500 ``INTERNAL_ERROR`` sem stack trace na resposta
  (tratada em ``RequestIdMiddleware``, que regista a exceção no log).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import orjson
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from simremap.core.errors import (
    PROBLEM_JSON,
    FieldError,
    ProblemDetail,
    SimRemapError,
    get_error,
    is_registered,
    problem_type,
)
from simremap.core.request_context import REQUEST_ID_HEADER, current_request_id

__all__ = [
    "build_problem",
    "install_problem_handlers",
    "internal_error_body",
    "problem_body",
    "problem_response",
]

_STATUS_CODES: Final[dict[int, str]] = {
    404: "ROUTE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
    507: "STORAGE_FULL",
}

_DEFAULT_DETAIL: Final[dict[str, str]] = {
    "ROUTE_NOT_FOUND": "A rota pedida não existe.",
    "METHOD_NOT_ALLOWED": "O método HTTP não é suportado nesta rota.",
    "PAYLOAD_TOO_LARGE": "O corpo do pedido excede o limite permitido.",
    "UNSUPPORTED_MEDIA_TYPE": "O tipo de conteúdo do pedido não é aceite por esta rota.",
    "VALIDATION_FAILED": "O pedido não passou na validação.",
    "INTERNAL_ERROR": "Ocorreu um erro interno. Consulte o request_id no log do servidor.",
}


def _instance(request: Request) -> str:
    return request.url.path


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else current_request_id()


def problem_response(problem: ProblemDetail, headers: Mapping[str, str] | None = None) -> Response:
    """Resposta ``application/problem+json`` com ``X-Request-ID``."""
    body = orjson.dumps(problem.model_dump(mode="json", exclude_none=True))
    merged = {REQUEST_ID_HEADER: problem.request_id, **dict(headers or {})}
    return Response(body, status_code=problem.status, media_type=PROBLEM_JSON, headers=merged)


def build_problem(
    code: str,
    request_id: str,
    *,
    detail: str | None = None,
    status: int | None = None,
    instance: str | None = None,
    errors: list[FieldError] | None = None,
    **extra: Any,
) -> ProblemDetail:
    spec = get_error(code)
    return ProblemDetail(
        type=problem_type(code),
        title=spec.title,
        status=status if status is not None else spec.status,
        detail=(detail or _DEFAULT_DETAIL.get(code) or spec.title)[:2000],
        code=code,
        request_id=request_id,
        instance=instance,
        errors=errors,
        **extra,
    )


async def _handle_simremap_error(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, SimRemapError):  # pragma: no cover - garantido pelo registo
        raise TypeError(type(exc).__name__)
    problem = exc.to_problem(_request_id(request), _instance(request))
    return problem_response(problem, exc.headers)


async def _handle_validation_error(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - garantido pelo registo
        raise TypeError(type(exc).__name__)
    errors = [
        FieldError(
            loc=[part if isinstance(part, int) else str(part) for part in err.get("loc", ())],
            msg=str(err.get("msg", "")),
            type=str(err.get("type", "")),
        )
        for err in exc.errors()
    ]
    problem = build_problem(
        "VALIDATION_FAILED", _request_id(request), instance=_instance(request), errors=errors
    )
    return problem_response(problem)


async def _handle_http_exception(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - garantido pelo registo
        raise TypeError(type(exc).__name__)
    code = _STATUS_CODES.get(exc.status_code)
    if code is None or not is_registered(code):
        code = "INTERNAL_ERROR" if exc.status_code >= 500 else "RESOURCE_NOT_FOUND"  # noqa: PLR2004
    detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None  # noqa: PLR2004
    if detail in {"Not Found", "Method Not Allowed"}:
        detail = None
    status = exc.status_code if 400 <= exc.status_code <= 599 else 500  # noqa: PLR2004
    problem = build_problem(
        code, _request_id(request), detail=detail, status=status, instance=_instance(request)
    )
    return problem_response(problem, exc.headers)


def problem_body(problem: ProblemDetail) -> tuple[bytes, dict[str, str]]:
    """Corpo JSON e cabeçalhos ASGI de um ``ProblemDetail`` (para middlewares)."""
    body = orjson.dumps(problem.model_dump(mode="json", exclude_none=True))
    return body, {"content-type": PROBLEM_JSON, REQUEST_ID_HEADER.lower(): problem.request_id}


def internal_error_body(request_id: str, path: str | None) -> tuple[bytes, dict[str, str]]:
    """Corpo e cabeçalhos de um 500 ``INTERNAL_ERROR`` (sem stack trace)."""
    return problem_body(build_problem("INTERNAL_ERROR", request_id, instance=path))


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SimRemapError, _handle_simremap_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
