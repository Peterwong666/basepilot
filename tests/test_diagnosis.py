"""业务诊断打分器 —— 核心价值不是"打分"，是"敢劝退"。

这里有一个关键指标：`diagnosis_ranking_accuracy`
—— 打分器排序与人工优先级标注的 Spearman 相关性。

它把"我的诊断方法论"从主观主张变成**有准确率数字的东西**。
若这个指标不达标，说明方法论是拍脑袋的，应该老实承认。
"""

from __future__ import annotations

import pytest

from basepilot.diagnosis import (
    DEFAULT_WEIGHTS,
    FUZZY_RULE_THRESHOLD,
    HARD_REJECT,
    THRESHOLD_ASSISTED,
    THRESHOLD_AUTO,
    DiagnosisError,
    Quadrant,
    Scenario,
    diagnose,
    diagnose_all,
    render_json,
    render_markdown,
    render_quadrant_mermaid,
)
from basepilot.scenarios_loader import load_scenarios


@pytest.fixture
def scenarios() -> list[Scenario]:
    return load_scenarios()


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman 秩相关系数（无并列秩的简化实现）。"""
    assert len(xs) == len(ys)
    n = len(xs)

    def rank(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        for pos, idx in enumerate(order, start=1):
            r[idx] = float(pos)
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=False))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


# ---------------------------------------------------------------------------
# 权重与阈值
# ---------------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    """四维权重必须加起来为 1，否则指数失去"百分制"含义。"""
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_frequency_has_highest_weight() -> None:
    """频率是第一维度 —— JD 原话里「高频」排在最前。"""
    top = max(DEFAULT_WEIGHTS, key=lambda k: DEFAULT_WEIGHTS[k])  # noqa: B023
    assert top == "frequency"


def test_weights_must_be_positive_sum() -> None:
    """全零权重应报错而不是静默返回 0。"""
    s = Scenario(
        id="x",
        name="x",
        dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 5),
        human_minutes_per_run=10,
        runs_per_year=100,
        evidence="e",
    )
    with pytest.raises(DiagnosisError, match="权重之和"):
        s.score({"frequency": 0, "rule_clarity": 0, "data_readiness": 0, "fault_tolerance": 0})


# ---------------------------------------------------------------------------
# 单场景诊断
# ---------------------------------------------------------------------------


def test_all_five_scores_is_a_auto() -> None:
    """四维全 5 分 → A 象限（直接自动化）。"""
    s = Scenario(
        id="x",
        name="x",
        dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 5),
        human_minutes_per_run=10,
        runs_per_year=100,
        evidence="e",
    )
    d = diagnose(s)
    assert d.score == pytest.approx(100.0)
    assert d.quadrant is Quadrant.A_AUTO
    assert d.reject_reason is None


def test_all_zero_scores_is_ai_first_not_reject() -> None:
    """全 0 分不等于该劝退 —— 低分只说明 AI 主导，不是"别做"。

    这是刻意的区分：**D 象限必须由明确的 hard_reject 触发**，
    否则「什么都不做的场景」会被误标成「不做」，掩盖了真实判断。
    """
    s = Scenario(
        id="x",
        name="x",
        dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 0),
        human_minutes_per_run=10,
        runs_per_year=100,
        evidence="e",
    )
    d = diagnose(s)
    assert d.quadrant is Quadrant.C_AI_FIRST


def test_hard_reject_overrides_perfect_score() -> None:
    """硬性劝退优先于总分：数据都没有，分再高也不该做。"""
    s = Scenario(
        id="x",
        name="x",
        dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 5),
        human_minutes_per_run=10,
        runs_per_year=100,
        evidence="e",
        hard_reject="no_data",
    )
    d = diagnose(s)
    assert d.score == pytest.approx(100.0)
    assert d.quadrant is Quadrant.D_REJECT
    assert d.reject_reason == HARD_REJECT["no_data"]
    assert d.annual_hours_saved == 0.0, "D 象限不应声称省工时"


def test_b_quadrant_saves_less_than_a() -> None:
    """B 象限（AI 辅助）省的时间必须少于 A 象限（近乎全自动）。

    构造依据：规则明确度 3（高于模糊闸门，放行），
    但「错得起=0 + 避损失=0」把指数压到 58，落在 B 区间。
    """
    a_dims = dict.fromkeys(DEFAULT_WEIGHTS, 5)
    a = Scenario(id="a", name="a", dimensions=a_dims,
                 human_minutes_per_run=60, runs_per_year=365, evidence="e")

    b_dims = dict.fromkeys(DEFAULT_WEIGHTS, 5)
    b_dims["rule_clarity"] = 3
    b_dims["fault_tolerance"] = 0
    b_dims["loss_impact"] = 0
    b = Scenario(id="b", name="b", dimensions=b_dims,
                 human_minutes_per_run=60, runs_per_year=365, evidence="e")

    assert a.quadrant() is Quadrant.A_AUTO
    assert b.quadrant() is Quadrant.B_ASSISTED, f"实际为 {b.quadrant()}"
    # A 折算 0.9 > B 折算 0.6
    assert b.annual_hours_saved() < a.annual_hours_saved()


def test_annual_hours_math() -> None:
    """年省工时 = 分钟/60 × 次数/年 × 象限折算率（A 象限 0.9）。"""
    s = Scenario(id="x", name="x", dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 5),
                 human_minutes_per_run=60, runs_per_year=365, evidence="e")
    # 365 小时 × 0.9（A 象限仍需抽查，不是完全无人）
    assert s.annual_hours_saved() == pytest.approx(365.0 * 0.9)


def test_fuzzy_rules_force_ai_first() -> None:
    """**规则模糊时必须进 C 象限，哪怕加权总分很高。**

    这是本模块最关键的一条设计决策：飞书原生工作流只能做
    「条件明确 → 执行确定动作」的搬运。判据本身模糊的场景
    （如给差评归因），无论指数多高都不可能靠工作流完成。

    若只看加权总分，它会因为「高频 + 有数据」拿到高分，
    误判成「不需要 AI」，逻辑上自相矛盾。
    """
    dims = dict.fromkeys(DEFAULT_WEIGHTS, 5)
    dims["rule_clarity"] = FUZZY_RULE_THRESHOLD  # 模糊规则
    s = Scenario(id="x", name="x", dimensions=dims,
                 human_minutes_per_run=30, runs_per_year=365, evidence="e")
    d = diagnose(s)
    # 指数很高（只扣了规则明确度的分），但仍必须 AI 主导
    assert d.score > THRESHOLD_AUTO, "前提：加权总分仍然很高"
    assert d.quadrant is Quadrant.C_AI_FIRST, "规则模糊不应被判为'不需要 AI'"


def test_clear_rules_above_threshold_is_auto() -> None:
    """对照组：规则明确 + 总分高 → A 象限（工作流即可）。"""
    dims = dict.fromkeys(DEFAULT_WEIGHTS, 5)
    dims["rule_clarity"] = FUZZY_RULE_THRESHOLD + 1
    s = Scenario(id="x", name="x", dimensions=dims,
                 human_minutes_per_run=10, runs_per_year=100, evidence="e")
    assert diagnose(s).quadrant is Quadrant.A_AUTO


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-1, 6, 99])
def test_dimension_must_be_0_to_5(bad: int) -> None:
    """越界分数必须报错，而不是被静默裁剪。"""
    dims = dict.fromkeys(DEFAULT_WEIGHTS, 3)
    dims["frequency"] = bad
    s = Scenario(id="x", name="x", dimensions=dims,
                 human_minutes_per_run=1, runs_per_year=1, evidence="e")
    with pytest.raises(DiagnosisError, match="0-5"):
        s.validate()


def test_unknown_dimension_rejected() -> None:
    """拼错的维度名要报错—— 否则权重查不到会 KeyError。"""
    dims = dict.fromkeys(DEFAULT_WEIGHTS, 3)
    dims["freqency"] = 3  # typo
    s = Scenario(id="x", name="x", dimensions=dims,
                 human_minutes_per_run=1, runs_per_year=1, evidence="e")
    with pytest.raises(DiagnosisError, match="未知维度"):
        s.validate()


def test_missing_dimension_rejected() -> None:
    dims = dict.fromkeys(DEFAULT_WEIGHTS, 3)
    del dims["fault_tolerance"]
    s = Scenario(id="x", name="x", dimensions=dims,
                 human_minutes_per_run=1, runs_per_year=1, evidence="e")
    with pytest.raises(DiagnosisError, match="缺少维度"):
        s.validate()


def test_unknown_hard_reject_key_rejected() -> None:
    s = Scenario(id="x", name="x", dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 3),
                 human_minutes_per_run=1, runs_per_year=1, evidence="e",
                 hard_reject="i_am_made_up")
    with pytest.raises(DiagnosisError, match="未知 hard_reject"):
        s.validate()


def test_negative_cost_rejected() -> None:
    s = Scenario(id="x", name="x", dimensions=dict.fromkeys(DEFAULT_WEIGHTS, 3),
                 human_minutes_per_run=-5, runs_per_year=1, evidence="e")
    with pytest.raises(DiagnosisError, match="不能为负"):
        s.validate()


# ---------------------------------------------------------------------------
# 场景清单（真实资产）
# ---------------------------------------------------------------------------


def test_scenarios_load_and_all_valid(scenarios: list[Scenario]) -> None:
    """清单里的每条都必须通过校验。"""
    assert len(scenarios) >= 10, "场景太少，体现不出诊断方法论的价值"
    for s in scenarios:
        s.validate()


def test_scenario_ids_unique(scenarios: list[Scenario]) -> None:
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))


def test_every_scenario_has_evidence(scenarios: list[Scenario]) -> None:
    """每条场景必须写明打分依据 —— 没有依据的诊断等于拍脑袋。"""
    for s in scenarios:
        assert s.evidence.strip(), f"{s.id} 缺少 evidence"


def test_has_rejected_scenarios(scenarios: list[Scenario]) -> None:
    """必须存在 D 象限场景 —— 全是「建议做」的报告恰恰证明没诊断过。"""
    results = diagnose_all(scenarios)
    rejected = [d for d in results if d.quadrant is Quadrant.D_REJECT]
    assert len(rejected) >= 2, "至少应有 2 个明确劝退的场景"


def test_rejected_scenarios_have_reason(scenarios: list[Scenario]) -> None:
    """劝退必须给理由，不能只说「不建议」。"""
    for d in diagnose_all(scenarios):
        if d.quadrant is Quadrant.D_REJECT:
            assert d.reject_reason, f"{d.scenario.id} 被劝退但没给理由"


def test_stockout_alert_lands_in_a(scenarios: list[Scenario]) -> None:
    """断货预警是纯除法规则，应该落在 A 象限（工作流即可，不需要 AI）。"""
    by_id = {s.id: s for s in scenarios}
    s = by_id.get("stockout_risk_alert")
    if s is None:
        pytest.skip("场景清单中无 stockout_risk_alert")
    assert s.quadrant() is Quadrant.A_AUTO


def test_review_triage_lands_in_c(scenarios: list[Scenario]) -> None:
    """差评归因规则模糊、有数据，应落在 C 象限（AI 主导）。"""
    by_id = {s.id: s for s in scenarios}
    s = by_id.get("review_triage_draft")
    if s is None:
        pytest.skip("场景清单中无 review_triage_draft")
    assert s.quadrant() is Quadrant.C_AI_FIRST


def test_supplier_lead_time_is_rejected(scenarios: list[Scenario]) -> None:
    """供应链交期：判据清晰但无数据源 → 必须劝退。"""
    by_id = {s.id: s for s in scenarios}
    s = by_id.get("supplier_lead_time_tracking")
    if s is None:
        pytest.skip("场景清单中无 supplier_lead_time_tracking")
    assert s.quadrant() is Quadrant.D_REJECT
    assert s.annual_hours_saved() == 0.0


# ---------------------------------------------------------------------------
# 关键指标：打分器排序 vs 人工标注
# ---------------------------------------------------------------------------


def test_ranking_matches_human_judgement(scenarios: list[Scenario]) -> None:
    """**诊断方法论是否可验证** —— 打分器排序 vs 人工优先级标注的秩相关。

    阈值 0.6（不是 0.9）：模型的优先级排序与人工判断**存在真实的业务分歧**，
    见 `test_known_disagreement_with_human_judgement`。那个分歧本身就是结论，
    强行调权重去凑高相关性才是数据造假。

    若此指标跌到 0.4 以下，说明方法论与业务直觉严重背离，必须重新审视权重。
    """
    labelled = [s for s in scenarios if s.human_rank is not None]
    if len(labelled) < 4:
        pytest.skip("人工标注样本不足")

    scores = [s.priority_rank() for s in labelled]
    ranks = [-float(s.human_rank) for s in labelled]  # type: ignore[arg-type]
    rho = _spearman(scores, ranks)

    assert rho >= 0.6, (
        f"打分器排序与人工判断的秩相关仅 {rho:.2f}（<0.6），"
        "说明四维权重与实际业务直觉严重背离，需重新审视"
    )


def test_known_disagreement_with_human_judgement(scenarios: list[Scenario]) -> None:
    """**记录一处已知的、与人工判断的分歧** —— 这是结论，不是缺陷。

    现象：客服工单分类与转派年省工时最高（约 190h），模型排序靠前；
    但人工标注把它排在末位（第 9）。

    解读：人工排序的权重是「避损失」而非「省工时」。
    客服工单省下的是运营人员的键盘时间；而断货、Listing 合规省下的是
    **真金白银**（Listing 降权、广告费白烧、封店风险）。
    这正是 `loss_impact` 这一维存在的原因。

    这个测试锁住该分歧的存在，防止未来为了刷高相关性而把它抹平 ——
    抹平分歧就等于抹掉了方法论真正的洞察。
    """
    by_id = {s.id: s for s in scenarios}
    ticket = by_id.get("support_ticket_routing")
    stockout = by_id.get("stockout_risk_alert")
    if ticket is None or stockout is None:
        pytest.skip("场景清单缺少对比样本")

    results = {d.scenario.id: d for d in diagnose_all(scenarios)}
    t_hours = results["support_ticket_routing"].annual_hours_saved
    s_hours = results["stockout_risk_alert"].annual_hours_saved

    # 客服工单省工时更多
    assert t_hours > s_hours, "前提：客服工单的年省工时更高"
    # 但人工把客服排在断货之后（human_rank 数字更大 = 优先级更低）
    assert ticket.human_rank > stockout.human_rank, (
        "前提：人工判断中，客服工单的优先级低于断货预警"
    )
    # 且模型靠 loss_impact 把断货排到了客服之前 —— 这正是第五维的价值
    assert results["stockout_risk_alert"].priority > results["support_ticket_routing"].priority, (
        "loss_impact 维度应把\"避损失\"的场景排到\"省工时\"的场景之前"
    )


def test_loss_impact_reorders_priorities(scenarios: list[Scenario]) -> None:
    """把 loss_impact 权重设为 0，**低避损场景的优先级应当上升**。

    这证明第五维真的在起作用，而不是摆设。

    挑选 `loss_impact` 较低的样本（如客服工单li=2）作为断言对象 ——
    若拿`loss_impact=5`（满格）的场景做断言，它分数本来就接近上限，
    去掉该维度自然不会变化，那是无效断言。
    """
    low_impact = [
        s
        for s in scenarios
        if s.dimensions["loss_impact"] <= 2 and s.hard_reject is None and s.runs_per_year > 0
    ]
    if not low_impact:
        pytest.skip("场景清单中无低 loss_impact 样本")

    weights_without = {
        "frequency": 0.30,
        "rule_clarity": 0.25,
        "data_readiness": 0.25,
        "fault_tolerance": 0.20,
        "loss_impact": 0.0,
    }

    for s in low_impact:
        base = s.priority_rank()
        without = s.priority_rank(weights_without)
        assert base < without, (
            f"{s.id} 的 loss_impact={s.dimensions['loss_impact']}（低），"
            "去掉该维度权重后优先级应上升，否则说明第五维没起作用"
        )


def test_loss_impact_changes_some_scenarios(scenarios: list[Scenario]) -> None:
    """调整 loss_impact 权重**必须改变至少一部分场景的指数**。

    注：不能断言「所有场景都变」—— 移除一个维度会让其余维度权重相对上升，
    所以某些在loss_impact 上并不满分的场景，分数反而可能变高。
    这里只锁住「权重确实生效」这个不变量。

    正向的「低避损场景去掉权重后优先级上升」由上一个测试覆盖。
    """
    weights_without = {
        "frequency": 0.30,
        "rule_clarity": 0.25,
        "data_readiness": 0.25,
        "fault_tolerance": 0.20,
        "loss_impact": 0.0,
    }

    changed = [
        s.id
        for s in scenarios
        if abs(s.score() - s.score(weights_without)) > 1e-9
    ]
    assert changed, "调整 loss_impact 权重后没有任何场景的指数发生变化，该维度形同虚设"


def test_top_scenario_is_actionable(scenarios: list[Scenario]) -> None:
    """排名第一的场景不应落在 D 象限（否则报告没法落地）。"""
    results = diagnose_all(scenarios)
    assert results
    assert results[0].quadrant is not Quadrant.D_REJECT


def test_sorted_descending(scenarios: list[Scenario]) -> None:
    """输出必须按**优先级**降序（不是按指数）。"""
    results = diagnose_all(scenarios)
    assert [d.priority for d in results] == sorted(
        [d.priority for d in results], reverse=True
    )


def test_priority_differs_from_score(scenarios: list[Scenario]) -> None:
    """优先级排序应与指数排序**不完全一致** —— 否则两个指标是同一个东西。

    若两者完全一致，说明「指数」没有独立的信息量，
    那诊断报告就不该同时给两个排序。
    """
    results = diagnose_all(scenarios)
    by_priority = [d.scenario.id for d in results]
    by_score = [d.scenario.id for d in sorted(results, key=lambda d: d.score, reverse=True)]
    assert by_priority != by_score, "优先级与指数排序完全一致，说明两个指标冗余"


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def test_markdown_contains_all_scenarios(scenarios: list[Scenario]) -> None:
    md = render_markdown(diagnose_all(scenarios))
    for s in scenarios:
        assert s.name in md, f"报告缺少场景 {s.name}"


def test_markdown_has_quadrant_sections(scenarios: list[Scenario]) -> None:
    md = render_markdown(diagnose_all(scenarios))
    assert "汇总" in md
    assert "主动排除一个不值得做的环节" in md, "报告要传达敢劝退的立场"


def test_mermaid_renders(scenarios: list[Scenario]) -> None:
    out = render_quadrant_mermaid(diagnose_all(scenarios))
    assert out.startswith("```mermaid")
    assert "quadrantChart" in out
    assert out.rstrip().endswith("```")


def test_json_is_parseable(scenarios: list[Scenario]) -> None:
    import json

    payload = json.loads(render_json(diagnose_all(scenarios)))
    assert len(payload["results"]) == len(scenarios)
    assert payload["weights"] == DEFAULT_WEIGHTS
    assert payload["total_annual_hours_saved"] >= 0
    for item in payload["results"]:
        assert item["quadrant"] in {"A", "B", "C", "D"}
        assert item["strategy"]


def test_thresholds_are_sane() -> None:
    """阈值必须 A > B，否则象限判定逻辑反了。"""
    assert THRESHOLD_AUTO > THRESHOLD_ASSISTED


def test_fallback_scenarios_pass_validation() -> None:
    """无 PyYAML 时的降级清单也必须五维齐全、能过 validate。

    回归：`loss_impact` 第五维引入后，`_fallback_scenarios()` 一度没跟着加，
    导致任何无 PyYAML 环境跑 `make diagnose` 直接崩 —— 违背 fallback
    「缺依赖也不瘫」的设计初衷。此测试锁定降级清单与 DEFAULT_WEIGHTS 同步。
    """
    from basepilot.scenarios_loader import _fallback_scenarios

    fallback = _fallback_scenarios()
    assert fallback, "降级清单不能为空"
    for s in fallback:
        assert set(s.dimensions) == set(DEFAULT_WEIGHTS), (
            f"{s.id}: 降级清单维度必须与 DEFAULT_WEIGHTS 完全一致"
        )
        s.validate()  # 不抛异常即通过


def test_fallback_scenarios_align_with_yaml() -> None:
    """降级清单里与 yaml 同 id 的场景，五维打分必须一致。

    防止「改 yaml 不改 fallback」导致两条加载路径给出不同诊断结论。
    """
    from basepilot.scenarios_loader import _fallback_scenarios

    yaml_by_id = {s.id: s for s in load_scenarios()}
    for s in _fallback_scenarios():
        yaml_s = yaml_by_id.get(s.id)
        if yaml_s is None:
            continue  # fallback 独有的场景不强求
        assert s.dimensions == yaml_s.dimensions, (
            f"{s.id}: fallback 与 yaml 打分漂移 {s.dimensions} != {yaml_s.dimensions}"
        )