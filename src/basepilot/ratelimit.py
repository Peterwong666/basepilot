"""按接口族分桶的令牌桶限流。

为什么分桶而不是全局桶
----------------------
飞书官方是**按接口分别标注频率限制**的（写类 50 次/秒、search 20 次/秒、
元信息列举 20 次/秒）。如果用一个全局令牌桶，那么一次大批量写就会把配额全部占满，
导致后续的 schema 查询（field.list）被无辜饿死 —— 而它本来有独立的 20 QPS 配额。

所以这里维护三个**互不抢占**的桶：`write` / `search` / `list`。

时钟可注入
----------
测试用 fake clock 驱动时间前进，不靠 `sleep` —— 这样并发/限流测试既快又不flaky。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Bucket(str, Enum):  # noqa: UP042 - 需 str 行为才能直接 JSON 序列化
    """令牌桶种类，与飞书的接口频率分组对应。"""

    WRITE = "write"
    SEARCH = "search"
    LIST = "list"


#: 各桶的官方 QPS 上限（来源见 config.py 同名常量）
DEFAULT_QPS: dict[Bucket, int] = {
    Bucket.WRITE: 50,
    Bucket.SEARCH: 20,
    Bucket.LIST: 20,
}


@dataclass
class _TokenBucket:
    """固定速率令牌桶（等价于滑动窗口限流，但不存全部历史）。"""

    rate: float
    capacity: float
    clock: Callable[[], float]
    _tokens: float = field(init=False)
    _last: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last = now

    def try_acquire(self, amount: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    def time_until(self, amount: float = 1.0) -> float:
        """还需要等多久才能拿到 amount 个令牌（秒）。"""
        self._refill()
        if self._tokens >= amount:
            return 0.0
        return (amount - self._tokens) / self.rate

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


class RateLimiter:
    """多桶限流器。

    典型用法::

        limiter = RateLimiter(clock=fake_clock)
        await limiter.acquire(Bucket.WRITE)   # 写前
        await limiter.acquire(Bucket.SEARCH)  # 查询前
    """

    def __init__(
        self,
        qps: dict[Bucket, int] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        burst: int | None = None,
    ) -> None:
        self._clock = clock
        qps_map = qps or DEFAULT_QPS
        self._buckets: dict[Bucket, _TokenBucket] = {}
        for bucket, rate in qps_map.items():
            cap = float(burst if burst is not None else rate)
            self._buckets[bucket] = _TokenBucket(
                rate=float(rate), capacity=cap, clock=clock
            )

    async def acquire(self, bucket: Bucket, amount: float = 1.0) -> float:
        """获取令牌，返回实际等待秒数（0 表示无需等待）。

        用锁保证「检查 + 扣减」原子化，避免并发下超发。
        """
        lock = self._lock_for(bucket)
        waited = 0.0
        async with lock:
            tk = self._buckets[bucket]
            while not tk.try_acquire(amount):
                delay = tk.time_until(amount)
                waited += delay
                await asyncio.sleep(delay)
        return waited

    def _lock_for(self, bucket: Bucket) -> asyncio.Lock:
        # 延迟创建，避免在 __init__ 里绑定事件循环
        if not hasattr(self, "_locks"):
            self._locks: dict[Bucket, asyncio.Lock] = {}
        if bucket not in self._locks:
            self._locks[bucket] = asyncio.Lock()
        return self._locks[bucket]

    def available(self, bucket: Bucket) -> float:
        """当前可用令牌数，供 `bitable_doctor` 展示。"""
        return self._buckets[bucket].available

    def snapshot(self) -> dict[str, float]:
        """三个桶的余量快照，键名为字符串便于 JSON 序列化。"""
        return {b.value: self.available(b) for b in self._buckets}

    def set_rate(self, bucket: Bucket, rate: float) -> None:
        """运行时调整速率（客户现场排查时可临时放宽或收紧）。"""
        tk = self._buckets[bucket]
        tk.rate = float(rate)
        tk.capacity = max(tk.capacity, float(rate))


class RequestStats:
    """按 (bucket, code) 维度累计请求统计，供 doctor 展示与排障。"""

    def __init__(self, maxlen: int = 200) -> None:
        self._recent: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, bucket: Bucket, code: int, latency_ms: float, attempt: int) -> None:
        self._recent.append(
            {
                "bucket": bucket.value,
                "code": code,
                "latency_ms": round(latency_ms, 2),
                "attempt": attempt,
            }
        )

    def error_histogram(self) -> dict[str, int]:
        """错误码直方图 —— 客户现场一眼看出「主要卡在哪个码」。"""
        hist: dict[str, int] = {}
        for item in self._recent:
            code = int(item["code"])
            if code != 0:
                hist[str(code)] = hist.get(str(code), 0) + 1
        return hist

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        """最近 n 条请求记录。"""
        return list(self._recent)[-n:]