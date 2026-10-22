"""Middlewares ASGI da API (platform-foundation RF-13, RF-14, RF-16, RF-23, RF-24; D-32; T236).

Ordem (de fora para dentro), instalada por ``install_middlewares``:

1. ``SecurityHeadersMiddleware``: ``Content-Security-Policy`` restrita a ``'self'``
   (``connect-src 'self' ws://localhost:* ws://127.0.0.1:*``), ``X-Content-Type-Options:
   nosniff``, ``Referrer-Policy: no-referrer`` e ``X-Frame-Options: DENY`` em toda
   resposta (inclusive 404, 413 e 500). As páginas ``/docs`` e ``/redoc`` (só ``dev`` e
   ``test``) recebem uma CSP própria para os assets do Swagger UI.
2. ``RequestIdMiddleware``: ``request_id`` (``X-Request-ID`` válido ou UUID4) em
   ``scope["state"]`` e na contextvar; cabeçalho ``X-Request-ID`` em toda resposta;
   evento ``http.request`` (``method``, ``path`` sem query, ``status``, ``duration_ms``;
   sem IP, cabeçalhos ou corpo); exceção não tratada ⇒ 500 ``INTERNAL_ERROR`` sem
   stack trace (a stack vai para o log).
3. ``CORSMiddleware`` do Starlette: só as origens ``localhost``/``127.0.0.1`` de
   ``SIMREMAP_CORS_ORIGINS`` (validadas em ``Settings``), sem credenciais.
4. ``BodyLimitMiddleware``: corpo limitado a ``SIMREMAP_MAX_BODY_BYTES`` (16 MiB) com
   override por rota pela dependência ``body_limit(bytes)``; excesso ⇒ 413
   ``PAYLOAD_TOO_LARGE`` sem chamar o handler. O middleware resolve a rota (caminho e
   método) antes do roteamento e usa o limite dela; sem rota completa (404/405) vale o
   global. ``Content-Length`` também é verificado pela dependência global
   ``enforce_declared_body_limit`` (que ignora WebSocket); corpo sem ``Content-Length``
   é contado durante a leitura.

Uso do override::

    from simremap.api.middleware import body_limit

    @router.post("/logs/import", dependencies=[body_limit(64 * 1024 * 1024)])
    async def import_log(...): ...
"""

from __future__ import annotations

import time
from typing import Any, Final

from fastapi import Depends, FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from simremap.api.problems import build_problem, internal_error_body, problem_body
from simremap.core.config import Settings
from simremap.core.logging import get_logger
from simremap.core.request_context import REQUEST_ID_HEADER, request_id_var, resolve_request_id

__all__ = [
    "BODY_LIMIT_ATTR",
    "CSP_POLICY",
    "SECURITY_HEADERS",
    "BodyLimitMiddleware",
    "PayloadTooLarge",
    "RequestIdMiddleware",
    "SecurityHeadersMiddleware",
    "body_limit",
    "enforce_declared_body_limit",
    "install_middlewares",
]

logger = get_logger("simremap.api")

CSP_POLICY: Final = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self' ws://localhost:* ws://127.0.0.1:*; "
    "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'"
)
_DOCS_CSP: Final = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
    "frame-ancestors 'none'"
)
_DOCS_PATHS: Final = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})
SECURITY_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": CSP_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
BODY_LIMIT_ATTR: Final = "__simremap_body_limit__"


# --------------------------------------------------------------------------- cabeçalhos


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, docs_enabled: bool = False) -> None:
        self.app = app
        self.docs_enabled = docs_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = self.docs_enabled and scope.get("path") in _DOCS_PATHS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if docs:
                    headers["Content-Security-Policy"] = _DOCS_CSP
            await send(message)

        await self.app(scope, receive, send_with_headers)


# --------------------------------------------------------------------------- request_id


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = False
        status = 500
        t0 = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = int(message["status"])
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers.append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("http.unhandled_exception", path=scope.get("path"))
            if scope["type"] != "http" or started:
                raise
            body, headers = internal_error_body(request_id, scope.get("path"))
            status = 500
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            if scope["type"] == "http":
                logger.info(
                    "http.request",
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                )
            request_id_var.reset(token)


# --------------------------------------------------------------------------- limite de corpo


class PayloadTooLarge(StarletteHTTPException):
    """Corpo acima do limite da rota (convertido em 413 ``PAYLOAD_TOO_LARGE``)."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            status_code=413,
            detail=f"O corpo do pedido excede o limite de {limit} bytes desta rota.",
        )
        self.limit = limit


def body_limit(max_bytes: int) -> Any:
    """Dependência que fixa o limite de corpo da rota (override de ``max_body_bytes``)."""
    if max_bytes < 1:
        raise ValueError("body_limit exige um limite positivo")

    def _marker() -> None:
        return None

    setattr(_marker, BODY_LIMIT_ATTR, max_bytes)
    _marker.__name__ = f"body_limit_{max_bytes}"
    return Depends(_marker)


def enforce_declared_body_limit(connection: HTTPConnection) -> None:
    """Dependência global da app: recusa pelo ``Content-Length`` antes de qualquer handler.

    Cobre também os handlers que leem o corpo cru (``await request.body()``), que de
    outra forma só falhariam durante a leitura. Recebe ``HTTPConnection`` para valer
    também nas rotas ``@router.websocket`` (sem corpo: nada a verificar).
    """
    if connection.scope.get("type") != "http":
        return
    declared = _content_length(connection.scope)
    if declared is None:
        return
    settings: Settings = connection.app.state.settings
    limit = _route_limit(connection.scope) or settings.max_body_bytes
    if declared > limit:
        raise PayloadTooLarge(limit)


def _dependant_limit(route: Any) -> int | None:
    dependant = getattr(route, "dependant", None)
    for dep in getattr(dependant, "dependencies", ()):
        limit = getattr(getattr(dep, "call", None), BODY_LIMIT_ATTR, None)
        if isinstance(limit, int):
            return limit
    return None


def _route_limit(scope: Scope) -> int | None:
    return _dependant_limit(scope.get("route"))


def _candidates(routes: Any) -> Any:
    """Rotas planas, incluindo as dos routers incluídos de forma preguiçosa pelo FastAPI.

    ``app.include_router`` guarda um ``_IncludedRouter`` cujos contextos efetivos
    (``effective_route_contexts``) têm ``matches`` e ``dependant`` como uma ``APIRoute``.
    """
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            yield from contexts()
        else:
            yield route


def _match_route(routes: Any, scope: Scope) -> Any:
    """Rota que casa por completo com ``scope`` (caminho e método), ou ``None``.

    Desce nos ``Mount`` com o escopo filho; rota com caminho certo e método errado
    (``Match.PARTIAL``, 405) não conta: vale o limite global.
    """
    for route in _candidates(routes):
        match, child = route.matches(scope)
        if match != Match.FULL:
            continue
        if isinstance(route, Mount):
            inner = _match_route(route.routes, {**scope, **child})
            if inner is not None:
                return inner
            continue
        return route
    return None


def resolve_route_limit(scope: Scope, default: int) -> int:
    """Limite de corpo da rota de ``scope`` antes do roteamento (``body_limit`` ou global)."""
    app = scope.get("app")
    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if routes is None:
        return _route_limit(scope) or default
    route = _match_route(routes, scope)
    return _dependant_limit(route) or default


def _content_length(scope: Scope) -> int | None:
    raw = Headers(scope=scope).get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class BodyLimitMiddleware:
    """413 por ``Content-Length`` antes do handler, ou ao exceder durante a leitura."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def _reject(self, scope: Scope, send: Send, limit: int) -> None:
        request_id = scope.get("state", {}).get("request_id") or request_id_var.get() or ""
        problem = build_problem(
            "PAYLOAD_TOO_LARGE",
            resolve_request_id(request_id),
            detail=f"O corpo do pedido excede o limite de {limit} bytes desta rota.",
            instance=scope.get("path"),
        )
        body, headers = problem_body(problem)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        # Limite da rota resolvido antes do teto global: rota sem POST (405) ou inexistente
        # fica com ``max_body_bytes``; só ``body_limit(n)`` sobe o limite (ex.: 64 MiB).
        limit = resolve_route_limit(scope, self.max_body_bytes)
        if declared is not None and declared > limit:
            await self._reject(scope, send, limit)
            return

        total = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal total, limit
            route_limit = _route_limit(scope)
            if route_limit is not None:
                limit = route_limit
                if declared is not None and declared > limit:
                    raise PayloadTooLarge(limit)
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise PayloadTooLarge(limit)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except PayloadTooLarge as exc:
            if started:
                raise
            await self._reject(scope, send, exc.limit)


# --------------------------------------------------------------------------- instalação


def install_middlewares(app: FastAPI, settings: Settings) -> None:
    """Instala os 4 middlewares na ordem documentada (o último adicionado fica por fora)."""
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, docs_enabled=settings.env in ("dev", "test"))
