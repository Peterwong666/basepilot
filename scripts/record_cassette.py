"""录制跨境场景的真实 HTTP 交互到 cassette。

录的是一次**典型交付流**，覆盖最容易出问题的操作组合：
1. 鉴权（tenant_access_token）
2. describe_table（库存表字段元信息）
3. search_records（查 SKU 已存在的记录，读回富文本数组）
4. upsert_records（混合批：1 条已存在→update，1 条新→create）
5. search_records 再查一次（验证 upsert 结果）

这份 cassette 是「读结构≠写结构」的铁证：
- 请求体里文本字段是纯字符串（写入）
- 响应体里文本字段是富文本数组（读回）

用法：
    python scripts/record_cassette.py
    # 产物：tests/cassettes/cross_border_upsert.jsonl

⚠️ 会在真实租户产生临时记录（SKU=__CASSETTE_PROBE__），跑完自动删除。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from basepilot.cassette import RecordingTransport  # noqa: E402
from basepilot.client import BitableClient  # noqa: E402

CASSETTE = (
    Path(__file__).resolve().parent.parent
    / "tests" / "cassettes" / "cross_border_upsert.jsonl"
)
#: 真实 app_token / table_id 从环境变量读，不写死在本仓库里
#: （录制需要真实值，但真实值不该进版本库 —— 见 tests/test_no_secrets_in_repo.py）
#: 注意必须在 load_dotenv 之后读，故在 main() 内取用。
APP = ""
TABLE = ""
PROBE_SKU = "__CASSETTE_PROBE__"


def _prepare() -> tuple[str, str]:
    """同步准备：读 .env + 清空旧 cassette（阻塞 IO 挪出 async 函数）。"""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    app_id = os.environ.get("BASEPILOT_APP_ID", "")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET", "")
    CASSETTE.parent.mkdir(parents=True, exist_ok=True)
    if CASSETTE.exists():
        CASSETTE.unlink()
    return app_id, app_secret


async def main() -> int:
    global APP, TABLE
    app_id, app_secret = _prepare()
    # _prepare() 里已 load_dotenv，此处才能读到值
    APP = os.environ.get("BASEPILOT_APP_TOKEN", "")
    TABLE = os.environ.get("BASEPILOT_TABLE_INVENTORY", "")
    if not app_id or not app_secret:
        print("缺少 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET", file=sys.stderr)
        return 2
    if not APP or not TABLE:
        print("缺少 BASEPILOT_APP_TOKEN / BASEPILOT_TABLE_INVENTORY", file=sys.stderr)
        return 2

    # 包一层录制 transport（沿用 BitableClient 默认 30s 超时，避免连接抖动）
    inner = httpx.AsyncHTTPTransport(retries=2)
    recording = RecordingTransport(
        inner, CASSETTE, secrets={app_secret}
    )
    http = httpx.AsyncClient(
        transport=recording,
        base_url="https://open.feishu.cn/open-apis",
        timeout=30.0,
    )

    client = BitableClient(app_id, app_secret, http_client=http)
    try:
        # 1+2. 鉴权 + describe
        meta = await client.list_fields(APP, TABLE)
        print(f"1. describe_table：{len(meta)} 个字段")

        # 3. 先 upsert 一条探测记录（create 分支）
        r1 = await client.upsert_records(
            APP, TABLE,
            [{"SKU": PROBE_SKU, "FBA库存": 1, "库存健康": "正常"}],
            "SKU",
        )
        print(f"2. 第一次 upsert（probe 新建）：created={r1['created']} updated={r1['updated']}")

        # 4. 再 upsert 同一条（update 分支，验证幂等）+ 一条已存在的真实 SKU
        r2 = await client.upsert_records(
            APP, TABLE,
            [
                {"SKU": PROBE_SKU, "FBA库存": 2, "库存健康": "正常"},  # 已存在→update
                {"SKU": "PET-BOWL-001", "FBA库存": 95},                # 种子数据已存在→update
            ],
            "SKU",
        )
        print(f"3. 第二次 upsert（混合批）：created={r2['created']} updated={r2['updated']}")

        # 5. search 验证 + 找到 probe 的 record_id 用于清理
        items = await client.search_records(APP, TABLE, field_names=["SKU", "FBA库存"])
        probe = next(
            (i for i in items
             if (i.get("fields") or {}).get("SKU", [{}])[0].get("text") == PROBE_SKU
             if isinstance((i.get("fields") or {}).get("SKU"), list)),
            None,
        )
        print(f"4. search 读回 {len(items)} 条，probe={'找到' if probe else '未找到'}")

        # 6. 清理 probe
        if probe:
            await client.delete_records(APP, TABLE, [probe["record_id"]])
            print(f"5. 已清理 probe 记录 {probe['record_id']}")

        lines = CASSETTE.read_text(encoding="utf-8").splitlines()
        print(f"\n✅ cassette 已录制 {len(lines)} 条交互 → {CASSETTE}")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
