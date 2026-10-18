"""原子读写工具 —— create / update / delete / search / batch_upsert。

所有写工具共享同一条调用链（见 client.py）：
字段编码 → 单表串行 + 节流 → 限流 → 鉴权 → 错误处置。

给 LLM 的关键提示都写在 docstring 里：
- 日期是 13 位毫秒，不是秒、不是字符串
- 单选是字符串不是数组
- 系统只读字段（公式/创建时间等）不能写
"""

from __future__ import annotations

from typing import Any

from ..client import BitableClient


async def create_records(
    client: BitableClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """批量新增记录。

    字段值格式（重要，错了会被 1254062 拒）：
    - 文本：字符串
    - 数字：数值
    - 单选：选项名字符串（不是数组），如 "正常"
    - 多选：字符串数组，如 ["A", "B"]
    - 日期：13 位毫秒时间戳，如 1674206443000（秒级会自动×1000）
    - 人员：open_id，如 "ou_xxxx"（自动包装成 [{"id": ...}]）
    - 关联：record_id 数组，如 ["recXXXX"]
    - 系统只读字段（公式/创建时间/创建人等）不能写，写了会被拒

    建议先用 describe_table 拿字段 type，再决定每个字段传什么。

    Args:
        app_token: 多维表格 app_token。
        table_id: 数据表 ID。
        records: 记录列表，每条是 {字段名: 字段值}。超过 1000 条自动分片。
    """
    return await client.create_records(app_token, table_id, records)


async def update_records(
    client: BitableClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """批量更新记录。

    每条必须含 record_id 与 fields，格式：
    [{"record_id": "recXXX", "fields": {"状态": "已处理"}}]
    字段值格式同 create_records。

    Args:
        records: 更新列表，每项 {"record_id": ..., "fields": {...}}。
    """
    return await client.update_records(app_token, table_id, records)


async def delete_records(
    client: BitableClient,
    app_token: str,
    table_id: str,
    record_ids: list[str],
) -> dict[str, Any]:
    """批量删除记录。

    ⚠️ 删除不可恢复。超过 500 条（官方保守值）自动分片。
    建议先 search 确认要删的记录，再删。

    Args:
        record_ids: 要删除的 record_id 列表。
    """
    return await client.delete_records(app_token, table_id, record_ids)


async def search_records(
    client: BitableClient,
    app_token: str,
    table_id: str,
    filter_: dict[str, Any] | None = None,
    field_names: list[str] | None = None,
    page_size: int = 500,
) -> dict[str, Any]:
    """查询记录（自动翻页）。

    Args:
        filter_: 筛选条件（飞书 filter 表达式），如
            {"conjunction": "and", "conditions": [
                {"field_name": "状态", "operator": "is", "value": ["异常"]}
            ]}
        field_names: 只返回这些字段，省流量。
        page_size: 每页条数，最大 500。
    """
    items = await client.search_records(
        app_token,
        table_id,
        filter_=filter_,
        field_names=field_names,
        page_size=page_size,
    )
    return {"count": len(items), "records": items}


async def batch_upsert(
    client: BitableClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
    key_field: str,
) -> dict[str, Any]:
    """按键字段「存在即更新，不存在即新增」。

    跨境电商同步场景的核心操作：按 SKU / 订单号 等唯一键同步，
    避免重复创建。先按 key_field search 出已存在的记录，
    命中的走 update，未命中的走 create。

    Args:
        records: 记录列表，每条是 {字段名: 值}，必须含 key_field。
        key_field: 作为唯一键的字段名，如 "SKU" / "订单号"。
    """
    if not records:
        return {"created": 0, "updated": 0}

    # 收集所有 key 值，一次性查出已存在的
    keys = [str(rec[key_field]) for rec in records if key_field in rec]
    existing: dict[str, str] = {}  # key 值 → record_id
    if keys:
        found = await client.search_records(
            app_token,
            table_id,
            field_names=[key_field],
        )
        for item in found:
            f = item.get("fields", {})
            kv = f.get(key_field)
            # 文本字段返回的是 [{"type":"text","text":...}] 结构
            if isinstance(kv, list) and kv and isinstance(kv[0], dict):
                kv = kv[0].get("text", "")
            if kv is not None:
                existing[str(kv)] = str(item.get("record_id"))

    to_update: list[dict[str, Any]] = []
    to_create: list[dict[str, Any]] = []
    for rec in records:
        if key_field not in rec:
            continue
        kval = str(rec[key_field])
        if kval in existing:
            to_update.append({"record_id": existing[kval], "fields": rec})
        else:
            to_create.append(rec)

    result: dict[str, Any] = {"created": 0, "updated": 0}
    if to_create:
        r = await client.create_records(app_token, table_id, to_create)
        result["created"] = r["created"]
    if to_update:
        r = await client.update_records(app_token, table_id, to_update)
        result["updated"] = r["updated"]
    return result


__all__ = [
    "create_records",
    "update_records",
    "delete_records",
    "search_records",
    "batch_upsert",
]
