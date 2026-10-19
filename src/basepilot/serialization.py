"""单表写串行队列 —— 把"同一数据表不支持并发写"从官方约束变成运行时保证。

**依据（官方原文）：**
- 错误码 1254291「Write conflict」排查建议：「若操作量较大，
  建议在接口与接口之间增加 0.5 或 1 秒的延迟」。
- 错误码 1254607 补充：底层「基于版本维度的串行方式，不支持并发」。

所以这里做两件事：
1. **per-table_id 锁**：同一张数据表的写请求串行，不同表之间仍可并行。
   （不是全局锁 —— 客户同时写「库存表」和「广告表」不该互相等。）
2. **请求节流**：同一张表两次写之间至少间隔 `WRITE_MIN_INTERVAL` 秒，
   主动规避 1254291，而不是撞上了再重试。

指标（可由压测断言）：
- 单表最大并发写 = 1
- 1254291 发生数 = 0
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .config import WRITE_MIN_INTERVAL

T = TypeVar("T")


@dataclass
class _TableGate:
    """单张数据表的写门禁：一把锁 + 上次写完成时间。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_write_at: float = 0.0


class WriteSerializer:
    """按 table_id 分桶的写串行器。

    用法::

        serializer = WriteSerializer()
        result = await serializer.run(table_id, lambda: client.batch_create(...))

    同一 table_id 的调用被串行化；不同 table_id 并行。
    `clock` 与 `sleeper` 可注入，测试用 fake clock 避免真实 sleep。
    """

    def __init__(
        self,
        min_interval: float = WRITE_MIN_INTERVAL,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._gates: dict[str, _TableGate] = {}
        self._gates_lock = asyncio.Lock()

        # 观测指标（压测断言用）
        self.inflight: dict[str, int] = {}
        self.max_inflight: dict[str, int] = {}
        self.throttle_wait_total: float = 0.0
        self.write_count: dict[str, int] = {}

    async def _gate_for(self, table_id: str) -> _TableGate:
        async with self._gates_lock:
            if table_id not in self._gates:
                self._gates[table_id] = _TableGate()
            return self._gates[table_id]

    async def run(self, table_id: str, op: Callable[[], Awaitable[T]]) -> T:
        """在「单表串行 + 节流」约束下执行一次写操作。

        Args:
            table_id: 数据表 ID，串行的粒度。
            op: 真正发起 HTTP 写的协程工厂。

        Returns:
            op 的返回值。
        """
        gate = await self._gate_for(table_id)
        async with gate.lock:
            # 节流：距上次写完成不足 min_interval，就睡到够
            now = self._clock()
            wait = self._min_interval - (now - gate.last_write_at)
            if wait > 0:
                self.throttle_wait_total += wait
                await self._sleeper(wait)

            # 观测：记录并发峰值
            self.inflight[table_id] = self.inflight.get(table_id, 0) + 1
            self.max_inflight[table_id] = max(
                self.max_inflight.get(table_id, 0), self.inflight[table_id]
            )
            try:
                result = await op()
            finally:
                self.inflight[table_id] -= 1
                gate.last_write_at = self._clock()
                self.write_count[table_id] = self.write_count.get(table_id, 0) + 1
            return result

    def max_inflight_for(self, table_id: str) -> int:
        """该表历史最大并发写数（应为 1）。"""
        return self.max_inflight.get(table_id, 0)

    def reset_metrics(self) -> None:
        """清空观测指标（压测间重置）。"""
        self.inflight.clear()
        self.max_inflight.clear()
        self.throttle_wait_total = 0.0
        self.write_count.clear()


__all__ = ["WriteSerializer"]
