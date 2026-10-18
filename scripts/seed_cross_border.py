"""跨境电商场景包灌数脚本 —— 用 batch_upsert 把三张表的示例数据写入真实租户。

用途：
1. 客户演示前一键准备数据（幂等：再跑一遍不会重复，只会按唯一键更新）
2. 真实租户回归：验证多选(4)/URL(15)/勾选(7)/日期时间(5) 等易错字段编码
3. cassette 录制素材：本脚本的真实 HTTP 交互即 cassette 来源

用法：
    python scripts/seed_cross_border.py          # 全量灌三张表 + 读回校验
    python scripts/seed_cross_border.py --check  # 只读回校验，不写入
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basepilot.client import BitableClient  # noqa: E402
from basepilot.scenarios.cross_border import (  # noqa: E402
    ADS_SAMPLE,
    INVENTORY_SAMPLE,
    REVIEW_SAMPLE,
    TABLE_IDS,
)

APP_TOKEN = "__REDACTED_APP_TOKEN__"

#: 每张表：(示例数据, 唯一键字段名)
PLAN = {
    "inventory": (INVENTORY_SAMPLE, "SKU"),
    "ads": (ADS_SAMPLE, "广告活动"),
    "review": (REVIEW_SAMPLE, "订单号"),
}


def normalize_key(value: object) -> str:
    """把 API 读回的字段值归一化成可比较的字符串键。

    读结构 ≠ 写结构的实锤：文本字段写入时是纯字符串，
    读回时却是富文本数组 [{"type":"text","text":"..."}]。
    唯一键提取必须兼容两种形态，否则 batch_upsert 的
    "exists→update" 判断会失配（list 不可哈希 / 比对不上）。
    """
    if isinstance(value, list):
        parts = [
            seg.get("text", "")
            for seg in value
            if isinstance(seg, dict) and seg.get("type") == "text"
        ]
        return "".join(parts)
    if value is None:
        return ""
    return str(value)


async def seed_one(client: BitableClient, name: str) -> dict[str, object]:
    """对一张表执行 batch_upsert 并读回校验。"""
    rows, key_field = PLAN[name]
    table_id = TABLE_IDS[name]

    # 1) 查唯一键已存在的记录 → 拆 update / create
    existing = await client.search_records(APP_TOKEN, table_id)
    by_key = {
        normalize_key((rec.get("fields") or {}).get(key_field)): rec["record_id"]
        for rec in existing
        if normalize_key((rec.get("fields") or {}).get(key_field))
    }

    to_update = [
        {"record_id": by_key[r[key_field]], "fields": r}
        for r in rows
        if r[key_field] in by_key
    ]
    to_create = [r for r in rows if r[key_field] not in by_key]

    if to_update:
        await client.update_records(APP_TOKEN, table_id, to_update)
    if to_create:
        await client.create_records(APP_TOKEN, table_id, to_create)

    # 2) 读回校验
    after = await client.search_records(APP_TOKEN, table_id)
    got_keys = sorted(
        normalize_key((rec.get("fields") or {}).get(key_field))
        for rec in after
    )
    want_keys = sorted(str(r[key_field]) for r in rows)
    ok = got_keys == want_keys

    return {
        "table": name,
        "created": len(to_create),
        "updated": len(to_update),
        "total_after": len(after),
        "keys_match": ok,
        "records": [
            {"record_id": rec["record_id"], "fields": rec.get("fields", {})}
            for rec in after
        ],
    }


async def check_one(client: BitableClient, name: str) -> dict[str, object]:
    """只读回，不写入。"""
    table_id = TABLE_IDS[name]
    rows = await client.search_records(APP_TOKEN, table_id)
    return {
        "table": name,
        "total": len(rows),
        "records": [
            {"record_id": r["record_id"], "fields": r.get("fields", {})}
            for r in rows
        ],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="只读回校验，不写入"
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    app_id = os.environ.get("BASEPILOT_APP_ID")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET")
    if not app_id or not app_secret:
        print("ERROR: 请在 .env 配置 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET", file=sys.stderr)
        return 2

    client = BitableClient(app_id, app_secret)
    try:
        results = []
        for name in PLAN:
            if args.check:
                res = await check_one(client, name)
                print(f"[check] {name}: {res['total']} 条记录")
            else:
                res = await seed_one(client, name)
                status = "OK" if res["keys_match"] else "MISMATCH"
                print(
                    f"[seed] {name}: created={res['created']} "
                    f"updated={res['updated']} total={res['total_after']} "
                    f"keys={status}"
                )
            results.append(res)

        # 把读回结果落盘，供 cassette / 报告引用（脱敏：不含凭证）
        out = Path(__file__).resolve().parent.parent / "tmp" / "seed_result.json"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass  # 沙箱/代理层偶发 EEXIST 竞态，目录其实已存在
        out.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n读回快照已写入 {out}")

        if not args.check and not all(r.get("keys_match") for r in results):
            return 1
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
