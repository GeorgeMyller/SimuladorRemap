"""``KeyValueCache``: memória (LRU + TTL) ou Redis opcional (platform-foundation RF-22; T234).

- Sem ``SIMREMAP_REDIS_URL``: ``MemoryCache`` (LRU de ``cache_max_keys`` = 10 000 chaves,
  TTL por chave); ``/api/v1/health`` mostra ``checks.redis.status = "disabled"``.
- Com ``SIMREMAP_REDIS_URL``: ``RedisCache`` com fallback automático para memória.
  Qualquer erro ou timeout (0,5 s) do Redis passa o cache para memória (≤ 1 s),
  regista ``cache.fallback`` e tenta religar a cada 30 s (``cache.recovered``).

Valores são ``bytes``; TTL em segundos (``None`` = sem expiração).

Uso::

    cache: KeyValueCache = request.app.state.cache
    await cache.set("curve:hatch", payload, ttl_s=300)
    data = await cache.get("curve:hatch")
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, runtime_checkable

from simremap.core.logging import get_logger

if TYPE_CHECKING:
    from simremap.core.config import Settings

__all__ = [
    "CacheCheck",
    "KeyValueCache",
    "MemoryCache",
    "RedisCache",
    "build_cache",
]

log = get_logger("simremap.cache")

REDIS_TIMEOUT_S: Final = 0.5
RECONNECT_INTERVAL_S: Final = 30.0

CacheCheck = tuple[Literal["ok", "down", "disabled"], float | None, str | None]
"""(estado, latência em ms, detalhe) para ``checks.redis`` do health."""


@runtime_checkable
class KeyValueCache(Protocol):
    """Interface comum dos caches."""

    backend: str

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_s: float | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def check(self) -> CacheCheck: ...
    async def close(self) -> None: ...


class MemoryCache:
    """LRU em memória com TTL (relógio monotónico)."""

    backend: str = "memory"

    def __init__(self, max_keys: int = 10_000, clock: Callable[[], float] = time.monotonic) -> None:
        if max_keys < 1:
            raise ValueError("max_keys deve ser ≥ 1")
        self.max_keys = max_keys
        self._clock = clock
        self._data: OrderedDict[str, tuple[bytes, float | None]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def get_sync(self, key: str) -> bytes | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and self._clock() >= expires:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set_sync(self, key: str, value: bytes, ttl_s: float | None = None) -> None:
        if ttl_s is not None and ttl_s <= 0:
            self._data.pop(key, None)
            return
        expires = None if ttl_s is None else self._clock() + ttl_s
        self._data[key] = (value, expires)
        self._data.move_to_end(key)
        while len(self._data) > self.max_keys:
            self._data.popitem(last=False)

    def delete_sync(self, key: str) -> None:
        self._data.pop(key, None)

    async def get(self, key: str) -> bytes | None:
        return self.get_sync(key)

    async def set(self, key: str, value: bytes, ttl_s: float | None = None) -> None:
        self.set_sync(key, value, ttl_s)

    async def delete(self, key: str) -> None:
        self.delete_sync(key)

    async def check(self) -> CacheCheck:
        return ("disabled", None, None)

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    """Redis com fallback transparente para ``MemoryCache``."""

    backend: str = "redis"

    def __init__(
        self,
        url: str,
        *,
        max_keys: int = 10_000,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        reconnect_interval_s: float = RECONNECT_INTERVAL_S,
    ) -> None:
        self.url = url
        self.memory = MemoryCache(max_keys, clock)
        self._clock = clock
        self._reconnect_interval = reconnect_interval_s
        if client is None:
            from redis.asyncio import Redis

            client = Redis.from_url(
                url, socket_timeout=REDIS_TIMEOUT_S, socket_connect_timeout=REDIS_TIMEOUT_S
            )
        self._client = client
        self._fallback_since: float | None = None

    @property
    def using_fallback(self) -> bool:
        return self._fallback_since is not None

    def _fall_back(self, exc: BaseException) -> None:
        if self._fallback_since is None:
            log.warning("cache.fallback", backend="memory", reason=type(exc).__name__)
        self._fallback_since = self._clock()

    async def _try_recover(self) -> bool:
        """Com fallback ativo, tenta o Redis de novo após ``reconnect_interval_s``."""
        if self._fallback_since is None:
            return True
        if self._clock() - self._fallback_since < self._reconnect_interval:
            return False
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_S):
                await self._client.ping()
        except Exception as exc:
            self._fall_back(exc)
            return False
        self._fallback_since = None
        log.info("cache.recovered", backend="redis")
        return True

    async def get(self, key: str) -> bytes | None:
        if await self._try_recover():
            try:
                async with asyncio.timeout(REDIS_TIMEOUT_S):
                    value = await self._client.get(key)
            except Exception as exc:
                self._fall_back(exc)
            else:
                if value is None or isinstance(value, bytes):
                    return value
                return str(value).encode("utf-8")
        return self.memory.get_sync(key)

    async def set(self, key: str, value: bytes, ttl_s: float | None = None) -> None:
        self.memory.set_sync(key, value, ttl_s)
        if not await self._try_recover():
            return
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_S):
                if ttl_s is None:
                    await self._client.set(key, value)
                elif ttl_s > 0:
                    await self._client.set(key, value, px=max(1, int(ttl_s * 1000)))
                else:
                    await self._client.delete(key)
        except Exception as exc:
            self._fall_back(exc)

    async def delete(self, key: str) -> None:
        self.memory.delete_sync(key)
        if not await self._try_recover():
            return
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_S):
                await self._client.delete(key)
        except Exception as exc:
            self._fall_back(exc)

    async def check(self) -> CacheCheck:
        start = time.perf_counter()
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_S):
                await self._client.ping()
        except Exception as exc:
            self._fall_back(exc)
            latency = round((time.perf_counter() - start) * 1000.0, 3)
            return ("down", latency, type(exc).__name__[:200])
        latency = round((time.perf_counter() - start) * 1000.0, 3)
        if self._fallback_since is not None:
            self._fallback_since = None
            log.info("cache.recovered", backend="redis")
        return ("ok", latency, None)

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:  # fecho best effort no shutdown
                log.warning("cache.close_failed", reason=type(exc).__name__)
        await self.memory.close()


def build_cache(settings: Settings) -> KeyValueCache:
    """``RedisCache`` com ``SIMREMAP_REDIS_URL``; senão ``MemoryCache``."""
    if settings.redis_url:
        return RedisCache(settings.redis_url, max_keys=settings.cache_max_keys)
    return MemoryCache(settings.cache_max_keys)
