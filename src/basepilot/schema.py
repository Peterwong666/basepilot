"""多维表格字段类型枚举与不可写字段白名单。

**type 编号与含义全部来自飞书开放平台官方字段说明**，未做任何推测。
来源：官方文档「开发指南 > 多维表格 > 字段 > 字段概述」的 type/ui_type 对照表。

这是整个适配层的地基：coerce 的编码器、schema 的白名单、
诊断报告的字段覆盖度，全部依赖这份枚举与官方保持一致。
"""

from __future__ import annotations

from enum import IntEnum


class FieldType(IntEnum):
    """多维表格字段 type 编号（官方定义）。"""

    TEXT = 1
    NUMBER = 2
    SINGLE_SELECT = 3
    MULTI_SELECT = 4
    DATETIME = 5
    CHECKBOX = 7
    USER = 11
    PHONE = 13
    URL = 15
    ATTACHMENT = 17
    SINGLE_LINK = 18
    LOOKUP = 19
    FORMULA = 20
    DUPLEX_LINK = 21
    LOCATION = 22
    GROUP_CHAT = 23
    CREATED_TIME = 1001
    MODIFIED_TIME = 1002
    CREATED_USER = 1003
    MODIFIED_USER = 1004
    AUTO_NUMBER = 1005
    BARCODE = 3001
    PROGRESS = 3002
    CURRENCY = 3003
    RATING = 3004
    EMAIL = 3005


#: 系统维护字段 —— 官方明确**不能通过 API 写入**。
#:
#: 依据：官方字段概述中，公式、查找引用、创建/修改时间、创建/修改人、
#: 自动编号均为系统维护。写入这类字段会报 1254062 系列的「字段值转换失败」
#: 或更隐蔽地被静默忽略。这里做成白名单，写入前 fail-fast，
#: 把「为什么写不进去」从飞书侧的运行时错误，提前到调用侧的明确异常。
SYSTEM_READONLY_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.LOOKUP,
        FieldType.FORMULA,
        FieldType.CREATED_TIME,
        FieldType.MODIFIED_TIME,
        FieldType.CREATED_USER,
        FieldType.MODIFIED_USER,
        FieldType.AUTO_NUMBER,
    }
)

#: 关联类字段：值为 record_id 的字符串数组。
LINK_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.SINGLE_LINK,
        FieldType.DUPLEX_LINK,
    }
)

#: 人员类字段：值为 [{"id": "ou_xxx"}]。
USER_TYPES: frozenset[FieldType] = frozenset({FieldType.USER})

#: 附件类字段：值为 [{"file_token": "..."}]，需先上传拿 file_token。
ATTACHMENT_TYPES: frozenset[FieldType] = frozenset({FieldType.ATTACHMENT})

#: 日期类字段：13 位毫秒时间戳。
DATETIME_TYPES: frozenset[FieldType] = frozenset({FieldType.DATETIME})


def type_name(type_value: int) -> str:
    """把 type 编号翻译成可读名称，查不到就返回原始编号。

    用于错误信息，让 1254062 这类「字段值转换失败」能定位到具体字段类型。
    """
    try:
        return FieldType(type_value).name
    except ValueError:
        return f"UNKNOWN({type_value})"
