"""token 缓存的核心指标测试。

核心断言：**100 次业务请求 → 向飞书换 token 仅 1 次**。
这正是 README 证据卡上的那一行，必须可复现。
"""

from __future__ import annotations

import httpx
import pytest

from basepilot.auth import AuthError, TokenCache
from basepilot.config import TOKEN_REFRESH_THRESHOLD, TOKEN_TTL_SECONDS
from tests.conftest import FakeClock

APP_ID = "cli_test"
APP_SECRET = "secret_test"


def _mock_token_transport(expire: int = TOKEN_TTL_SECONDS) -> tuple[httpx.MockTransport, list[int]]:
    """返回 mock transport 与调用计数容器。"""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "tenant_access_token": f"t-token-{len(calls)}",
                "expire": expire,
            },
        )

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_100_requests_fetch_token_once(fake_clock: FakeClock) -> None:
    """100 次业务请求只换1 次 token —— 核心指标。"""
    transport, calls = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        tokens = [await cache.get() for _ in range(100)]

        assert cache.fetch_count == 1, f"应只换 1 次，实际 {cache.fetch_count} 次"
        assert len(calls) == 1
        # 100 次拿到的都是同一个 token
        assert len(set(tokens)) == 1
        assert tokens[0] == "t-token-1"


@pytest.mark.asyncio
async def test_concurrent_get_is_single_flight(fake_clock: FakeClock) -> None:
    """50 个协程同时首次调用，只触发一次真实请求（asyncio.Lock 单飞）。"""
    import asyncio

    transport, calls = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        tokens = await asyncio.gather(*[cache.get() for _ in range(50)])

        assert cache.fetch_count == 1
        assert len(calls) == 1
        assert len(set(tokens)) == 1


@pytest.mark.asyncio
async def test_refresh_before_threshold_but_after_official_boundary(fake_clock: FakeClock) -> None:
    """刷新窗口必须落在官方规定的 [0, 30min] 区间内。

    官方规则：剩余 <30min 返回新token；>=30min 返回原token。
    所以在剩余 29 分 59 秒时刷新才有意义。
    """
    transport, _ = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        first = await cache.get()
        assert cache.fetch_count == 1

        # 时间前进 7200 - 1799 = 5401 秒 → 剩余 1799s < 1800s，应触发刷新
        fake_clock.advance(TOKEN_TTL_SECONDS - TOKEN_REFRESH_THRESHOLD + 1)
        second = await cache.get()

        assert cache.fetch_count == 2
        assert second != first


@pytest.mark.asyncio
async def test_no_refresh_when_still_above_threshold(fake_clock: FakeClock) -> None:
    """剩余仍 ≥30 分钟时不应刷新（官方会原样返回旧 token，刷新是浪费）。"""
    transport, _ = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        await cache.get()
        # 只前进 100 秒，剩余 7100s，远大于阈值
        fake_clock.advance(100)
        await cache.get()

        assert cache.fetch_count == 1


@pytest.mark.asyncio
async def test_remaining_ttl_reported(fake_clock: FakeClock) -> None:
    """remaining_ttl 用于 bitable_doctor 展示。"""
    transport, _ = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        await cache.get()
        assert await cache.remaining_ttl() == TOKEN_TTL_SECONDS

        fake_clock.advance(600)
        assert await cache.remaining_ttl() == TOKEN_TTL_SECONDS - 600


@pytest.mark.asyncio
async def test_invalidate_forces_refetch(fake_clock: FakeClock) -> None:
    """收到 401 时可手动失效并强制重取。"""
    transport, _ = _mock_token_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)

        await cache.get()
        await cache.invalidate()
        await cache.get()

        assert cache.fetch_count == 2


@pytest.mark.asyncio
async def test_business_error_raises_auth_error(fake_clock: FakeClock) -> None:
    """飞书返回 code != 0 时应抛 AuthError，而不是静默失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10003, "msg": "app not exist"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)
        with pytest.raises(AuthError, match="app not exist"):
            await cache.get()


@pytest.mark.asyncio
async def test_missing_token_field_raises(fake_clock: FakeClock) -> None:
    """响应里没有 token 字段必须报错，不能返回 None 让下游崩。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "msg": "ok", "expire": 7200})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = TokenCache(APP_ID, APP_SECRET, http_client=client, clock=fake_clock)
        with pytest.raises(AuthError, match="tenant_access_token"):
            await cache.get()