"""字段编码黄金测试集 —— 覆盖全部易错类型与边界。

**这 61 条用例是 README 里「字段编码正确率 100%」的可复现依据。**
每条用例都对应飞书官方的一个真实格式要求或错误码，
不是凑数。新增编码器时，必须同步新增黄金用例。
"""

from __future__ import annotations

import pytest

from basepilot.coerce import CoerceError, coerce_record, coerce_value

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_text_basic() -> None:
    # 写入时文本字段是纯字符串（富文本数组是读取结构，写入会报 1254060）
    assert coerce_value("标题", 1, "断货预警") == "断货预警"


def test_text_none_returns_empty() -> None:
    assert coerce_value("备注", 1, None) == ""


def test_text_number_coerced_to_string() -> None:
    assert coerce_value("单号", 1, 12345) == "12345"


# ---------------------------------------------------------------------------
# Number
# ---------------------------------------------------------------------------


def test_number_int() -> None:
    assert coerce_value("库存", 2, 42) == 42.0


def test_number_float() -> None:
    assert coerce_value("ACOS", 2, 0.35) == 0.35


def test_number_string_numeric() -> None:
    assert coerce_value("花费", 2, "128.5") == 128.5


def test_number_rejects_bool() -> None:
    with pytest.raises(CoerceError):
        coerce_value("开关", 2, True)


def test_number_rejects_garbage() -> None:
    with pytest.raises(CoerceError):
        coerce_value("金额", 2, "abc")


# ---------------------------------------------------------------------------
# SingleSelect —— 最易错：官方要 str 不是数组（1254062）
# ---------------------------------------------------------------------------


def test_single_select_string() -> None:
    assert coerce_value("状态", 3, "正常") == "正常"


def test_single_select_single_element_array() -> None:
    assert coerce_value("状态", 3, ["正常"]) == "正常"


def test_single_select_rejects_multi_array() -> None:
    with pytest.raises(CoerceError, match="不是数组"):
        coerce_value("状态", 3, ["正常", "异常"])


def test_single_select_rejects_empty() -> None:
    with pytest.raises(CoerceError):
        coerce_value("状态", 3, "  ")


# ---------------------------------------------------------------------------
# MultiSelect —— 要字符串数组（1254062）
# ---------------------------------------------------------------------------


def test_multi_select_array() -> None:
    assert coerce_value("标签", 4, ["A", "B"]) == ["A", "B"]


def test_multi_select_single_string_wrapped() -> None:
    assert coerce_value("标签", 4, "A") == ["A"]


def test_multi_select_rejects_non_string_elements() -> None:
    with pytest.raises(CoerceError):
        coerce_value("标签", 4, [1, 2])


# ---------------------------------------------------------------------------
# DateTime —— 13 位毫秒（1254064），最易错
# ---------------------------------------------------------------------------


def test_datetime_13digit_ms_int() -> None:
    assert coerce_value("创建时间", 5, 1674206443000) == 1674206443000


def test_datetime_10digit_seconds_auto_x1000() -> None:
    assert coerce_value("时间", 5, 1674206443) == 1674206443000


def test_datetime_13digit_string() -> None:
    assert coerce_value("时间", 5, "1674206443000") == 1674206443000


def test_datetime_10digit_string() -> None:
    assert coerce_value("时间", 5, "1674206443") == 1674206443000


def test_datetime_iso_date_string() -> None:
    # "2023-01-20" 当日 00:00 的毫秒
    result = coerce_value("日期", 5, "2023-01-20")
    assert isinstance(result, int)
    assert 1_000_000_000_000 <= result <= 9_999_999_999_999


def test_datetime_iso_datetime_string() -> None:
    result = coerce_value("时间", 5, "2023-01-20T08:00:00")
    assert isinstance(result, int)


def test_datetime_rejects_seconds_out_of_range() -> None:
    with pytest.raises(CoerceError, match="13 位毫秒"):
        coerce_value("时间", 5, 123)


def test_datetime_rejects_garbage_string() -> None:
    with pytest.raises(CoerceError):
        coerce_value("时间", 5, "not-a-date")


# ---------------------------------------------------------------------------
# Checkbox
# ---------------------------------------------------------------------------


def test_checkbox_true() -> None:
    assert coerce_value("已处理", 7, True) is True


def test_checkbox_false() -> None:
    assert coerce_value("已处理", 7, False) is False


def test_checkbox_string_true() -> None:
    assert coerce_value("已处理", 7, "true") is True


def test_checkbox_string_yes() -> None:
    assert coerce_value("已处理", 7, "yes") is True


def test_checkbox_int_one() -> None:
    assert coerce_value("已处理", 7, 1) is True


def test_checkbox_int_zero() -> None:
    assert coerce_value("已处理", 7, 0) is False


def test_checkbox_rejects_garbage() -> None:
    with pytest.raises(CoerceError):
        coerce_value("已处理", 7, "maybe")


# ---------------------------------------------------------------------------
# User —— [{"id": "ou_xxx"}]（1254066）
# ---------------------------------------------------------------------------


def test_user_string_open_id() -> None:
    assert coerce_value("负责人", 11, "ou_abc123") == [{"id": "ou_abc123"}]


def test_user_dict() -> None:
    assert coerce_value("负责人", 11, {"id": "ou_abc123"}) == [{"id": "ou_abc123"}]


def test_user_list_of_strings() -> None:
    assert coerce_value("协作人", 11, ["ou_a", "ou_b"]) == [{"id": "ou_a"}, {"id": "ou_b"}]


def test_user_rejects_non_ou_prefix() -> None:
    with pytest.raises(CoerceError, match="ou_"):
        coerce_value("负责人", 11, "user_123")


def test_user_rejects_number() -> None:
    with pytest.raises(CoerceError):
        coerce_value("负责人", 11, 12345)


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------


def test_phone_string() -> None:
    assert coerce_value("手机", 13, "13800138000") == "13800138000"


def test_phone_int_coerced() -> None:
    assert coerce_value("手机", 13, 13800138000) == "13800138000"


# ---------------------------------------------------------------------------
# Url —— {"link","text"}（1254062）
# ---------------------------------------------------------------------------


def test_url_string_auto_text() -> None:
    result = coerce_value("链接", 15, "https://example.com")
    assert result == {"link": "https://example.com", "text": "https://example.com"}


def test_url_dict() -> None:
    result = coerce_value("链接", 15, {"link": "https://a.com", "text": "A站"})
    assert result == {"link": "https://a.com", "text": "A站"}


def test_url_dict_no_text_defaults_to_link() -> None:
    result = coerce_value("链接", 15, {"link": "https://a.com"})
    assert result["text"] == "https://a.com"


def test_url_rejects_non_http_string() -> None:
    with pytest.raises(CoerceError):
        coerce_value("链接", 15, "example.com")


# ---------------------------------------------------------------------------
# Attachment —— [{"file_token"}]，两阶段写入
# ---------------------------------------------------------------------------


def test_attachment_string_token() -> None:
    assert coerce_value("附件", 17, "tok_abc") == [{"file_token": "tok_abc"}]


def test_attachment_dict() -> None:
    assert coerce_value("附件", 17, {"file_token": "tok_abc"}) == [{"file_token": "tok_abc"}]


def test_attachment_list() -> None:
    assert coerce_value("附件", 17, ["tok_a", "tok_b"]) == [
        {"file_token": "tok_a"},
        {"file_token": "tok_b"},
    ]


def test_attachment_rejects_local_path() -> None:
    with pytest.raises(CoerceError):
        coerce_value("附件", 17, {"path": "/some/dir/x.pdf"})


# ---------------------------------------------------------------------------
# 关联字段（18/21）—— record_id 字符串数组（1254074）
# ---------------------------------------------------------------------------


def test_single_link_string_wrapped() -> None:
    assert coerce_value("关联订单", 18, "recXXXX") == ["recXXXX"]


def test_single_link_array() -> None:
    assert coerce_value("关联订单", 18, ["recA", "recB"]) == ["recA", "recB"]


def test_duplex_link_array() -> None:
    assert coerce_value("双向关联", 21, ["recA"]) == ["recA"]


def test_link_rejects_non_string() -> None:
    with pytest.raises(CoerceError):
        coerce_value("关联", 18, [123])


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_location_string_wrapped() -> None:
    result = coerce_value("地址", 22, "深圳市南山区")
    assert result == {"location": "深圳市南山区", "pname": "深圳市南山区"}


def test_location_dict_passthrough() -> None:
    result = coerce_value("地址", 22, {"location": "深圳", "pname": "深圳"})
    assert result["location"] == "深圳"


# ---------------------------------------------------------------------------
# 系统只读字段 —— fail-fast（核心安全设计）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_value,name",
    [
        (19, "查找引用"),
        (20, "公式"),
        (1001, "创建时间"),
        (1002, "修改时间"),
        (1003, "创建人"),
        (1004, "修改人"),
        (1005, "自动编号"),
    ],
)
def test_system_readonly_fields_rejected(type_value: int, name: str) -> None:
    with pytest.raises(CoerceError, match="系统维护字段"):
        coerce_value(name, type_value, "anything")


# ---------------------------------------------------------------------------
# 未知类型 —— 保守原样返回
# ---------------------------------------------------------------------------


def test_unknown_type_passthrough() -> None:
    assert coerce_value("神秘字段", 9999, "whatever") == "whatever"


# ---------------------------------------------------------------------------
# coerce_record —— 批量编码 + 未知字段保留
# ---------------------------------------------------------------------------


def test_coerce_record_uses_schema() -> None:
    meta = {"状态": 3, "创建时间": 5, "负责人": 11}
    record = {"状态": "正常", "创建时间": 1674206443, "负责人": "ou_x"}
    out = coerce_record(meta, record)
    assert out["状态"] == "正常"
    assert out["创建时间"] == 1674206443000
    assert out["负责人"] == [{"id": "ou_x"}]


def test_coerce_record_unknown_field_passthrough() -> None:
    out = coerce_record({"状态": 3}, {"状态": "正常", "未知字段": "raw"})
    assert out["未知字段"] == "raw"


def test_coerce_record_readonly_field_fails_fast() -> None:
    meta = {"公式字段": 20}
    with pytest.raises(CoerceError, match="系统维护字段"):
        coerce_record(meta, {"公式字段": "x"})


# ---------------------------------------------------------------------------
# 错误信息质量 —— 必须可执行，不是只喊"错了"
# ---------------------------------------------------------------------------


def test_error_message_contains_field_and_format() -> None:
    with pytest.raises(CoerceError) as exc_info:
        coerce_value("交付日期", 5, "2023年1月")
    msg = str(exc_info.value)
    assert "交付日期" in msg
    assert "1254064" in msg
    assert "13 位毫秒" in msg or "正确格式" in msg
