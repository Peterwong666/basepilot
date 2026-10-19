"""gen_discovery_report 报告生成测试（全离线）。

锁三个行为：
1. 报告包含核心叙事结构（问题/五维/结论/四象限/劝退/下一步）
2. 所有数字来自 diagnosis 实算（不写死）——改场景后报告自动反映
3. 劝退区如实列出 D 象限（「敢劝退」是咨询底色，不能丢）
"""

from __future__ import annotations

from basepilot.diagnosis import diagnose_all
from basepilot.scenarios_loader import load_scenarios
from scripts.gen_discovery_report import render


def _render_default() -> str:
    return render(diagnose_all(load_scenarios()))


def test_report_has_core_narrative_structure() -> None:
    """报告必须包含客户可读的核心章节，且顺序正确。"""
    md = _render_default()
    sections = [
        "这份报告回答什么问题",
        "我们怎么判断：五个维度",
        "结论：先做什么",
        "四个象限，四种做法",
        "我们不建议做什么",
        "下一步",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_report_numbers_come_from_real_computation() -> None:
    """报告里的关键数字必须与 diagnosis 实算一致（不写死）。"""
    results = diagnose_all(load_scenarios())
    md = render(results)

    total = len(results)
    from basepilot.diagnosis import Quadrant

    rejected = sum(1 for d in results if d.quadrant is Quadrant.D_REJECT)
    actionable = total - rejected

    assert f"{total} 个" in md
    assert f"建议投入：**{actionable} 个**" in md
    assert f"明确劝退：**{rejected} 个**" in md

    # 起步建议必须是优先级第一的可投入场景
    top = next(d for d in results if d.quadrant is not Quadrant.D_REJECT)
    assert top.scenario.name in md


def test_report_reject_section_is_honest() -> None:
    """劝退区必须如实列出 D 象限场景及其理由 —— 「敢劝退」不能丢。"""
    from basepilot.diagnosis import Quadrant

    results = diagnose_all(load_scenarios())
    md = render(results)
    rejected = [d for d in results if d.quadrant is Quadrant.D_REJECT]

    assert rejected, "场景清单里应至少保留一个劝退案例（咨询底色）"
    for d in rejected:
        assert d.scenario.name in md
        assert d.reject_reason in md


def test_report_no_garbled_chars() -> None:
    """报告不得含 U+FFFD 替换字符（yaml 源乱码会传染到交付物）。"""
    md = _render_default()
    assert "�" not in md, "报告含乱码字符 —— 检查 scenarios.yaml 的编码"
