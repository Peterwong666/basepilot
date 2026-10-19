"""cassette 重放测试 —— 「读结构≠写结构」的铁证，CI 可重放。

这份测试重放 scripts/record_cassette.py 在真实租户录下的 10 条交互，
断言三个**只有真实 API 才能暴露**的事实：

1. **写入时**文本字段是纯字符串（seq=4/7 的请求体）
2. **读回时**文本字段是富文本数组 [{"type":"text","text":...}]（seq=3/6/8 响应体）
3. **upsert 幂等**：probe 第二次 upsert 走 update 不是 create（seq=7 batch_update）

如果哪天有人把 coerce_text 改回富文本数组，或把 normalize_key 删了，
这份测试会立刻红 —— 它锁的是「在真实飞书里验证过」的行为，不是 Mock 的想象。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basepilot.cassette import ReplayTransport
from basepilot.client import BitableClient

CASSETTE = Path(__file__).parent / "cassettes" / "cross_border_upsert.jsonl"
# 重放不真发请求，因此 app_token / table_id 用与 cassette 内一致的占位符即可 ——
# 真实值不得入库（见 tests/test_no_secrets_in_repo.py）
APP = "__REDACTED_APP_TOKEN__"
TABLE = "__REDACTED_TABLE_ID__"
PROBE_SKU = "__CASSETTE_PROBE__"


@pytest.fixture
def replay() -> ReplayTransport:
    return ReplayTransport.from_cassette(CASSETTE)


def _client(replay: ReplayTransport) -> BitableClient:
    import httpx

    http = httpx.AsyncClient(transport=replay, base_url="https://open.feishu.cn/open-apis")
    # app_id/secret 用占位符即可 —— 重放不会真发请求
    return BitableClient("cli_replay", "secret_replay", http_client=http)


@pytest.mark.asyncio
async def test_replay_full_delivery_flow(replay: ReplayTransport) -> None:
    """完整重放一次交付流，每一步的 method/path 都必须与录制一致。"""
    async with _client(replay) as client:
        client._serializer._min_interval = 0.0

        meta = await client.list_fields(APP, TABLE)
        assert "SKU" in meta

        r1 = await client.upsert_records(
            APP,
            TABLE,
            [{"SKU": PROBE_SKU, "FBA库存": 1, "库存健康": "正常"}],
            "SKU",
        )
        assert r1["created"] == 1 and r1["updated"] == 0

        r2 = await client.upsert_records(
            APP,
            TABLE,
            [
                {"SKU": PROBE_SKU, "FBA库存": 2, "库存健康": "正常"},
                {"SKU": "PET-BOWL-001", "FBA库存": 95},
            ],
            "SKU",
        )
        assert r2["created"] == 0 and r2["updated"] == 2

        items = await client.search_records(APP, TABLE, field_names=["SKU", "FBA库存"])
        assert len(items) == 4  # 3 条种子 + 1 条 probe（录制时序）

        probe = next(
            i
            for i in items
            if isinstance((i.get("fields") or {}).get("SKU"), list)
            and i["fields"]["SKU"][0].get("text") == PROBE_SKU
        )
        await client.delete_records(APP, TABLE, [probe["record_id"]])

    assert replay.exhausted, f"cassette 有 {len(replay._entries)} 条，实际只消费了 {replay._idx} 条"


@pytest.mark.asyncio
async def test_write_side_uses_plain_string_not_richtext(replay: ReplayTransport) -> None:
    """铁证①：写入请求体里，文本字段必须是纯字符串，不是富文本数组。

    这是 cassette 驱动开发的立身之本：纯 Mock 永远不会发现
    「写入≠读回」，只有重放真实交互才能锁住这个行为。
    """
    async with _client(replay) as client:
        client._serializer._min_interval = 0.0
        await client.list_fields(APP, TABLE)
        await client.upsert_records(
            APP,
            TABLE,
            [{"SKU": PROBE_SKU, "FBA库存": 1, "库存健康": "正常"}],
            "SKU",
        )

    # 找到 batch_create 那一条（seq=4），检查请求体
    create_req = next(
        r for r in replay.request_log if r["json"] and "records" in r["json"] and r["seq"] == 4
    )
    fields = create_req["json"]["records"][0]["fields"]
    assert isinstance(fields["SKU"], str), (
        f"写入时 SKU 应是纯字符串，实测 {type(fields['SKU']).__name__}: {fields['SKU']!r}"
    )
    assert fields["SKU"] == PROBE_SKU


@pytest.mark.asyncio
async def test_read_side_returns_richtext_array() -> None:
    """铁证②：读回响应体里，文本字段是富文本数组 —— 与写入形态完全不同。

    同一个字段，写入是纯字符串、读回是富文本数组，
    这就是「读结构≠写结构」，normalize_key 存在的全部理由。

    本测试直接读 cassette 原始响应体断言（不经过 client 加工），
    锁的是「飞书真实返回的结构」这个事实本身。
    """
    entries = [
        json.loads(line)
        for line in CASSETTE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # seq=3 是第一次 search（upsert 前的「查已存在」）
    search_resp = next(e for e in entries if e["seq"] == 3)
    assert search_resp["method"] == "POST"
    assert search_resp["path"].endswith("/records/search")

    first_item = search_resp["response"]["json"]["data"]["items"][0]
    sku_value = first_item["fields"]["SKU"]

    assert isinstance(sku_value, list), (
        f"读回时 SKU 应是富文本数组，实测 {type(sku_value).__name__}"
    )
    assert sku_value[0]["type"] == "text"
    assert "text" in sku_value[0]
