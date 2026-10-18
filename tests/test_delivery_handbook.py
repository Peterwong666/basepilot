"""gen_delivery_handbook 合集页生成测试（全离线）。

锁五个行为：
1. 合集页包含核心叙事章节，且顺序正确（按 Markdown 标题匹配）
2. 统计数字从 diagnosis 实算，与 discovery_report 口径一致
3. 文档链完整：5 份交付文档全部收录，且 step 连续不跳号
4. 实算/定性/规划三类性质区分在场（不得把规划时间轴写成实算）
5. 无 U+FFFD 乱码
"""

from __future__ import annotations

from basepilot.diagnosis import diagnose_all
from basepilot.scenarios_loader import load_scenarios
from scripts.gen_delivery_handbook import DELIVERY, DOCS, render


def _results():  # type: ignore[no-untyped-def]
    return diagnose_all(load_scenarios())


def _render_default() -> str:
    return render(_results())


def test_handbook_has_core_sections_in_order() -> None:
    """合集页必须包含核心章节标题，且顺序正确。"""
    md = _render_default()
    sections = [
        "## 这份合集是什么",
        "## 五份文档一览",
        "## 交付顺序：五个问题，一条线",
        "## 哪些数字是算出来的，哪些不是",
        "## 五份文档摘要",
        "## 这套方法不承诺什么",
        "## 这些文档怎么维护",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_handbook_numbers_come_from_real_computation() -> None:
    """环节数/可投入数/年省工时必须与 diagnosis 实算一致。"""
    results = _results()
    md = render(results)

    actionable = [d for d in results if d.quadrant.name != "D_REJECT"]
    hours = sum(d.annual_hours_saved for d in actionable)

    assert f"评估环节：**{len(results)} 个**" in md
    assert f"建议投入：**{len(actionable)} 个**" in md
    assert f"明确劝退：**{len(results) - len(actionable)} 个**" in md
    assert f"可落地年省：**{hours:.0f} 小时**" in md


def test_handbook_doc_chain_is_complete_and_ordered() -> None:
    """文档链必须 5 份齐全，step 从 1 连续递增，不漏不跳。"""
    assert len(DOCS) == 5, f"文档链应有 5 份，实际 {len(DOCS)} 份"
    assert [d.step for d in DOCS] == [1, 2, 3, 4, 5], "step 必须连续 1-5，不跳号"

    md = _render_default()
    for d in DOCS:
        assert d.id in md, f"文档 {d.id} 未被收录"
        assert f"[`{d.id}.md`]({d.id}.md)" in md, f"文档 {d.id} 缺少可点击指针"
        assert d.answers in md, f"文档 {d.id} 缺少「回答什么问题」"


def test_handbook_marks_computed_vs_planned_honestly() -> None:
    """必须区分实算 / 定性 / 规划，规划时间轴不得混进实算区。"""
    md = _render_default()

    # 三种性质标签都要在场
    assert "🟢 实算" in md
    assert "🟡 定性" in md
    assert "🟡 规划" in md

    # 时间轴行必须落在「规划」列，不能标成实算
    timeline_row = next(
        (ln for ln in md.splitlines() if "推广时间轴" in ln),
        None,
    )
    assert timeline_row is not None, "时间轴数字未在性质表中列出"
    assert "规划" in timeline_row, f"时间轴被标成了实算：{timeline_row}"
    assert "实算" not in timeline_row, f"时间轴行混入实算标注：{timeline_row}"


def test_handbook_has_honest_limits_section() -> None:
    """必须有「不承诺什么」章节（交付材料说清边界是交付质量的一部分）。"""
    md = _render_default()
    assert "## 这套方法不承诺什么" in md
    limits_pos = md.find("## 这套方法不承诺什么")
    limits_section = md[limits_pos : md.find("---", limits_pos)]
    assert len(limits_section.split("\n- ")) >= 4, "局限条目少于 4 条，不够诚实"


def test_handbook_no_garbled_chars() -> None:
    """合集页不得含 U+FFFD 替换字符（乱码会传染到交付物）。"""
    assert "�" not in _render_default(), "合集页含乱码字符"


def test_handbook_requires_all_source_docs_exist() -> None:
    """引用的五份文档必须真实存在于磁盘（防静默失效）。"""
    for d in DOCS:
        path = DELIVERY / f"{d.id}.md"
        assert path.exists(), f"交付文档缺失：{path}"
        # 摘要行必须能实读（不允许读到空摘要）
        from scripts.gen_delivery_handbook import read_headline

        assert read_headline(d.id).strip(), f"{d.id} 首行摘要为空"
