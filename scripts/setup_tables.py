"""建跨境「运营异常闭环台账」三张表 —— 真实业务场景的可复现资产。

三张表覆盖跨境电商运营的核心异常闭环，且**刻意覆盖全部易错字段类型**：
- 库存健康表：单选(3)、数字(2)、日期(5)、公式(20 系统只读)、人员(11)
- 广告异常表：单选(3)、多选(4)、数字(2)、日期(5)、超链接(15)、关联(21)
- 差评处理表：单选(3)、多选(4)、日期(5)、人员(11)、超链接(15)、复选(7)

用法：
    python scripts/setup_tables.py <app_token>
输出：三张表的 table_id 与字段清单（写 tests/cassettes/ 用）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from basepilot.auth import TokenCache


def _load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------------------
# 三张表的字段设计（type 编号见 schema.py）
# ---------------------------------------------------------------------------

# 库存健康表
INVENTORY_FIELDS = [
    {"field_name": "SKU", "type": 1},  # 文本（唯一键）
    {"field_name": "ASIN", "type": 1},
    {"field_name": "站点", "type": 3, "property": {"options": [
        {"name": "US"}, {"name": "DE"}, {"name": "JP"}]}},
    {"field_name": "FBA库存", "type": 2},
    {"field_name": "在途库存", "type": 2},
    {"field_name": "日均销量", "type": 2},
    {"field_name": "可售天数", "type": 20, "property": {  # 公式（系统只读）
        "formula_expression": "IF({日均销量}>0, {FBA库存}/{日均销量}, 999)"}},
    {"field_name": "库存健康", "type": 3, "property": {"options": [
        {"name": "正常"}, {"name": "预警"}, {"name": "断货风险"}, {"name": "压货"}]}},
    {"field_name": "负责人", "type": 11},
    {"field_name": "最近盘点", "type": 5, "property": {"date_formatter": "yyyy-MM-dd"}},
]

# 广告异常表
ADS_FIELDS = [
    {"field_name": "广告活动", "type": 1},
    {"field_name": "SKU", "type": 1},
    {"field_name": "异常类型", "type": 4, "property": {"options": [  # 多选
        {"name": "ACOS超标"}, {"name": "花费突增"}, {"name": "曝光暴跌"},
        {"name": "转化归零"}, {"name": "预算耗尽"}]}},
    {"field_name": "ACOS", "type": 2},
    {"field_name": "日花费", "type": 2},
    {"field_name": "严重程度", "type": 3, "property": {"options": [
        {"name": "P0"}, {"name": "P1"}, {"name": "P2"}]}},
    {"field_name": "广告后台", "type": 15},  # 超链接
    {"field_name": "关联库存", "type": 21, "property": {  # 双向关联（占位，建表后回填 table_id）
        "table_id": "", "multiple": True}},
    {"field_name": "发现时间", "type": 5, "property": {"date_formatter": "yyyy-MM-dd HH:mm"}},
    {"field_name": "处理人", "type": 11},
]

# 差评处理表
REVIEW_FIELDS = [
    {"field_name": "订单号", "type": 1},  # 唯一键
    {"field_name": "SKU", "type": 1},
    {"field_name": "星级", "type": 3, "property": {"options": [
        {"name": "1星"}, {"name": "2星"}, {"name": "3星"}]}},
    {"field_name": "差评标签", "type": 4, "property": {"options": [  # 多选
        {"name": "质量"}, {"name": "物流"}, {"name": "尺寸"},
        {"name": "描述不符"}, {"name": "客服"}]}},
    {"field_name": "差评内容", "type": 1},
    {"field_name": "买家链接", "type": 15},
    {"field_name": "处理状态", "type": 3, "property": {"options": [
        {"name": "待处理"}, {"name": "跟进中"}, {"name": "已解决"}, {"name": "无法挽回"}]}},
    {"field_name": "需要退款", "type": 7},  # 复选框
    {"field_name": "处理人", "type": 11},
    {"field_name": "差评日期", "type": 5, "property": {"date_formatter": "yyyy-MM-dd"}},
]


async def _create_table(
    http: httpx.AsyncClient, app_token: str, name: str, fields: list[dict]
) -> tuple[str, dict[str, str]]:
    """建一张表并配字段，返回 (table_id, {字段名: field_id})。"""
    resp = await http.post(
        f"/bitable/v1/apps/{app_token}/tables",
        json={"table": {"name": name, "default_view_name": "全部", "fields": fields}},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"建表 {name} 失败：{data.get('code')} {data.get('msg')}")
    table_id = data["data"]["table_id"]
    # 拉字段 id
    fresp = await http.get(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        params={"page_size": 100},
    )
    fdata = fresp.json()
    fmap = {it["field_name"]: it["field_id"] for it in fdata["data"]["items"]}
    return table_id, fmap


async def setup(app_token: str) -> int:
    app_id = os.environ.get("BASEPILOT_APP_ID", "")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET", "")
    cache = TokenCache(app_id, app_secret)
    token = await cache.get()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(
        base_url="https://open.feishu.cn/open-apis", headers=headers, timeout=30
    ) as http:
        print(f"在 app={app_token} 建三张表\n")

        # 1. 库存健康表（先建，广告表的关联字段要指向它）
        inv_tid, inv_fmap = await _create_table(http, app_token, "库存健康表", INVENTORY_FIELDS)
        print(f"✅ 库存健康表  table_id={inv_tid}  ({len(inv_fmap)} 字段)")

        # 2. 广告异常表（关联字段回填库存表 id）
        ads_fields = []
        for f in ADS_FIELDS:
            f = dict(f)
            if f["field_name"] == "关联库存":
                f["property"] = {"table_id": inv_tid, "multiple": True}
            ads_fields.append(f)
        ads_tid, ads_fmap = await _create_table(http, app_token, "广告异常表", ads_fields)
        print(f"✅ 广告异常表  table_id={ads_tid}  ({len(ads_fmap)} 字段)")

        # 3. 差评处理表
        rev_tid, rev_fmap = await _create_table(http, app_token, "差评处理表", REVIEW_FIELDS)
        print(f"✅ 差评处理表  table_id={rev_tid}  ({len(rev_fmap)} 字段)")

        print("\n=== 三张表就绪 ===")
        print(f"APP={app_token}")
        print(f"INVENTORY_TABLE={inv_tid}")
        print(f"ADS_TABLE={ads_tid}")
        print(f"REVIEW_TABLE={rev_tid}")
        print("\n把上面三行 table_id 写进 .env 或 tests/cassettes 配置即可。")
        return 0


def main() -> int:
    _load_env()
    if len(sys.argv) < 2:
        print("用法：python scripts/setup_tables.py <app_token>")
        return 1
    return asyncio.run(setup(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
