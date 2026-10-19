"""跨境「运营异常闭环台账」场景包 —— 三张表的字段设计与示例数据。

这是**从真实跨境电商运营里提炼**的可复用资产：
- 库存健康表：FBA 断货/压货预警（断货=Listing 降权+广告白烧）
- 广告异常表：ACOS 超标/花费突增升级（异常发现晚一天=多烧一天钱）
- 差评处理表：差评归因与挽回闭环（差评累积影响转化与账号健康）

三张表刻意覆盖全部易错字段类型（见 schema.py），
是 cassette 录制与客户演示的真实场景。
"""

from __future__ import annotations

import os

#: 三张表在**示例/文档语境**下的表名占位符。
#:
#: **为什么不存真实 table_id**：table_id 是租户身份标识，公开它等于告诉别人
#: 「这个企业租户里有这么一张表」。cassette 与源码都做过这层脱敏
#: （见 `cassette.redact_identifiers` 与 `tests/test_no_secrets_in_repo.py`），
#: 这里保持一致。
#:
#: **真实 table_id 怎么拿**：跑 `scripts/setup_tables.py` 建表后写入 `.env`
#: （已 gitignore），再由 `table_ids()` 读取。
TABLE_ID_PLACEHOLDERS = {
    "inventory": "tblxxxxxxxxxxxx",
    "ads": "tblxxxxxxxxxxxx",
    "review": "tblxxxxxxxxxxxx",
}


def table_ids() -> dict[str, str]:
    """从环境变量读三张表的真实 table_id（缺配置则返回占位符）。

    环境变量（可选，缺任一项该项回退占位符）：
        BASEPILOT_TABLE_INVENTORY / BASEPILOT_TABLE_ADS / BASEPILOT_TABLE_REVIEW
    """
    keys = {
        "inventory": "BASEPILOT_TABLE_INVENTORY",
        "ads": "BASEPILOT_TABLE_ADS",
        "review": "BASEPILOT_TABLE_REVIEW",
    }
    return {name: os.environ.get(key) or TABLE_ID_PLACEHOLDERS[name] for name, key in keys.items()}


#: 库存健康表示例数据（SKU 为唯一键，供 batch_upsert 演示）
INVENTORY_SAMPLE = [
    {
        "SKU": "PET-BOWL-001",
        "ASIN": "B0ABC123US",
        "站点": "US",
        "FBA库存": 120,
        "在途库存": 200,
        "日均销量": 8.5,
        "库存健康": "正常",
        "最近盘点": 1674206443,  # 秒级 → 自动×1000
    },
    {
        "SKU": "PET-TOY-002",
        "ASIN": "B0DEF456DE",
        "站点": "DE",
        "FBA库存": 15,
        "在途库存": 0,
        "日均销量": 6.2,
        "库存健康": "断货风险",
        "最近盘点": "2026-10-15",  # ISO → 自动转毫秒
    },
    {
        "SKU": "PET-LEASH-003",
        "ASIN": "B0GHI789JP",
        "站点": "JP",
        "FBA库存": 500,
        "在途库存": 100,
        "日均销量": 2.1,
        "库存健康": "压货",
        "最近盘点": 1729000000,
    },
]

#: 广告异常表示例数据
ADS_SAMPLE = [
    {
        "广告活动": "SP-PET-BOWL-Exact",
        "SKU": "PET-BOWL-001",
        "异常类型": ["ACOS超标"],
        "ACOS": 0.45,
        "日花费": 85.0,
        "严重程度": "P1",
        "广告后台": "https://advertising.amazon.com/cm/campaigns",
        "发现时间": 1760000000,
    },
    {
        "广告活动": "SD-PET-TOY-Broad",
        "SKU": "PET-TOY-002",
        "异常类型": ["花费突增", "转化归零"],
        "ACOS": 0.0,
        "日花费": 120.0,
        "严重程度": "P0",
        "广告后台": "https://advertising.amazon.com/cm/campaigns",
        "发现时间": "2026-10-17",
    },
]

#: 差评处理表示例数据（订单号为唯一键）
REVIEW_SAMPLE = [
    {
        "订单号": "111-2222333-4444555",
        "SKU": "PET-BOWL-001",
        "星级": "1星",
        "差评标签": ["质量"],
        "差评内容": "碗用三天就裂了",
        "买家链接": "https://www.amazon.com/gp/customer-reviews/xxx",
        "处理状态": "待处理",
        "需要退款": True,
        "差评日期": 1760000000,
    },
    {
        "订单号": "111-6666777-8888999",
        "SKU": "PET-TOY-002",
        "星级": "2星",
        "差评标签": ["尺寸", "描述不符"],
        "差评内容": "比图片小很多",
        "买家链接": "https://www.amazon.com/gp/customer-reviews/yyy",
        "处理状态": "跟进中",
        "需要退款": False,
        "差评日期": "2026-10-16",
    },
]


__all__ = [
    "TABLE_IDS",
    "INVENTORY_SAMPLE",
    "ADS_SAMPLE",
    "REVIEW_SAMPLE",
]
