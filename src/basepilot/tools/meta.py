"""元信息工具 —— 写记录前必须先 describe_table 拿字段类型。

LLM 最常犯的错是「猜字段类型」：看到「创建时间」就传字符串，
看到「负责人」就传名字。describe_table 返回的 type 编号是
coerce_record 的 fields_meta 来源 —— 先 describe 再写，
把 1254062「字段值转换失败」从运行时错误变成调用前可避开的坑。
"""

from __future__ import annotations

from typing import Any

from ..client import BitableClient
from ..schema import type_name


async def describe_table(client: BitableClient, app_token: str, table_id: str) -> dict[str, Any]:
    """获取数据表的字段结构（写记录前必查）。

    返回每个字段的名称、type 编号、可读类型名、是否系统只读。
    用 type 编号做后续 create/update 的字段编码依据，
    不要凭字段名猜类型。

    Args:
        app_token: 多维表格的 app_token（URL 里 /base/ 后面那段）。
        table_id: 数据表 ID（URL 里 &table= 后面那段）。
    """
    fields = await client.list_fields(app_token, table_id)
    from ..schema import SYSTEM_READONLY_TYPES, FieldType

    out = []
    for name, tval in fields.items():
        try:
            ftype = FieldType(tval)
            readonly = ftype in SYSTEM_READONLY_TYPES
        except ValueError:
            readonly = False
        out.append(
            {
                "field_name": name,
                "type": tval,
                "type_name": type_name(tval),
                "system_readonly": readonly,
            }
        )
    return {
        "table_id": table_id,
        "field_count": len(out),
        "fields": out,
        "hint": "写入前用这里的 type 做字段编码；system_readonly=true 的字段不能写",
    }


__all__ = ["describe_table"]
