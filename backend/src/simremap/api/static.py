"""Build estático do frontend com fallback SPA (platform-foundation RF-15, EC-11; D-02; T237).

O handler substitui o ``default`` do router (chamado só quando nenhuma rota casa), o
que preserva o 405 das rotas da API e o 404 ``ROUTE_NOT_FOUND`` em ``/api/*``/``/ws/*``.

- ``GET``/``HEAD`` fora de ``/api/`` e ``/ws/``: ficheiro de ``SIMREMAP_STATIC_DIR`` se
  existir (``/assets/*`` com ``Cache-Control: public, max-age=31536000, immutable``),
  senão ``index.html`` (``Cache-Control: no-cache``) para as rotas do SPA.
- Sem build (diretório ausente ou sem ``index.html``): 404 ``STATIC_NOT_BUILT`` com
  instrução ``npm run build``; a API funciona normalmente (log ``startup.static_missing``).
- Caminhos fora do diretório estático (``..``, links) são recusados (404).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketClose

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger

__all__ = ["IMMUTABLE_CACHE", "SpaStaticFallback", "install_static", "static_available"]

log = get_logger("simremap.api.static")

IMMUTABLE_CACHE: Final = "public, max-age=31536000, immutable"
_NO_CACHE: Final = "no-cache"
_API_PREFIXES: Final = ("/api/", "/ws/")
_API_ROOTS: Final = frozenset({"/api", "/ws"})


def static_available(static_dir: Path | None) -> bool:
    return static_dir is not None and (static_dir / "index.html").is_file()


def _is_api_path(path: str) -> bool:
    return path in _API_ROOTS or path.startswith(_API_PREFIXES)


class SpaStaticFallback:
    """ASGI ``default`` do router: estático + fallback SPA, ou 404 em problem+json."""

    def __init__(self, static_dir: Path | None) -> None:
        self.root = static_dir.resolve() if static_available(static_dir) and static_dir else None

    def _resolve(self, path: str) -> Path | None:
        if self.root is None:
            return None
        relative = path.lstrip("/")
        if not relative:
            return None
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            return None
        return candidate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose()(scope, receive, send)
            return
        path = str(scope.get("path", "/"))
        method = str(scope.get("method", "GET")).upper()
        if _is_api_path(path) or method not in ("GET", "HEAD"):
            raise StarletteHTTPException(status_code=404)
        if self.root is None:
            raise SimRemapError(
                "O build do frontend não existe em SIMREMAP_STATIC_DIR; execute "
                "`npm run build` em frontend/ ou reconstrua a imagem Docker.",
                code="STATIC_NOT_BUILT",
            )
        file = self._resolve(path)
        if file is not None:
            relative = file.relative_to(self.root).as_posix()
            cache = IMMUTABLE_CACHE if relative.startswith("assets/") else _NO_CACHE
            response = FileResponse(file, headers={"Cache-Control": cache})
        else:
            response = FileResponse(self.root / "index.html", headers={"Cache-Control": _NO_CACHE})
        await response(scope, receive, send)


def install_static(app: FastAPI, static_dir: Path | None) -> bool:
    """Liga o fallback ao router da app; devolve ``True`` se o build existe."""
    fallback = SpaStaticFallback(static_dir)
    app.router.default = fallback
    available = fallback.root is not None
    if not available:
        log.warning(
            "startup.static_missing",
            static_dir=str(static_dir) if static_dir else None,
            hint="npm run build",
        )
    return available
