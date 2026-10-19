"""共享测试夹具。

关键设计：**用 fake clock 驱动时间，不用 sleep。**
这样并发/限流测试跑得快且不flaky —— 真靠 sleep 等 0.5 秒节流的测试会让CI 慢几十倍。
"""

from __future__ import annotations

from typing import Any

import pytest


class FakeClock:
    """可手工推进的单调时钟。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sample_schema() -> dict[str, Any]:
    """一张覆盖全部易错字段类型的数据表结构（裁剪自真实响应）。

    字段名与 type 取自飞书多维表格的常见配置：
    人员=11、日期=5、单选=3、多选=4、超链接=15、附件=17、复选框=7。
    """
    return {
        "table_id": "tblTest123",
        "fields": [
            {
                "field_id": "fldSku",
                "field_name": "SKU",
                "type": 1,
                "ui_type": "Text",
                "is_primary": True,
            },
            {
                "field_id": "fldSite",
                "field_name": "站点",
                "type": 3,
                "ui_type": "SingleSelect",
                "property": {
                    "options": [{"id": "optUS", "name": "US"}, {"id": "optJP", "name": "JP"}]
                },
            },
            {"field_id": "fldAvg", "field_name": "日均销量", "type": 2, "ui_type": "Number"},
            {"field_id": "fldStock", "field_name": "现货", "type": 2, "ui_type": "Number"},
            {
                "field_id": "fldRisk",
                "field_name": "风险等级",
                "type": 4,
                "ui_type": "MultiSelect",
                "property": {
                    "options": [{"id": "optLow", "name": "缺货"}, {"id": "optTr", "name": "在途"}]
                },
            },
            {"field_id": "fldOwner", "field_name": "负责人", "type": 11, "ui_type": "User"},
            {"field_id": "fldDate", "field_name": "复核日期", "type": 5, "ui_type": "DateTime"},
            {"field_id": "fldLink", "field_name": "商品链接", "type": 15, "ui_type": "Url"},
            {"field_id": "fldFile", "field_name": "质检报告", "type": 17, "ui_type": "Attachment"},
            {"field_id": "fldOver", "field_name": "是否超标", "type": 7, "ui_type": "Checkbox"},
            # 不可写字段
            {"field_id": "fldCalc", "field_name": "覆盖天数", "type": 20, "ui_type": "Formula"},
            {
                "field_id": "fldCreated",
                "field_name": "创建时间",
                "type": 1001,
                "ui_type": "CreatedTime",
            },
        ],
    }


@pytest.fixture
def field_index(sample_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按field_name 索引的字段表，便于测试里快速查 type。"""
    return {f["field_name"]: f for f in sample_schema["fields"]}
