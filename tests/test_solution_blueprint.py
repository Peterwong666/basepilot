"""gen_solution_blueprint 方案蓝图生成测试（全离线）。

锁四个行为：
1. 蓝图包含客户/技术双方签字所需的核心章节，且顺序正确
2. 所有数字（指数/年省工时/表字段数）来自 diagnosis + 场景包实算，不写死
3. 「为什么没 AI」的立场段必须存在 —— top 环节全是 A 象限时，
   不解释就会被误读成「能力不足」，解释后才成为方法论证据
4. 表映射忠实：每个覆盖环节都锚定到真实建好的数据表（或如实标「待建」）
5. 交付物不含真实 table_id（租户身份标识不进公开文档）
"""

from __future__ import annotations

import re

from basepilot.diagnosis import Quadrant, diagnose_all
from basepilot.scenarios_loader import load_scenarios
from scripts.gen_solution_blueprint import SCENARIO_TABLE_MAP, TOP_N, render


def _render_default() -> str:
    return render(diagnose_all(load_scenarios()))


def _actionable(results: list) -> list:  # type: ignore[type-arg]
    return [d for d in results if d.quadrant is not Quadrant.D_REJECT]


def test_blueprint_has_core_narrative_structure() -> None:
    """蓝图必须包含签字所需的核心章节，且顺序正确。"""
    md = _render_default()
    sections = [
        "这份蓝图是什么",
        "覆盖环节总览",
        "逐环节方案",
        "落地顺序与节奏",
        "风险与边界",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_blueprint_numbers_come_from_real_computation() -> None:
    """蓝图里的指数/年省工时必须与 diagnosis 实算一致（不写死）。"""
    results = diagnose_all(load_scenarios())
    md = render(results)
    top = _actionable(results)[:TOP_N]

    total_saved = sum(d.annual_hours_saved for d in top)
    assert f"合计年省：**{total_saved:.0f} 小时**" in md

    for d in top:
        # 每个 top 环节的指数与年省都要出现在总览表里
        assert d.scenario.name in md
        assert f"{d.score:.0f}" in md
        assert f"{d.annual_hours_saved:.0f} h" in md


def test_blueprint_explains_why_no_ai() -> None:
    """「为什么没 AI」立场段必须在场 —— 这是把疑点转成方法论证据的关键。"""
    md = _render_default()
    assert "为什么这份蓝图里几乎没有「AI」" in md
    # 立场核心：A 象限上 AI 是浪费，先把规则搬运做扎实
    assert "上 AI 反而是浪费预算" in md
    assert "先把规则的搬运做扎实" in md


def test_blueprint_table_mapping_is_faithful() -> None:
    """每个覆盖环节都锚定到真实数据表；映射表里的场景名必须真实存在。"""
    results = diagnose_all(load_scenarios())
    md = render(results)
    top = _actionable(results)[:TOP_N]

    # 映射表里引用的场景名，必须能在场景清单里找到（防止映射写到不存在的场景）
    known_names = {d.scenario.name for d in results}
    for name in SCENARIO_TABLE_MAP:
        assert name in known_names, f"SCENARIO_TABLE_MAP 引用了不存在的场景：{name}"

    # top 环节若命中映射，表名要落到蓝图里
    # 注：蓝图刻意不写 table_id（租户标识，不进公开交付物）
    for d in top:
        tbl_name, _ = SCENARIO_TABLE_MAP.get(d.scenario.name, ("（待建）", []))
        assert tbl_name in md


def test_blueprint_no_garbled_chars() -> None:
    """蓝图不得含 U+FFFD 替换字符（yaml 源乱码会传染到交付物）。"""
    md = _render_default()
    assert "�" not in md, "蓝图含乱码字符 —— 检查 scenarios.yaml 的编码"


def test_blueprint_contains_no_real_table_id() -> None:
    """交付文档不得含真实 table_id —— 那是租户身份标识，且对读者无信息价值。

    回归防护：早期版本的蓝图在「数据表」后附了真实 table_id，
    使公开仓库暴露了「这个企业租户里有这么一张表」。
    """
    md = _render_default()
    assert not re.search(r"\btbl[A-Za-z0-9]{12,}\b", md), (
        "蓝图含真实 table_id —— 交付物只写表名，ID 由客户端从环境变量读"
    )
