"""BitableClient 契约测试 —— 用 MockTransport 全离线验证五层串联。

每条测试断言一个「如果写错了，客户现场就会出事」的行为：
- 字段编码是否真的在写前发生
- 串行器是否真的把并发压到 1
- 错误码是否真的按规则表处置
- token 是否真的被缓存复用
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from basepilot.client import BitableClient, FeishuAPIError


def _ok_token(request: httpx.Request) -> httpx.Response | None:
    """命中鉴权端点返回 token，否则返回 None 让后续 handler 处理。"""
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


def _fields_payload() -> dict:
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "has_more": False,
            "items": [
                {"field_name": "状态", "type": 3},
                {"field_name": "创建时间", "type": 5},
                {"field_name": "负责人", "type": 11},
            ],
        },
    }


def _make_client(handler) -> BitableClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    return BitableClient("cli_x", "secret_x", http_client=http)


@pytest.mark.asyncio
async def test_create_records_coerces_fields_before_write() -> None:
    """写记录前必须做字段编码：秒级时间戳 → 13 位毫秒，数组单选 → 字符串。"""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/batch_create"):
            import json as _json

            captured.append(_json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {"records": [{"record_id": "rec1"}]},
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})

    async with _make_client(handler) as client:
        result = await client.create_records(
            "appTok",
            "tbl1",
            [{"状态": ["正常"], "创建时间": 1674206443, "负责人": "ou_x"}],
        )

    assert result["created"] == 1
    fields = captured[0]["records"][0]["fields"]
    assert fields["状态"] == "正常"  # 数组被压成字符串
    assert fields["创建时间"] == 1674206443000  # 秒 → 毫秒
    assert fields["负责人"] == [{"id": "ou_x"}]


@pytest.mark.asyncio
async def test_same_table_writes_are_serialized() -> None:
    """同一张表的并发写，在飞书侧看到的并发必须 = 1。"""
    in_flight = 0
    peak = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/batch_create"):
            in_flight += 1
            peak = max(peak, in_flight)
            in_flight -= 1
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": [{"record_id": "r"}]}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        # 用极小节流间隔加速压测
        client._serializer._min_interval = 0.0
        await asyncio.gather(
            *[client.create_records("appTok", "tblSame", [{"状态": "正常"}]) for _ in range(50)]
        )

    assert peak == 1, f"飞书侧观测到的并发应为 1，实测 {peak}"


@pytest.mark.asyncio
async def test_fail_fast_error_not_retried() -> None:
    """权限类错误（FAIL_FAST）必须立即抛，不重试 —— 重试无意义。"""
    calls = {"batch_create": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/batch_create"):
            calls["batch_create"] += 1
            # 1254043 NoTablePerm 之类权限错误（取规则表里的一个 FAIL_FAST 码）
            from basepilot.errors import RULES, Action

            code = next(c for c, r in RULES.items() if r.action is Action.FAIL_FAST)
            return httpx.Response(200, json={"code": code, "msg": "no permission", "data": {}})
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        with pytest.raises(FeishuAPIError):
            await client.create_records("appTok", "tbl1", [{"状态": "正常"}])

    assert calls["batch_create"] == 1, "FAIL_FAST 不应重试"


@pytest.mark.asyncio
async def test_retryable_error_retries_then_succeeds() -> None:
    """可重试错误（RETRY）应退避重试，最终成功。"""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/batch_create"):
            attempts["n"] += 1
            if attempts["n"] < 3:
                # 前两次返回可重试的系统忙错误
                from basepilot.errors import RULES, Action

                code = next(c for c, r in RULES.items() if r.action is Action.RETRY)
                return httpx.Response(200, json={"code": code, "msg": "busy", "data": {}})
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": [{"record_id": "r"}]}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        client._serializer._min_interval = 0.0
        result = await client.create_records("appTok", "tbl1", [{"状态": "正常"}])

    assert result["created"] == 1
    assert attempts["n"] == 3, "应重试到第 3 次才成功"


@pytest.mark.asyncio
async def test_token_cached_across_requests() -> None:
    """100 次业务请求只换 1 次 token —— 鉴权端点只被命中一次。"""
    token_fetches = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            token_fetches["n"] += 1
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "t-test",
                    "expire": 7200,
                },
            )
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"has_more": False, "items": []}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        for _ in range(100):
            await client.search_records("appTok", "tbl1")

    assert token_fetches["n"] == 1, f"100 次业务请求应只换 1 次 token，实测 {token_fetches['n']}"


@pytest.mark.asyncio
async def test_search_paginates_until_no_more() -> None:
    """search 自动翻页直到 has_more=false。"""
    pages = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/search"):
            pages["n"] += 1
            has_more = pages["n"] < 3
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "has_more": has_more,
                        "page_token": f"pt{pages['n']}" if has_more else None,
                        "items": [{"record_id": f"r{pages['n']}"}],
                    },
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        items = await client.search_records("appTok", "tbl1")

    assert pages["n"] == 3
    assert [i["record_id"] for i in items] == ["r1", "r2", "r3"]


@pytest.mark.asyncio
async def test_batch_create_splits_over_limit() -> None:
    """超过 1000 条自动分片成多次 batch_create。"""
    batches = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        if request.url.path.endswith("/batch_create"):
            batches["n"] += 1
            import json as _json

            body = _json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "records": [{"record_id": f"r{i}"} for i in range(len(body["records"]))]
                    },
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "?"})

    async with _make_client(handler) as client:
        client._serializer._min_interval = 0.0
        result = await client.create_records(
            "appTok", "tbl1", [{"状态": "正常"} for _ in range(2500)]
        )

    assert batches["n"] == 3  # 1000 + 1000 + 500
    assert result["created"] == 2500
