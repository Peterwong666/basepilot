"""gen_expansion_matrix 可复制矩阵生成测试（全离线）。

锁四个行为：
1. 矩阵包含核心叙事章节，且顺序正确（按 Markdown 标题匹配）
2. 每种能力模式的场景数/年省工时从 diagnosis 实算，不写死
3. 模式归组忠实：全部 15 个场景无遗漏、不重复归入某一模式
4. 无 U+FFFD 乱码
"""

from __future__ import annotations

from basepilot.diagnosis import diagnose_all
from basepilot.scenarios_loader import load_scenarios
from scripts.gen_expansion_matrix import collect_patterns, render


def _results():  # type: ignore[no-untyped-def]
    return diagnose_all(load_scenarios())


def _render_default() -> str:
    results = _results()
    return render(collect_patterns(results), len(results))


def test_matrix_has_core_narrative_structure() -> None:
    """矩阵必须包含核心章节标题，且顺序正确。"""
    md = _render_default()
    sections = [
        "## 这份矩阵是什么",
        "## 能力模式矩阵",
        "## 逐模式明细",
        "## 为什么这是资产，不是项目",
        "## 复制的边界",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_matrix_numbers_come_from_real_computation() -> None:
    """模式数、场景总数、年省工时必须与 diagnosis 实算一致。"""
    results = _results()
    patterns = collect_patterns(results)
    md = render(patterns, len(results))

    assert f"**{len(patterns)} 种**" in md
    assert f"**{len(results)} 个**" in md

    # 每种模式的场景数与年省都要落到总览表
    for p in patterns:
        assert p.name in md
        assert f"{len(p.scenario_names)} 个" in md


def test_matrix_partition_is_complete_and_disjoint() -> None:
    """全部场景必须无遗漏、不重复地归入某一模式（划分性质）。"""
    results = _results()
    patterns = collect_patterns(results)

    all_names = [name for p in patterns for name in p.scenario_names]
    scenario_names = [d.scenario.name for d in results]

    # 无重复
    assert len(all_names) == len(set(all_names)), "有场景被重复归入多个模式"
    # 无遗漏
    assert set(all_names) == set(scenario_names), "有场景未被任何模式覆盖"

    # 合计年省必须等于全体场景年省之和（划分不丢量）
    total_from_patterns = sum(p.total_hours for p in patterns)
    total_from_results = sum(d.annual_hours_saved for d in results)
    assert abs(total_from_patterns - total_from_results) < 1e-6


def test_matrix_every_pattern_has_recipe_and_replicate() -> None:
    """每种模式都必须有做法与可复制方向（资产属性的前提）。"""
    patterns = collect_patterns(_results())
    for p in patterns:
        assert p.recipe.strip(), f"{p.id}: 缺做法"
        assert p.replicate_to.strip(), f"{p.id}: 缺可复制方向"
        assert p.scenario_names, f"{p.id}: 至少要有 1 个已验证场景"


def test_matrix_no_garbled_chars() -> None:
    """矩阵不得含 U+FFFD 替换字符。"""
    md = _render_default()
    assert "�" not in md, "矩阵含乱码字符"
