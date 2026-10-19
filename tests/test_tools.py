"""MCP 工具层端到端测试 —— 用 call_tool 走真实 MCP 协议路径。

不是测工具函数本身，而是测「LLM 通过 MCP 协议调用工具」的完整链路：
工具发现 → 参数 schema → 调用 → 五层引擎 → 返回可读结果。

核心断言：**dry_run 工具的真实 HTTP 写调用数 = 0**。
"""

from __future__ import annotations

import httpx
import pytest

from basepilot.client import BitableClient
from basepilot.tools import build_server


def _ok_token(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/tenant_access_token/internal"):
        return httpx.Response(
            200,
            json={"code": 0, "msg": "ok", "tenant_access_token": "t", "expire": 7200},
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
                {"field_name": "SKU", "type": 1},
            ],
        },
    }


def _build() -> tuple:
    write_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_payload())
        # 记录所有写请求（POST 到 records 相关路径，非 search）
        if request.method == "POST" and "/records" in request.url.path:
            if request.url.path.endswith("/search"):
                return httpx.Response(
                    200,
                    json={"code": 0, "msg": "ok", "data": {"has_more": False, "items": []}},
                )
            write_calls.append(request.url.path)
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": [{"record_id": "r"}]}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "unexpected " + request.url.path})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    client = BitableClient("cli_x", "secret_x", http_client=http)
    server = build_server(client)
    return server, client, write_calls


@pytest.mark.asyncio
async def test_tools_discoverable() -> None:
    """8 个工具必须能通过 MCP 协议被发现。"""
    server, client, _ = _build()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "describe_table",
        "create_records",
        "update_records",
        "delete_records",
        "search_records",
        "batch_upsert",
        "dry_run_create",
        "diagnose_scenarios",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_call_describe_table() -> None:
    """describe_table 返回字段结构含 type 与可读名。"""
    server, client, _ = _build()
    result = await server.call_tool("describe_table", {"app_token": "app", "table_id": "tbl"})
    # fastmcp 把 dict 结果包成结构化内容
    data = result.structured_content
    assert data["field_count"] == 3
    by_name = {f["field_name"]: f for f in data["fields"]}
    assert by_name["状态"]["type"] == 3
    assert by_name["状态"]["type_name"] == "SINGLE_SELECT"
    assert by_name["创建时间"]["system_readonly"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_dry_run_makes_zero_write_calls() -> None:
    """核心指标：dry_run 预演时，真实 HTTP 写调用数必须为 0。"""
    server, client, write_calls = _build()
    result = await server.call_tool(
        "dry_run_create",
        {
            "app_token": "app",
            "table_id": "tbl",
            "records": [{"状态": "正常", "创建时间": 1674206443}],
        },
    )
    data = result.structured_content
    assert data["dry_run"] is True
    assert data["ok"] == 1
    assert data["failed"] == 0
    # 编码正确性：秒级时间戳被转成毫秒
    assert data["records"][0]["encoded"]["创建时间"] == 1674206443000
    # 关键断言：没有任何写请求发出
    assert write_calls == [], f"dry_run 不应发写请求，实际: {write_calls}"
    await client.aclose()


@pytest.mark.asyncio
async def test_dry_run_reports_field_errors() -> None:
    """dry_run 必须指出哪些记录会失败，而不是默默通过。"""
    server, client, _ = _build()
    result = await server.call_tool(
        "dry_run_create",
        {
            "app_token": "app",
            "table_id": "tbl",
            "records": [
                {"状态": "正常"},  # 合法
                {"状态": ["正常", "异常"]},  # 单选传数组 → 失败
            ],
        },
    )
    data = result.structured_content
    assert data["ok"] == 1
    assert data["failed"] == 1
    failed_rec = next(r for r in data["records"] if not r["ok"])
    assert "1254062" in failed_rec["error"]
    await client.aclose()


@pytest.mark.asyncio
async def test_call_create_records_end_to_end() -> None:
    """create_records 工具走完整链路，字段编码生效。"""
    server, client, write_calls = _build()
    client._serializer._min_interval = 0.0
    result = await server.call_tool(
        "create_records",
        {
            "app_token": "app",
            "table_id": "tbl",
            "records": [{"状态": ["正常"], "创建时间": 1674206443}],
        },
    )
    data = result.structured_content
    assert data["created"] == 1
    assert len(write_calls) == 1
    assert write_calls[0].endswith("/batch_create")
    await client.aclose()


@pytest.mark.asyncio
async def test_call_diagnose_scenarios_offline() -> None:
    """diagnose_scenarios 不联网，返回四象限诊断。"""
    server, client, _ = _build()
    result = await server.call_tool("diagnose_scenarios", {})
    data = result.structured_content
    assert data["total_scenarios"] > 0
    assert "by_quadrant" in data
    # 每个结果都含决策所需字段
    r0 = data["results"][0]
    for key in ("name", "score", "quadrant", "strategy", "annual_hours_saved", "evidence"):
        assert key in r0
    await client.aclose()
