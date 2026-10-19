"""错误码处置规则的表驱动测试。

验收标准：≥30 个错误码，每个都有明确处置与现场指引。
本测试同时充当 `docs/delivery/troubleshooting.md` 的数据来源校验 ——
文档里的每条指引都必须在这里被断言过。
"""

from __future__ import annotations

import pytest

from basepilot.errors import RULES, Action, ErrorRule, FeishuAPIError, coverage, lookup

# README / 证据卡承诺的数量下限
MIN_RULES = 30


def test_at_least_min_rules() -> None:
    """规则数量达标（README 证据卡承诺 ≥30）。"""
    assert len(RULES) >= MIN_RULES, f"仅 {len(RULES)} 条规则，低于承诺的 {MIN_RULES}"


def test_coverage_report_consistent() -> None:
    cov = coverage()
    assert cov["total_rules"] == len(RULES)
    assert cov["all_rules_have_guidance"], "存在没有现场指引的错误码"
    assert cov["all_rules_have_keywords"], "存在没有断言关键词的错误码"
    assert set(cov["by_action"]) <= {a.value for a in Action}


@pytest.mark.parametrize("code", sorted(RULES))
def test_every_rule_has_action_and_guidance(code: int) -> None:
    """每条规则都有合法处置与非空指引。"""
    rule = lookup(code)
    assert rule is not None
    assert isinstance(rule.action, Action)
    assert rule.guidance.strip(), f"{code} 缺少现场指引"
    assert rule.keywords, f"{code} 缺少断言关键词"
    assert rule.title.strip(), f"{code} 缺少标题"


@pytest.mark.parametrize(
    ("code", "expected_action"),
    [
        (1254290, Action.RETRY),
        (1254291, Action.RETRY),
        (1254607, Action.RETRY),
        (1255040, Action.RETRY),
        (1254036, Action.LONG_BACKOFF),
        (1255006, Action.REGEN_IDEMPOTENCY),
        (1254608, Action.REGEN_IDEMPOTENCY),
        (1254302, Action.FAIL_FAST),
        (1254003, Action.FAIL_FAST),
        (1254045, Action.FAIL_FAST),
        (1254064, Action.FAIL_FAST),
        (1254066, Action.FAIL_FAST),
    ],
)
def test_action_classification(code: int, expected_action: Action) -> None:
    """关键错误码的处置分类必须正确 —— 分类错了会导致现场卡死。"""
    assert lookup(code).action is expected_action


@pytest.mark.parametrize("code", sorted(RULES))
def test_error_message_contains_all_keywords(code: int) -> None:
    """异常消息里必须包含全部断言关键词（排障 SOP 的可检索性保障）。"""
    err = FeishuAPIError(code, msg="raw message")
    text = err.message()
    for kw in RULES[code].keywords:
        assert kw in text, f"{code} 的提示缺少关键词「{kw}」"


def test_permission_error_gives_actionable_steps() -> None:
    """权限类错误必须给出「添加文档应用」这个可操作指引。"""
    err = FeishuAPIError(1254302)
    assert "添加文档应用" in err.message()
    assert err.should_retry() is False, "权限问题重试无意义"


def test_datetime_error_explains_milliseconds() -> None:
    """日期错误必须说清是13 位毫秒 —— 这是最常踩的坑。"""
    msg = FeishuAPIError(1254064).message()
    assert "毫秒" in msg
    assert "1674206443000" in msg, "最好给一个具体例子，避免对方继续传秒级"


def test_user_field_error_explains_array_object_format() -> None:
    """人员字段错误必须给出正确格式与清空方式。"""
    msg = FeishuAPIError(1254066).message()
    assert "ou_xxx" in msg
    assert "数组" in msg or "id" in msg
    assert "null" in msg, "应说明传 null 可清空"


def test_long_backoff_schedule_is_longer_than_normal() -> None:
    """副本复制中要长退避，不能和普通限流用同一个序列。"""
    err = FeishuAPIError(1254036)
    schedule = err.backoff_schedule()
    assert len(schedule) >= 3
    assert max(schedule) >= 12.0


def test_regen_idempotency_generates_uuid4() -> None:
    """幂等键冲突时生成合规的 uuid4。"""
    err = FeishuAPIError(1255006)
    assert err.needs_new_idempotency_key() is True
    key = err.new_idempotency_key()
    assert len(key) == 36
    assert key.count("-") == 4


def test_unknown_code_defaults_to_retry_but_keeps_raw_msg() -> None:
    """未登记的错误码：保守重试，但保留飞书原始信息，不能吞掉细节。"""
    err = FeishuAPIError(999999, msg="something unusual")
    assert err.action is Action.RETRY
    assert "999999" in err.message()
    assert "something unusual" in err.message()


def test_fail_fast_errors_do_not_ask_for_retry() -> None:
    """所有 fail_fast 类错误都不应建议重试。"""
    for code, rule in RULES.items():
        if rule.action is Action.FAIL_FAST:
            assert not FeishuAPIError(code).should_retry(), f"{code} 不应重试"


def test_no_duplicate_action_semantics() -> None:
    """同一处置类别里，LONG_BACKOFF 必须提供退避序列。"""
    for code, rule in RULES.items():
        if rule.action is Action.LONG_BACKOFF:
            assert FeishuAPIError(code).backoff_schedule(), f"{code} 缺退避序列"


def test_rules_are_immutable() -> None:
    """规则是 frozen 的，防止运行中被意外改写（会导致排障指引失真）。"""
    import dataclasses

    rule: ErrorRule = RULES[1254302]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.guidance = "被改了"  # type: ignore[misc]
