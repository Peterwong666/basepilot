"""adoption.py 三指标计算逻辑测试（全 MockTransport 离线）。

锁三个行为：
1. 覆盖率 = 去重 SKU 数 / baseline，分母 0 时如实 N/A 不编造
2. SLA 逾期率 = 超期未闭环 / 总未闭环（读回富文本键也能正确归一化）
3. 采用率恒 pending_config（三表无 User 字段，如实报不猜数字）
"""

from __future__ import annotations

import argparse
import time

import httpx
import pytest

from basepilot.cassette import ReplayTransport  # noqa: F401  (确认 cassette 可复用)
from scripts.adoption import compute


def _ok_token(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/tenant_access_token/internal"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "tenant_access_token": "t-test",
                "expire": 7200,
            },
        )
    return None


def _rec(rid: str, sku: str) -> dict[str, object]:
    """构造一条读回的记录（文本字段为富文本数组形态，同真实 API）。"""
    return {"record_id": rid, "fields": {"SKU": [{"type": "text", "text": sku}]}}


def _make_args(**kw: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "app": "appTok",
        "table": "tbl1",
        "key_field": "SKU",
        "baseline": 0,
        "status_field": None,
        "closed_value": "已闭环",
        "date_field": None,
        "sla_days": 7,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


@pytest.mark.asyncio
async def test_coverage_dedupes_and_divides_by_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """覆盖率：3 条记录去重后 2 个 SKU，baseline=4 → 50%，不健康。"""
    monkeypatch.setenv("BASEPILOT_APP_ID", "cli_x")
    monkeypatch.setenv("BASEPILOT_APP_SECRET", "secret_x")

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/records/search"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "has_more": False,
                        "items": [
                            _rec("r1", "A"),
                            _rec("r2", "B"),
                            _rec("r3", "A"),  # 与 r1 重复，应被去重
                        ],
                    },
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    import basepilot.client as client_mod

    orig = client_mod.BitableClient

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")

    def factory(app_id: str, app_secret: str) -> object:
        return orig(app_id, app_secret, http_client=http)

    monkeypatch.setattr("scripts.adoption.BitableClient", factory)

    r = await compute(_make_args(baseline=4))
    cov = r["coverage"]
    assert cov["unique_keys"] == 2  # A 重复被去重
    assert cov["ratio"] == "50.0%"
    assert cov["healthy"] is False


@pytest.mark.asyncio
async def test_coverage_zero_baseline_returns_na_not_fabricated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分母为 0：如实 N/A，绝不编造 100% 或 0%。

    这是 troubleshooting.md「不猜、不编」原则在运营工具上的延伸。
    """
    monkeypatch.setenv("BASEPILOT_APP_ID", "cli_x")
    monkeypatch.setenv("BASEPILOT_APP_SECRET", "secret_x")

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/records/search"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"has_more": False, "items": []}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    import basepilot.client as client_mod

    orig = client_mod.BitableClient
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    monkeypatch.setattr(
        "scripts.adoption.BitableClient",
        lambda a, s: orig(a, s, http_client=http),
    )

    r = await compute(_make_args(baseline=0))
    assert "N/A" in str(r["coverage"]["ratio"])
    assert r["coverage"]["healthy"] is None


@pytest.mark.asyncio
async def test_sla_overdue_counts_only_open_and_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SLA：只统计「未闭环」且「日期早于阈值」的；已闭环/未逾期不计。"""
    monkeypatch.setenv("BASEPILOT_APP_ID", "cli_x")
    monkeypatch.setenv("BASEPILOT_APP_SECRET", "secret_x")

    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 10 * 86_400_000  # 10 天前（超 7 天 SLA）
    recent_ms = now_ms - 2 * 86_400_000  # 2 天前（未超）

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/records/search"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "has_more": False,
                        "items": [
                            # 未闭环 + 超期 → 计入 overdue
                            {
                                "record_id": "r1",
                                "fields": {"处理状态": "待处理", "差评日期": old_ms},
                            },
                            # 未闭环 + 未超期 → 只计入 total_open
                            {
                                "record_id": "r2",
                                "fields": {"处理状态": "跟进中", "差评日期": recent_ms},
                            },
                            # 已闭环 → 两边都不计
                            {
                                "record_id": "r3",
                                "fields": {"处理状态": "已闭环", "差评日期": old_ms},
                            },
                        ],
                    },
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    import basepilot.client as client_mod

    orig = client_mod.BitableClient
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    monkeypatch.setattr(
        "scripts.adoption.BitableClient",
        lambda a, s: orig(a, s, http_client=http),
    )

    r = await compute(
        _make_args(
            baseline=3,
            status_field="处理状态",
            date_field="差评日期",
            sla_days=7,
        )
    )
    sla = r["sla"]
    assert sla["status"] == "computed"
    assert sla["total_open"] == 2  # r1 + r2（r3 已闭环）
    assert sla["overdue"] == 1  # 只有 r1 超期
    assert sla["ratio"] == "50.0%"
    assert sla["healthy"] is False


@pytest.mark.asyncio
async def test_adoption_always_pending_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """采用率恒 pending_config：三表无 User 字段，如实报不编造。"""
    monkeypatch.setenv("BASEPILOT_APP_ID", "cli_x")
    monkeypatch.setenv("BASEPILOT_APP_SECRET", "secret_x")

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/records/search"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"has_more": False, "items": []}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    import basepilot.client as client_mod

    orig = client_mod.BitableClient
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    monkeypatch.setattr(
        "scripts.adoption.BitableClient",
        lambda a, s: orig(a, s, http_client=http),
    )

    r = await compute(_make_args(baseline=0))
    ado = r["adoption"]
    assert ado["status"] == "pending_config"
    assert "reason" in ado
