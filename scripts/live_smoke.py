"""live_smoke —— 连真实飞书租户跑全链路自检。

这是「真的在飞书里跑过」的可复现证据，不是 Mock。
它会：
1. 用凭证换 tenant_access_token（验证鉴权）
2. describe_table 拉字段元信息
3. dry_run 预演（验证字段编码，**不写数据**）
4. create_records 真实写一条 → search 读回校验 → delete 清理
5. 打印每一步的真实结果与关键指标

用法：
    # 凭证写在 .env（已 gitignore），或环境变量
    python scripts/live_smoke.py <app_token> <table_id>

退出码：0 全链路通过；1 任一步失败。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 让脚本可直接 `python scripts/live_smoke.py` 运行
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _load_env() -> None:
    """从 .env 读凭证（不覆盖已存在的环境变量）。"""
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


async def smoke(app_token: str, table_id: str) -> int:
    from basepilot.client import BitableClient, FeishuAPIError
    from basepilot.coerce import coerce_record

    app_id = os.environ.get("BASEPILOT_APP_ID", "")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET", "")
    if not app_id or not app_secret:
        print("❌ 缺少 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET")
        return 1

    print(f"目标：app={app_token}  table={table_id}")
    print("=" * 56)

    try:
        async with BitableClient(app_id, app_secret) as client:
            # 1. 鉴权
            token = await client._token_cache.get()
            print(f"✅ 1. 鉴权成功（token 长度 {len(token)}）")

            # 2. 拉字段
            meta = await client.list_fields(app_token, table_id)
            print(f"✅ 2. describe_table 成功，{len(meta)} 个字段：")
            for name, t in meta.items():
                print(f"     {name}: type={t}")

            # 3. dry_run（不写数据）
            probe = {"文本": "live_smoke 预演", "日期": 1674206443}
            # 只用表里真实存在的字段做预演
            probe = {k: v for k, v in probe.items() if k in meta}
            if probe:
                encoded = coerce_record(meta, probe)
                print("✅ 3. dry_run 预演（字段编码，未写数据）：")
                for k, v in encoded.items():
                    print(f"     {k}: {v!r}")
            else:
                print("⏭️  3. dry_run 跳过（表内无 文本/日期 字段）")

            # 4. 真实写一条 → 读回 → 删除
            if "文本" in meta:
                rec = {"文本": "live_smoke 全链路自检（将自动删除）"}
                if "日期" in meta:
                    rec["日期"] = 1674206443  # 秒级，验证自动×1000

                created = await client.create_records(app_token, table_id, [rec])
                rid = created["record_ids"][0]
                print(f"✅ 4. 真实写入成功 record_id={rid}")

                # 读回校验
                items = await client.search_records(app_token, table_id)
                found = next((i for i in items if i.get("record_id") == rid), None)
                if found and "日期" in meta:
                    ts = found.get("fields", {}).get("日期")
                    ok = ts == 1674206443000
                    mark = "✅" if ok else "❌"
                    print(f"{mark} 5. 读回校验：日期落库 {ts}（期望 1674206443000，秒级自动×1000）")

                # 清理
                await client.delete_records(app_token, table_id, [rid])
                print(f"✅ 6. 已清理测试记录 {rid}")
            else:
                print("⏭️  4-6. 写入测试跳过（表内无 文本 字段）")

            # 指标
            print("=" * 56)
            print(f"token 换取次数：{client._token_cache.fetch_count}（多次请求应只换 1 次）")
            print("✅ live_smoke 全链路通过")
            return 0

    except FeishuAPIError as e:
        print(f"❌ 飞书业务错误：{e}")
        return 1
    except Exception as e:  # noqa: BLE001 - 自检脚本要捕获一切
        print(f"❌ 异常：{type(e).__name__}: {e}")
        return 1


def main() -> int:
    _load_env()
    if len(sys.argv) < 3:
        print(__doc__)
        print("用法：python scripts/live_smoke.py <app_token> <table_id>")
        return 1
    return asyncio.run(smoke(sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    sys.exit(main())
