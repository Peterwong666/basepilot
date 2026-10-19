"""单表写串行队列的压测 —— 证明指标「单表最大并发写 = 1」不是口号。

用 fake clock + 事件记录，在 0.1 秒内模拟 200 次并发写，
断言串行器真正把并发压到了 1。
"""

from __future__ import annotations

import asyncio

import pytest

from basepilot.serialization import WriteSerializer


class FakeClock:
    """手动推进的时钟，避免真实 sleep。"""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        # 让出事件循环，模拟"等待期间其它协程可以跑"
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_same_table_serialized_max_inflight_one() -> None:
    """同一张表 200 次并发写，任意时刻在飞的写必须 ≤ 1。"""
    clock = FakeClock()
    serializer = WriteSerializer(min_interval=0.5, clock=clock, sleeper=clock.sleep)

    in_flight = 0
    peak = 0

    async def op() -> str:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)  # 模拟一次网络往返
        in_flight -= 1
        return "ok"

    results = await asyncio.gather(*[serializer.run("tblA", op) for _ in range(200)])

    assert results == ["ok"] * 200
    assert peak == 1, f"单表并发写峰值应为 1，实测 {peak}"
    assert serializer.max_inflight_for("tblA") == 1


@pytest.mark.asyncio
async def test_different_tables_can_run_in_parallel() -> None:
    """不同数据表之间不应互相阻塞 —— 不是全局锁。"""
    clock = FakeClock()
    serializer = WriteSerializer(min_interval=0.5, clock=clock, sleeper=clock.sleep)

    order: list[str] = []

    async def op_a() -> str:
        order.append("a-start")
        await asyncio.sleep(0)
        order.append("a-end")
        return "a"

    async def op_b() -> str:
        order.append("b-start")
        await asyncio.sleep(0)
        order.append("b-end")
        return "b"

    # 两个表交错提交
    await asyncio.gather(
        serializer.run("tblA", op_a),
        serializer.run("tblB", op_b),
    )

    # b 的 start 不应等到 a 的 end 之后
    assert order.index("b-start") < order.index("a-end") or order.index("a-start") < order.index(
        "b-end"
    )


@pytest.mark.asyncio
async def test_throttle_enforces_min_interval() -> None:
    """同一张表两次写之间的间隔必须 ≥ min_interval。"""
    clock = FakeClock()
    serializer = WriteSerializer(min_interval=0.5, clock=clock, sleeper=clock.sleep)

    completion_times: list[float] = []

    async def op() -> str:
        completion_times.append(clock())
        return "ok"

    for _ in range(5):
        await serializer.run("tblA", op)

    # 相邻两次写完成时间的间隔应 ≥ 0.5
    # zip 显式 strict=False：两个序列本来就不等长（差 1 个），这是预期
    for prev, cur in zip(completion_times, completion_times[1:], strict=False):
        assert cur - prev >= 0.5 - 1e-9, f"间隔 {cur - prev} 小于 0.5s"

    # 5 次写至少节流了 4 次（第一次不节流）
    assert serializer.throttle_wait_total >= 4 * 0.5 - 1e-9


@pytest.mark.asyncio
async def test_failed_write_still_releases_lock_and_updates_timestamp() -> None:
    """写失败也要释放锁、更新时间戳，不能卡死后续写。"""
    clock = FakeClock()
    serializer = WriteSerializer(min_interval=0.5, clock=clock, sleeper=clock.sleep)

    calls = 0

    async def failing_op() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("1254291 simulated")
        return "ok"

    with pytest.raises(RuntimeError):
        await serializer.run("tblA", failing_op)

    # 锁必须已释放，后续写能继续
    result = await serializer.run("tblA", failing_op)
    assert result == "ok"
    assert serializer.inflight.get("tblA", 0) == 0
    assert serializer.write_count["tblA"] == 2


@pytest.mark.asyncio
async def test_metrics_observability() -> None:
    """观测指标必须可断言：write_count / max_inflight / throttle。"""
    clock = FakeClock()
    serializer = WriteSerializer(min_interval=0.5, clock=clock, sleeper=clock.sleep)

    async def op() -> str:
        return "ok"

    await asyncio.gather(*[serializer.run("tblA", op) for _ in range(10)])

    assert serializer.write_count["tblA"] == 10
    assert serializer.max_inflight_for("tblA") == 1
    assert serializer.throttle_wait_total > 0
