"""``KeyValueCache`` (T234; RF-22; EC-03)."""

from __future__ import annotations

from typing import Any

import pytest

from simremap.core.cache import KeyValueCache, MemoryCache, RedisCache, build_cache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeRedis:
    """Cliente Redis assíncrono mínimo; ``down = True`` simula Redis parado."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.down = False
        self.closed = False
        self.px: dict[str, int] = {}

    def _guard(self) -> None:
        if self.down:
            raise ConnectionError("redis parado")

    async def ping(self) -> bool:
        self._guard()
        return True

    async def get(self, key: str) -> bytes | None:
        self._guard()
        return self.data.get(key)

    async def set(self, key: str, value: bytes, px: int | None = None) -> None:
        self._guard()
        self.data[key] = value
        if px is not None:
            self.px[key] = px

    async def delete(self, key: str) -> None:
        self._guard()
        self.data.pop(key, None)

    async def aclose(self) -> None:
        self.closed = True


async def test_memory_lru_and_ttl() -> None:
    clock = Clock()
    cache = MemoryCache(max_keys=3, clock=clock)
    assert isinstance(cache, KeyValueCache)
    for key in "abc":
        await cache.set(key, key.encode())
    assert await cache.get("a") == b"a"  # "a" passa a mais recente
    await cache.set("d", b"d")  # despeja "b" (LRU)
    assert await cache.get("b") is None
    assert len(cache) == 3
    await cache.set("t", b"t", ttl_s=10)
    clock.now = 9.9
    assert await cache.get("t") == b"t"
    clock.now = 10.0
    assert await cache.get("t") is None
    await cache.set("x", b"x", ttl_s=0)
    assert await cache.get("x") is None
    await cache.delete("d")
    assert await cache.get("d") is None
    assert await cache.check() == ("disabled", None, None)
    await cache.close()
    assert len(cache) == 0


def test_memory_rejects_zero_capacity() -> None:
    with pytest.raises(ValueError, match="max_keys"):
        MemoryCache(max_keys=0)


def test_memory_default_capacity_is_10000() -> None:
    cache = MemoryCache()
    for i in range(10_050):
        cache.set_sync(str(i), b"v")
    assert len(cache) == 10_000
    assert cache.get_sync("0") is None
    assert cache.get_sync("10049") == b"v"


async def test_redis_roundtrip_and_ttl_in_ms() -> None:
    fake = FakeRedis()
    cache = RedisCache("redis://fake", client=fake)
    await cache.set("k", b"v", ttl_s=1.5)
    assert fake.px["k"] == 1500
    assert await cache.get("k") == b"v"
    await cache.set("n", b"1")
    await cache.set("z", b"0", ttl_s=0)
    assert "z" not in fake.data
    await cache.delete("n")
    assert "n" not in fake.data
    status, latency, detail = await cache.check()
    assert status == "ok" and latency is not None and detail is None
    await cache.close()
    assert fake.closed


async def test_redis_string_values_are_encoded() -> None:
    fake = FakeRedis()
    fake.data["s"] = "texto"  # type: ignore[assignment]
    cache = RedisCache("redis://fake", client=fake)
    assert await cache.get("s") == b"texto"


async def test_redis_down_falls_back_and_recovers(
    caplog: pytest.LogCaptureFixture, log_events: Any
) -> None:
    caplog.set_level("INFO")
    clock = Clock()
    fake = FakeRedis()
    cache = RedisCache("redis://fake", client=fake, clock=clock, reconnect_interval_s=30)
    await cache.set("k", b"v")
    fake.down = True
    assert await cache.get("k") == b"v"  # vem da memória (escrita dupla)
    assert cache.using_fallback
    await cache.set("k2", b"v2")
    assert await cache.get("k2") == b"v2"
    await cache.delete("k2")
    assert await cache.get("k2") is None
    events = [e["event"] for e in log_events(caplog)]
    assert events.count("cache.fallback") == 1
    status, _, detail = await cache.check()
    assert status == "down" and detail == "ConnectionError"
    fake.down = False
    clock.now = 10.0  # antes dos 30 s: continua em memória
    assert await cache.get("k") == b"v"
    assert cache.using_fallback
    clock.now = 31.0
    assert await cache.get("k") == b"v"  # religa ao Redis
    assert getattr(cache, "using_fallback") is False  # noqa: B009 - evita estreitamento do mypy
    assert "cache.recovered" in [e["event"] for e in log_events(caplog)]


async def test_redis_recovery_attempt_fails_again() -> None:
    clock = Clock()
    fake = FakeRedis()
    cache = RedisCache("redis://fake", client=fake, clock=clock, reconnect_interval_s=1)
    fake.down = True
    await cache.get("a")
    clock.now = 2.0
    assert await cache.get("a") is None
    assert cache.using_fallback
    fake.down = False
    assert (await cache.check())[0] == "ok"
    assert not cache.using_fallback


async def test_close_tolerates_client_errors() -> None:
    class Broken(FakeRedis):
        async def aclose(self) -> None:
            raise OSError("já fechado")

    await RedisCache("redis://fake", client=Broken()).close()


async def test_unreachable_real_redis_falls_back_quickly(settings_factory: Any) -> None:
    import time

    cache = build_cache(settings_factory(redis_url="redis://127.0.0.1:1/0"))
    assert isinstance(cache, RedisCache)
    t0 = time.perf_counter()
    await cache.set("k", b"v")
    assert await cache.get("k") == b"v"
    assert time.perf_counter() - t0 < 1.0
    assert cache.using_fallback
    await cache.close()


def test_build_cache_without_redis(settings_factory: Any) -> None:
    cache = build_cache(settings_factory(cache_max_keys=500))
    assert isinstance(cache, MemoryCache)
    assert cache.max_keys == 500
