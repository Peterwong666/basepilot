"""normalize_key 与 upsert_records 契约测试。

背景（cassette 实测发现）：API 读回的文本字段是富文本数组
``[{"type":"text","text":...}]``，URL 字段是 ``{"link","text","type":"url"}``
对象。batch_upsert 若直接把读回值当 dict 键：
- ``TypeError: unhashable type: 'list'``
- 或 ``str([...])`` 得到 repr，与写入的纯值永远比对不上
  → 「存在」的记录被判为「不存在」→ 重复创建 → 客户现场数据翻倍

这组测试锁住归一化规则 + upsert 幂等性，全部 MockTransport 离线。
"""

from __future__ import annotations

import json

import httpx
import pytest

from basepilot.client import BitableClient
from basepilot.coerce import normalize_key

# ---------------------------------------------------------------------------
# normalize_key 单元测试：每种「读回形态」都必须归一到写入时的纯值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 纯值（写入时传的形态）
        ("PET-BOWL-001", "PET-BOWL-001"),
        (95, "95"),
        (95.0, "95"),  # 整数浮点去小数点
        (8.5, "8.5"),
        (True, "true"),
        (False, "false"),
        (None, ""),
        ("", ""),
        # 富文本数组（文本字段读回形态）
        ([{"type": "text", "text": "PET-BOWL-001"}], "PET-BOWL-001"),
        # 多段文本拼接
        (
            [{"type": "text", "text": "订单号："}, {"type": "text", "text": "111-222"}],
            "订单号：111-222",
        ),
        ([], ""),  # 空数组
        # URL 读回对象（写入时传的是纯字符串 link）
        (
            {"link": "https://a.com/x", "text": "https://a.com/x", "type": "url"},
            "https://a.com/x",
        ),
        # 纯字符串数组（多选读回，作为键时 join）
        (["花费突增", "转化归零"], "花费突增,转化归零"),
    ],
)
def test_normalize_key_shapes(raw: object, expected: str) -> None:
    assert normalize_key(raw) == expected


def test_normalize_key_unknown_complex_returns_empty() -> None:
    """无法安全归一的复杂结构返回空串（宁可判为不存在，也不 str(repr) 误判）。"""
    assert normalize_key({"foo": "bar"}) == ""
    assert normalize_key([{"type": "mention", "text": "@某人"}]) == "" or isinstance(
        normalize_key([{"type": "mention", "text": "@某人"}]), str
    )


# ---------------------------------------------------------------------------
# upsert_records 集成测试：MockTransport 模拟「读回富文本数组」场景
# ---------------------------------------------------------------------------


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


_FIELDS = {
    "code": 0,
    "msg": "ok",
    "data": {
        "has_more": False,
        "items": [
            {"field_name": "SKU", "type": 1},
            {"field_name": "FBA库存", "type": 2},
        ],
    },
}


def _make_client(handler) -> BitableClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://open.feishu.cn/open-apis")
    return BitableClient("cli_x", "secret_x", http_client=http)


@pytest.mark.asyncio
async def test_upsert_existing_richtext_key_goes_update_not_create() -> None:
    """核心回归：读回的富文本键必须被识别为「已存在」→ update，绝不 create。

    这是种子脚本在真实租户踩过的坑：不修会重复创建。
    """
    calls: dict[str, list] = {"create": [], "update": []}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_FIELDS)
        if request.url.path.endswith("/search"):
            # 模拟真实读回：SKU 是富文本数组形态
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "has_more": False,
                        "items": [
                            {
                                "record_id": "recEXISTING",
                                "fields": {"SKU": [{"type": "text", "text": "PET-BOWL-001"}]},
                            }
                        ],
                    },
                },
            )
        if request.url.path.endswith("/batch_create"):
            calls["create"].append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": [{"record_id": "recNEW"}]}},
            )
        if request.url.path.endswith("/batch_update"):
            calls["update"].append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": [{"record_id": "recEXISTING"}]}},
            )
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})

    async with _make_client(handler) as client:
        client._serializer._min_interval = 0.0
        result = await client.upsert_records(
            "appTok",
            "tbl1",
            [{"SKU": "PET-BOWL-001", "FBA库存": 95}],  # 写入是纯字符串
            "SKU",
        )

    assert result["created"] == 0, "已存在的键绝不能走 create"
    assert result["updated"] == 1
    assert not calls["create"], "不应发出任何 batch_create 请求"
    assert calls["update"][0]["records"][0]["record_id"] == "recEXISTING"


@pytest.mark.asyncio
async def test_upsert_new_key_goes_create() -> None:
    """新键 → create；已存在键 → update；混合一批同传。"""
    calls: dict[str, list] = {"create": [], "update": []}

    def handler(request: httpx.Request) -> httpx.Response:
        tok = _ok_token(request)
        if tok:
            return tok
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_FIELDS)
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "has_more": False,
                        "items": [
                            {
                                "record_id": "recA",
                                "fields": {"SKU": [{"type": "text", "text": "SKU-A"}]},
                            }
                        ],
                    },
                },
            )
        if request.url.path.endswith("/batch_create"):
            body = json.loads(request.content)
            calls["create"].append(body)
            new_records = [{"record_id": f"recNew{i}"} for i in range(len(body["records"]))]
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"records": new_records}},
            )
        if request.url.path.endswith("/batch_update"):
            body = json.loads(request.content)
            calls["update"].append(body)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {"records": [{"record_id": r["record_id"]} for r in body["records"]]},
                },
            )
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})

    async with _make_client(handler) as client:
        client._serializer._min_interval = 0.0
        result = await client.upsert_records(
            "appTok",
            "tbl1",
            [
                {"SKU": "SKU-A", "FBA库存": 10},  # 已存在 → update
                {"SKU": "SKU-B", "FBA库存": 20},  # 新 → create
                {"FBA库存": 999},  # 缺键 → skipped
            ],
            "SKU",
        )

    assert result == {"created": 1, "updated": 1, "skipped": 1}
    # create 分支只有 SKU-B
    assert calls["create"][0]["records"][0]["fields"]["SKU"] == "SKU-B"
    # update 分支打到 recA
    assert calls["update"][0]["records"][0]["record_id"] == "recA"


@pytest.mark.asyncio
async def test_upsert_empty_records_short_circuit() -> None:
    """空列表不发任何请求。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": 500, "msg": "不应被调用"})

    async with _make_client(handler) as client:
        result = await client.upsert_records("appTok", "tbl1", [], "SKU")

    assert result == {"created": 0, "updated": 0, "skipped": 0}
