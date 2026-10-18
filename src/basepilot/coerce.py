"""字段编码适配层 —— 把"LLM 友好的输入"转成"飞书要求的格式"。

设计原则：**入口宽容，出口严格。**

LLM（或人类）调用工具时，传 ISO 日期、秒级时间戳、单元素数组、
字符串形式的布尔值都很自然。这些"不那么严格"的输入，
由适配层统一规范化成飞书官方要求的格式，而不是把 1254062
「字段值转换失败」抛给客户。

反过来，对**不可写字段**（公式/系统字段）与**无法安全推断**的输入，
适配层 fail-fast 并给出可执行的修复指引，而不是静默吞掉或猜一个值。

每个编码器都标注了对应的官方错误码，错误信息里直接告诉客户
「这个字段该传什么」，而不是只说"错了"。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .schema import (
    ATTACHMENT_TYPES,
    DATETIME_TYPES,
    LINK_TYPES,
    SYSTEM_READONLY_TYPES,
    USER_TYPES,
    FieldType,
    type_name,
)


class CoerceError(ValueError):
    """字段编码失败。

    message 必须是**客户可执行**的指引，包含：字段名、字段类型、
    你传了什么、正确格式是什么。对应官方 125406X 系列错误码。
    """


def _fail(field: str, ftype: FieldType, got: Any, want: str, code: str) -> CoerceError:
    return CoerceError(
        f"字段「{field}」(type={ftype.value} {ftype.name}) 编码失败："
        f"收到 {got!r}（{type(got).__name__}）。"
        f"正确格式：{want}。"
        f"（对应飞书错误码 {code}，详见 docs/delivery/troubleshooting.md）"
    )


# ---------------------------------------------------------------------------
# 标量编码器
# ---------------------------------------------------------------------------


def coerce_text(field: str, ftype: FieldType, value: Any) -> list[dict[str, Any]]:
    """Text(type=1)：[{"type":"text","text":"..."}]。官方要求富文本数组结构。

    field/ftype 参数保留是为了让所有编码器签名一致（便于表驱动分发）。
    """
    del field, ftype  # 签名一致性占位
    if value is None:
        return []
    text = value if isinstance(value, str) else str(value)
    return [{"type": "text", "text": text}]


def coerce_number(field: str, ftype: FieldType, value: Any) -> float:
    """Number(type=2)：数值。拒绝 bool（Python 里 bool 是 int 子类）。"""
    if isinstance(value, bool):
        raise _fail(field, ftype, value, "数值，如 42 或 3.14", "1254062")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s:
            try:
                return float(s)
            except ValueError:
                pass
    raise _fail(field, ftype, value, "数值，如 42 或 3.14", "1254062")


def coerce_single_select(field: str, ftype: FieldType, value: Any) -> str:
    """SingleSelect(type=3)：字符串选项名。

    ⚠️ 最易错点：官方要求 **str**，不是数组（错误码 1254062 明确标注）。
    入口宽容：如果 LLM 传了单元素数组，取第一个元素。
    """
    if isinstance(value, str):
        if value.strip():
            return value
        raise _fail(field, ftype, value, "非空选项名字符串", "1254062")
    if isinstance(value, (list, tuple)):
        if len(value) == 1 and isinstance(value[0], str):
            return value[0]
        raise _fail(
            field,
            ftype,
            value,
            "单个选项名字符串（不是数组），如 \"正常\"",
            "1254062",
        )
    raise _fail(field, ftype, value, "选项名字符串，如 \"正常\"", "1254062")


def coerce_multi_select(field: str, ftype: FieldType, value: Any) -> list[str]:
    """MultiSelect(type=4)：字符串数组。入口宽容：单字符串包成数组。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        if all(isinstance(v, str) for v in value):
            return list(value)
        raise _fail(field, ftype, value, "字符串数组，如 [\"A\", \"B\"]", "1254062")
    raise _fail(field, ftype, value, "字符串数组，如 [\"A\", \"B\"]", "1254062")


_MS_RE = re.compile(r"^\d{13}$")
_S_RE = re.compile(r"^\d{10}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def coerce_datetime(field: str, ftype: FieldType, value: Any) -> int:
    """DateTime(type=5)：**13 位毫秒时间戳**（错误码 1254064 明确）。

    入口宽容，接受：
    - 13 位毫秒时间戳（int / 数字字符串）——原样通过
    - 10 位秒级时间戳（int / 数字字符串）——自动 ×1000
    - ISO 日期字符串 "YYYY-MM-DD" —— 转当日 00:00 的毫秒
    - datetime / date 对象 —— 转毫秒

    出口严格：拒绝无法安全推断的输入，绝不返回秒级或字符串。
    """
    # 数值/数字字符串：判断位数
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        if 1_000_000_000_000 <= n <= 9_999_999_999_999:
            return n  # 13 位毫秒
        if 1_000_000_000 <= n <= 9_999_999_999:
            return n * 1000  # 10 位秒 → 毫秒
        raise _fail(
            field,
            ftype,
            value,
            "13 位毫秒时间戳（如 1674206443000）",
            "1254064",
        )
    if isinstance(value, str):
        s = value.strip()
        if _MS_RE.match(s):
            return int(s)
        if _S_RE.match(s):
            return int(s) * 1000
        if _ISO_DATE_RE.match(s):
            dt = datetime.fromisoformat(s)
            return int(dt.timestamp() * 1000)
        # 尝试完整 ISO datetime
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
        raise _fail(
            field,
            ftype,
            value,
            "13 位毫秒时间戳或 ISO 日期，如 1674206443000 或 \"2026-10-18\"",
            "1254064",
        )
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day).timestamp() * 1000)
    raise _fail(field, ftype, value, "13 位毫秒时间戳", "1254064")


def coerce_checkbox(field: str, ftype: FieldType, value: Any) -> bool:
    """Checkbox(type=7)：bool。入口宽容：识别常见字符串/数值形式。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "是", "✓", "checked"):
            return True
        if s in ("false", "0", "no", "n", "否", "", "unchecked"):
            return False
    raise _fail(field, ftype, value, "布尔值 true/false", "1254062")


def coerce_user(field: str, ftype: FieldType, value: Any) -> list[dict[str, str]]:
    """User(type=11)：[{"id": "ou_xxx"}]。错误码 1254066 明确数组对象结构。

    入口宽容：接受单个 open_id 字符串、单个 dict、或它们的列表。
    出口严格：id 必须以 ou_ 开头（open_id 格式），否则 fail-fast。
    """
    items: list[Any]
    if isinstance(value, (str, dict)):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise _fail(field, ftype, value, "[{\"id\": \"ou_xxx\"}]", "1254066")

    out: list[dict[str, str]] = []
    for it in items:
        if isinstance(it, str):
            uid = it
        elif isinstance(it, dict) and "id" in it:
            uid = str(it["id"])
        else:
            raise _fail(field, ftype, value, "[{\"id\": \"ou_xxx\"}]", "1254066")
        if not uid.startswith("ou_"):
            raise _fail(
                field,
                ftype,
                value,
                "open_id 必须以 ou_ 开头，如 ou_xxxxxxxxx",
                "1254066",
            )
        out.append({"id": uid})
    return out


def coerce_phone(field: str, ftype: FieldType, value: Any) -> str:
    """Phone(type=13)：字符串手机号。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 手机号常被 Excel 读成数字，转回字符串（去小数点）
        return str(int(value))
    raise _fail(field, ftype, value, "手机号字符串，如 \"13800138000\"", "1254062")


def coerce_url(field: str, ftype: FieldType, value: Any) -> dict[str, str]:
    """Url(type=15)：{"link": "...", "text": "..."}。

    入口宽容：单字符串自动补 text=link。
    """
    if isinstance(value, str):
        s = value.strip()
        if s.startswith(("http://", "https://")):
            return {"link": s, "text": s}
        raise _fail(
            field,
            ftype,
            value,
            "{\"link\": \"https://...\", \"text\": \"显示文本\"}",
            "1254062",
        )
    if isinstance(value, dict) and "link" in value:
        link = str(value["link"])
        text = str(value.get("text", link))
        return {"link": link, "text": text}
    raise _fail(field, ftype, value, "{\"link\": \"...\", \"text\": \"...\"}", "1254062")


def coerce_attachment(field: str, ftype: FieldType, value: Any) -> list[dict[str, str]]:
    """Attachment(type=17)：[{"file_token": "..."}]。

    ⚠️ 两阶段写入：必须先调上传接口拿 file_token，再写记录。
    这里只做格式适配，不负责上传（上传在 client 层）。
    入口宽容：接受单个 file_token 字符串、单个 dict、或列表。
    """
    items: list[Any]
    if isinstance(value, (str, dict)):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise _fail(field, ftype, value, "[{\"file_token\": \"...\"}]", "1254062")

    out: list[dict[str, str]] = []
    for it in items:
        if isinstance(it, str):
            token = it
        elif isinstance(it, dict) and "file_token" in it:
            token = str(it["file_token"])
        else:
            raise _fail(field, ftype, value, "[{\"file_token\": \"...\"}]", "1254062")
        if not token:
            raise _fail(field, ftype, value, "非空 file_token", "1254062")
        out.append({"file_token": token})
    return out


def coerce_link(field: str, ftype: FieldType, value: Any) -> list[str]:
    """关联字段（18/21）：record_id 的字符串数组。错误码 1254074 明确。

    入口宽容：单个 record_id 字符串包成数组。
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return list(value)
    raise _fail(
        field,
        ftype,
        value,
        "record_id 字符串数组，如 [\"recXXXXXXXX\"]",
        "1254074",
      )


def coerce_location(field: str, ftype: FieldType, value: Any) -> dict[str, Any]:
    """Location(type=22)：{"location": "...", "pname": "...", ...}。

    入口宽容：单字符串地址自动包装。
    """
    if isinstance(value, str):
        return {"location": value, "pname": value}
    if isinstance(value, dict) and ("location" in value or "pname" in value):
        return dict(value)
    raise _fail(
        field,
        ftype,
        value,
        "{\"location\": \"地址\", \"pname\": \"地点名\"}",
        "1254062",
      )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def coerce_value(field_name: str, type_value: int, value: Any) -> Any:
    """把任意输入编码为飞书官方格式。

    Args:
        field_name: 字段名（用于错误信息）。
        type_value: 字段 type 编号（来自 field.list）。
        value: 原始输入。

    Returns:
        飞书 API 要求的格式。

    Raises:
        CoerceError: 不可写字段，或无法安全编码。
    """
    try:
        ftype = FieldType(type_value)
    except ValueError:
        # 未知类型：保守起见原样返回，不猜格式
        return value

    if ftype in SYSTEM_READONLY_TYPES:
        raise CoerceError(
            f"字段「{field_name}」(type={ftype.value} {ftype.name}) 是**系统维护字段**，"
            f"不能通过 API 写入。这类字段由飞书自动计算或记录："
            f"公式/查找引用由关联字段推导，创建/修改时间与创建/修改人由系统记录。"
            f"（对应官方说明，详见 docs/delivery/troubleshooting.md）"
        )

    if ftype == FieldType.TEXT:
        return coerce_text(field_name, ftype, value)
    if ftype == FieldType.NUMBER:
        return coerce_number(field_name, ftype, value)
    if ftype == FieldType.SINGLE_SELECT:
        return coerce_single_select(field_name, ftype, value)
    if ftype == FieldType.MULTI_SELECT:
        return coerce_multi_select(field_name, ftype, value)
    if ftype in DATETIME_TYPES:
        return coerce_datetime(field_name, ftype, value)
    if ftype == FieldType.CHECKBOX:
        return coerce_checkbox(field_name, ftype, value)
    if ftype in USER_TYPES:
        return coerce_user(field_name, ftype, value)
    if ftype == FieldType.PHONE:
        return coerce_phone(field_name, ftype, value)
    if ftype == FieldType.URL:
        return coerce_url(field_name, ftype, value)
    if ftype in ATTACHMENT_TYPES:
        return coerce_attachment(field_name, ftype, value)
    if ftype in LINK_TYPES:
        return coerce_link(field_name, ftype, value)
    if ftype == FieldType.LOCATION:
        return coerce_location(field_name, ftype, value)

    # 其余类型（货币/进度/评分/邮箱等）——数值或字符串，原样返回
    return value


def coerce_record(
    fields_meta: dict[str, int], record: dict[str, Any]
) -> dict[str, Any]:
    """按表字段元信息，批量编码一条记录的所有字段。

    Args:
        fields_meta: {字段名: type 编号}，来自 schema/field.list。
        record: {字段名: 原始值}。

    Returns:
        编码后的 {字段名: 飞书格式值}，可直接用于 create/update。
    """
    out: dict[str, Any] = {}
    for name, value in record.items():
        if name not in fields_meta:
            # 未知字段：保留原样，由飞书侧报"字段不存在"
            # 不在这里 fail，因为可能是调用方拼写错误，让飞书报更明确
            out[name] = value
            continue
        out[name] = coerce_value(name, fields_meta[name], value)
    return out


__all__ = [
    "CoerceError",
    "coerce_value",
    "coerce_record",
    "coerce_datetime",
    "coerce_user",
    "coerce_attachment",
    "coerce_single_select",
    "coerce_multi_select",
    "coerce_link",
    "type_name",
]
