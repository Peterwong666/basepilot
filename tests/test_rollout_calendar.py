"""gen_rollout_calendar 推广日历生成测试（全离线）。

锁四个行为：
1. 日历包含核心叙事章节，且顺序正确（按 Markdown 标题匹配）
2. 能力模式/场景数/年省工时从 diagnosis 实算，不写死
3. 波次顺序忠实「先稳后难」：规则/阈值在 AI 草拟之前，劝退闸贯穿全程
4. 无 U+FFFD 乱码
"""

from __future__ import annotations

from basepilot.diagnosis import diagnose_all
from basepilot.scenarios_loader import load_scenarios
from scripts.gen_expansion_matrix import collect_patterns
from scripts.gen_rollout_calendar import _WAVE_TEMPLATES, render


def _render_default() -> str:
    results = diagnose_all(load_scenarios())
    patterns = collect_patterns(results)
    return render(list(_WAVE_TEMPLATES), patterns, len(results))


def test_calendar_has_core_narrative_structure() -> None:
    """日历必须包含核心章节标题，且顺序正确。"""
    md = _render_default()
    sections = [
        "## 这份日历是什么",
        "## 推广波次总览",
        "## 逐波次明细",
        "## 贯穿每一波的「劝退闸」",
        "## 节奏原则",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_calendar_pattern_numbers_come_from_real_computation() -> None:
    """每种能力模式的场景数必须与 diagnosis 实算一致。"""
    results = diagnose_all(load_scenarios())
    patterns = collect_patterns(results)
    md = render(list(_WAVE_TEMPLATES), patterns, len(results))

    assert f"**{len(patterns)} 种**" in md
    assert f"**{len(_WAVE_TEMPLATES)} 波**" in md

    # 被引用的能力模式，其场景数要落到日历里
    pmap = {p.id: p for p in patterns}
    for w in _WAVE_TEMPLATES:
        if w.pattern_id and w.pattern_id in pmap:
            p = pmap[w.pattern_id]
            assert p.name in md
            assert f"{len(p.scenario_names)} 场景" in md


def test_calendar_orders_stable_before_hard() -> None:
    """波次顺序必须「先稳后难」：规则搬运/阈值预警排在 AI 草拟之前。"""
    order = [w.pattern_id for w in _WAVE_TEMPLATES if w.pattern_id]
    # 规则搬运与阈值预警必须先于 AI 草拟
    assert order.index("rule_pipeline") < order.index("ai_drafting")
    assert order.index("threshold_alert") < order.index("ai_drafting")
    # 波次编号必须递增（0,1,2,3...）
    assert [w.no for w in _WAVE_TEMPLATES] == sorted(w.no for w in _WAVE_TEMPLATES)


def test_calendar_honest_reject_is_gate_not_wave() -> None:
    """「诚实劝退」不作为独立波次，而是贯穿全程的前置闸 —— 文档必须点明。"""
    wave_pattern_ids = {w.pattern_id for w in _WAVE_TEMPLATES}
    assert "honest_reject" not in wave_pattern_ids, "劝退不应该是独立波次"
    md = _render_default()
    assert "劝退闸" in md
    assert "数据源就位吗" in md


def test_calendar_timeline_is_marked_as_template() -> None:
    """时间轴必须显式标注为「规划模板（定性决策）」—— 不伪装成算出来的。"""
    md = _render_default()
    assert "规划模板" in md
    assert "定性决策" in md


def test_calendar_no_garbled_chars() -> None:
    """日历不得含 U+FFFD 替换字符。"""
    md = _render_default()
    assert "�" not in md, "日历含乱码字符"
