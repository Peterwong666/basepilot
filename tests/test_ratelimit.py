"""令牌桶限流测试。

用 fake clock 前进时间，不sleep —— 快且不flaky。
"""

from __future__ import annotations

import asyncio

import pytest

from basepilot.config import BATCH_WRITE_QPS, LIST_QPS, SEARCH_QPS
from basepilot.ratelimit import Bucket, RateLimiter, RequestStats
from tests.conftest import FakeClock


def test_bucket_rates_match_official_docs() -> None:
    """三个桶的QPS 必须与飞书官方标注一致。"""
    limiter = RateLimiter()
    assert limiter.available(Bucket.WRITE) == pytest.approx(float(BATCH_WRITE_QPS))
    assert limiter.available(Bucket.SEARCH) == pytest.approx(float(SEARCH_QPS))
    assert limiter.available(Bucket.LIST) == pytest.approx(float(LIST_QPS))


def test_buckets_are_independent() -> None:
    """关键性质：写桶用光不影响 search 桶 —— 这就是分桶的意义。

    若用一个全局桶，一次大批量写就会把 field.list 的配额饿死。
    """
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    # 把 search 桶耗到只剩 1
    for _ in range(SEARCH_QPS - 1):
        limiter._buckets[Bucket.SEARCH].try_acquire()  # noqa: SLF001
    assert limiter.available(Bucket.SEARCH) == pytest.approx(1.0)

    # write 桶仍满
    assert limiter.available(Bucket.WRITE) == pytest.approx(float(BATCH_WRITE_QPS))


def test_tokens_refill_over_time() -> None:
    """时间前进后令牌回补。"""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(BATCH_WRITE_QPS):
        limiter._buckets[Bucket.WRITE].try_acquire()  # noqa: SLF001
    assert limiter.available(Bucket.WRITE) == pytest.approx(0.0)

    # 前进 1 秒 → 回补 50 个（受容量上限约束）
    clock.advance(1.0)
    assert limiter.available(Bucket.WRITE) == pytest.approx(float(BATCH_WRITE_QPS))


def test_refill_capped_at_capacity() -> None:
    """回补不超过桶容量（防止长时间空闲后突发打爆对端）。"""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    clock.advance(3600.0)
    assert limiter.available(Bucket.WRITE) == pytest.approx(float(BATCH_WRITE_QPS))


def test_time_until_calculation() -> None:
    """time_until 返回还需等待的秒数。"""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(BATCH_WRITE_QPS):
        limiter._buckets[Bucket.WRITE].try_acquire()  # noqa: SLF001

    # 50QPS → 每 0.02 秒补1 个令牌
    assert limiter._buckets[Bucket.WRITE].time_until() == pytest.approx(0.02)  # noqa: SLF001


@pytest.mark.asyncio
async def test_acquire_returns_zero_when_token_available() -> None:
    """有令牌时acquire 不等待。"""
    limiter = RateLimiter(clock=FakeClock())
    waited = await limiter.acquire(Bucket.WRITE)
    assert waited == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_concurrent_acquire_never_exceeds_rate() -> None:
    """并发获取不超发：实际发放数 == 容量 + 时间补充的量。

    这是限流器最容易写错的地方（检查与扣减非原子），所以必须有断言。
    """
    clock = FakeClock()
    limiter = RateLimiter(qps={Bucket.WRITE: 5}, clock=clock, burst=5)

    granted = 0

    async def worker() -> None:
        nonlocal granted
        await limiter.acquire(Bucket.WRITE)
        granted += 1

    # fake clock 不前进 → 只能拿到初始 5 个，后面的会一直等（不 sleep 阻塞）
    # 所以只并发 5 个，断言不多发
    await asyncio.wait_for(asyncio.gather(*[worker() for _ in range(5)]), timeout=2.0)
    assert granted == 5
    assert limiter.available(Bucket.WRITE) == pytest.approx(0.0)


def test_set_rate_allows_runtime_tuning() -> None:
    """客户现场排查时可临时调整速率（如收紧以规避写冲突）。"""
    limiter = RateLimiter(clock=FakeClock())
    limiter.set_rate(Bucket.WRITE, 10.0)
    # 速率改了，但容量不会低于速率
    assert limiter._buckets[Bucket.WRITE].rate == pytest.approx(10.0)  # noqa: SLF001


def test_snapshot_is_json_serializable() -> None:
    """doctor 工具要返回 JSON，键必须是字符串。"""
    limiter = RateLimiter(clock=FakeClock())
    snap = limiter.snapshot()
    assert set(snap) == {"write", "search", "list"}
    for key, val in snap.items():
        assert isinstance(key, str)
        assert isinstance(val, float)


def test_request_stats_error_histogram() -> None:
    """错误直方图是排障入口：一眼看出主要卡在哪个码。"""
    stats = RequestStats()
    stats.record(Bucket.WRITE, 0, 120.0, 1)
    stats.record(Bucket.WRITE, 1254291, 340.0, 1)
    stats.record(Bucket.WRITE, 1254291, 210.0, 2)
    stats.record(Bucket.SEARCH, 0, 88.0, 1)

    hist = stats.error_histogram()
    assert hist == {"1254291": 2}
    assert len(stats.tail(3)) == 3


def test_request_stats_bounded() -> None:
    """统计队列有上限，长跑不会吃内存。"""
    stats = RequestStats(maxlen=10)
    for i in range(100):
        stats.record(Bucket.WRITE, 0, float(i), 1)
    assert len(stats.tail(1000)) == 10
