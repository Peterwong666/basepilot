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
import contextlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basepilot.client import BitableClient  # noqa: E402
from basepilot.coerce import normalize_key  # noqa: E402
from basepilot.scenarios.cross_border import (  # noqa: E402
    ADS_SAMPLE,
    INVENTORY_SAMPLE,
    REVIEW_SAMPLE,
    table_ids,
)

#: 跨境演示用的多维表格 app_token —— 从环境变量读。
#:
#: **旧注释曾说「app_token 本身就是给前端可见的标识」，那是错的**：
#: 可见性指的是飞书自己前端会用到它，不意味着适合公开到 GitHub。
#: 它是租户身份标识，公开等于告诉别人「这个企业租户里有这么几张表」。
CROSS_BORDER_APP = os.environ.get("BASEPILOT_APP_TOKEN", "")

#: 每张表：(示例数据, 唯一键字段名)
PLAN = {
    "inventory": (INVENTORY_SAMPLE, "SKU"),
    "ads": (ADS_SAMPLE, "广告活动"),
    "review": (REVIEW_SAMPLE, "订单号"),
}


async def seed_one(client: BitableClient, name: str, table_id: str) -> dict[str, object]:
    """对一张表执行引擎层 upsert_records 并读回校验。"""
    rows, key_field = PLAN[name]

    # 引擎层 upsert：键提取/归一化/拆 update+create 全在引擎内完成
    r = await client.upsert_records(CROSS_BORDER_APP, table_id, rows, key_field)
    created = r["created"]
    updated = r["updated"]

    # 读回校验
    after = await client.search_records(CROSS_BORDER_APP, table_id)
    got_keys = sorted(normalize_key((rec.get("fields") or {}).get(key_field)) for rec in after)
    want_keys = sorted(str(r[key_field]) for r in rows)
    ok = got_keys == want_keys

    return {
        "table": name,
        "created": created,
        "updated": updated,
        "total_after": len(after),
        "keys_match": ok,
        "records": [
            {"record_id": rec["record_id"], "fields": rec.get("fields", {})} for rec in after
        ],
    }


async def check_one(client: BitableClient, name: str, table_id: str) -> dict[str, object]:
    """只读回，不写入。"""
    rows = await client.search_records(CROSS_BORDER_APP, table_id)
    return {
        "table": name,
        "total": len(rows),
        "records": [{"record_id": r["record_id"], "fields": r.get("fields", {})} for r in rows],
    }


def _env_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".env"


def _write_snapshot(results: list[dict[str, object]]) -> Path:
    """把读回结果落盘（同步 IO，供 cassette / 报告引用，脱敏不含凭证）。"""
    out = Path(__file__).resolve().parent.parent / "tmp" / "seed_result.json"
    with contextlib.suppress(FileExistsError):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只读回校验，不写入")
    args = parser.parse_args()

    load_dotenv(_env_path())
    app_id = os.environ.get("BASEPILOT_APP_ID")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET")
    if not app_id or not app_secret:
        print(
            "ERROR: 请在 .env 配置 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET",
            file=sys.stderr,
        )
        return 2

    # app_token / 三张表的 table_id 全部从 .env 读（真实值不入库）
    global CROSS_BORDER_APP
    CROSS_BORDER_APP = os.environ.get("BASEPILOT_APP_TOKEN", "")
    tids = table_ids()
    if not CROSS_BORDER_APP or any(v.startswith("tblx") for v in tids.values()):
        print(
            "ERROR: 请在 .env 配置 BASEPILOT_APP_TOKEN 与 "
            "BASEPILOT_TABLE_INVENTORY / _ADS / _REVIEW",
            file=sys.stderr,
        )
        return 2

    client = BitableClient(app_id, app_secret)
    try:
        results = []
        for name in PLAN:
            tid = tids[name]
            if args.check:
                res = await check_one(client, name, tid)
                print(f"[check] {name}: {res['total']} 条记录")
            else:
                res = await seed_one(client, name, tid)
                status = "OK" if res["keys_match"] else "MISMATCH"
                print(
                    f"[seed] {name}: created={res['created']} "
                    f"updated={res['updated']} total={res['total_after']} "
                    f"keys={status}"
                )
            results.append(res)

        # 把读回结果落盘（同步 helper 内完成，避免在 async 函数里做阻塞 IO）
        out = await asyncio.to_thread(_write_snapshot, results)
        print(f"\n读回快照已写入 {out}")

        if not args.check and not all(r.get("keys_match") for r in results):
            return 1
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
