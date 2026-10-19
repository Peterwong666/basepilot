"""生成推广日历（rollout_calendar）—— 单点验证完之后，怎么把能力模式铺出去。

FDE 交付流程的第五步（接 expansion_matrix）：
- discovery_report 回答「先做哪个」
- solution_blueprint 回答「怎么做」
- case_backtest 回答「凭什么信你」
- expansion_matrix 回答「能复制到哪」
- rollout_calendar 回答「**按什么节奏铺**」——把能力模式排成横向推广的波次日历

**报告即代码**：能力模式/场景数/年省工时从 diagnosis + expansion_matrix 实算；
时间轴（波次/周次）是显式的**规划模板**——它本身是定性决策，如实标注，
不伪装成算出来的。

用法：
    python scripts/gen_rollout_calendar.py
    # 产物：docs/delivery/rollout_calendar.md
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # 让 `from scripts.gen_expansion_matrix import ...` 可用

from basepilot.diagnosis import diagnose_all  # noqa: E402
from basepilot.scenarios_loader import load_scenarios  # noqa: E402
from scripts.gen_expansion_matrix import CapabilityPattern, collect_patterns  # noqa: E402

OUT = ROOT / "docs" / "delivery" / "rollout_calendar.md"


@dataclass(frozen=True)
class Wave:
    """一个推广波次。"""

    no: int
    phase: str  # 时间窗（相对 T0）
    title: str
    pattern_id: str  # 对应能力模式（"" 表示跨模式/元动作）
    actions: tuple[str, ...]
    gate: str  # 达标判据（gate criterion）
    rationale: str  # 为什么排在这一波


#: 波次规划模板（时间轴是定性决策，pattern 引用实算）。
#: 顺序原则：先稳后难 —— 规则/阈值（A 象限，零 AI、零数据依赖）先铺，
#: AI 草拟（要数据源）后铺；劝退模式不作为独立波次，而是每波的「前置提问」。
_WAVE_TEMPLATES: tuple[Wave, ...] = (
    Wave(
        no=0,
        phase="T0（单点验证完成）",
        title="跨境三表闭环跑通，作为复制母版",
        pattern_id="",
        actions=(
            "按 `solution_blueprint.md` 4 周节奏落地跨境三表",
            "按 `weekly_ops.md` 跑 8 周运营，促活三指标达标",
            "产出 `case_backtest.md` 回测证据",
        ),
        gate="跨境台账连续 4 周促活达标 + 回测 4/4 兑现",
        rationale="没有跑通的母版就谈复制，是把未验证的假设批量放大 —— 先有一个能打的样板。",
    ),
    Wave(
        no=1,
        phase="第 1-2 月",
        title="铺「规则搬运」到同业态其他业务线",
        pattern_id="rule_pipeline",
        actions=(
            "用 `make diagnose` 诊断目标业务线的日报/合规/抄送类环节",
            "判据可枚举的，直接套工作流模板（不上 AI）",
            "每接一条线，重跑 `gen_expansion_matrix.py` 更新矩阵",
        ),
        gate="目标业务线至少 1 个规则搬运场景上线且幂等验证通过",
        rationale="A 象限零数据依赖、零 AI 风险，是复制成本最低、最快见效的一波 —— 先建信任。",
    ),
    Wave(
        no=2,
        phase="第 2-3 月",
        title="铺「阈值预警」到库存/价格/SLA 类场景",
        pattern_id="threshold_alert",
        actions=(
            "识别目标线里「一个比值定生死」的环节（库存÷销量、比价、账期）",
            "重新标定阈值（母版的「7 天」是宠物类目经验值，不可照搬）",
            "接工作流盯死，误报成本须接近零",
        ),
        gate="阈值经业务方签字标定 + 预警上线后误报率可接受",
        rationale="阈值预警判据是单比值，比规则搬运多一步「阈值标定」，所以排在第二波。",
    ),
    Wave(
        no=3,
        phase="第 3-6 月",
        title="铺「AI 草拟 + 人工确认」到文本密集环节",
        pattern_id="ai_drafting",
        actions=(
            "先问数据源：目标线有没有历史文本沉淀（差评/工单/搜索词）",
            "有 → AI 出草案 + 人工确认闭环；没有 → 退回诚实劝退，先补数据源",
            "复核成本必须低于纯人工，否则不上",
        ),
        gate="数据源就位 + AI 草案人工复核成本 < 纯人工成本",
        rationale="AI 草拟强依赖数据源、复核有成本，是四种模式里门槛最高的 —— "
        "放最后，用前两波攒的信任换数据配合。",
    ),
)


def _pattern_map(patterns: list[CapabilityPattern]) -> dict[str, CapabilityPattern]:
    return {p.id: p for p in patterns}


def render(
    waves: list[Wave],
    patterns: list[CapabilityPattern],
    n_scenarios: int,
) -> str:
    today = date.today().isoformat()
    pmap = _pattern_map(patterns)

    lines: list[str] = []
    lines.append("# 推广日历：单点跑通后，按什么节奏铺出去")
    lines.append("")
    lines.append(
        f"> 生成日期：{today}　|　推广波次：**{len(waves)} 波**　|　"
        f"可推广能力模式：**{len(patterns)} 种**　|　"
        f"前置：`docs/delivery/expansion_matrix.md`"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 定位 ----
    lines.append("## 这份日历是什么")
    lines.append("")
    lines.append("expansion_matrix 说了「这套打法**能**复制到哪」；")
    lines.append("这份日历说的是「**按什么节奏**铺」—— 复制的顺序本身就是决策：")
    lines.append(
        "铺错顺序（先上最难的 AI 草拟），会在数据源没就位时翻车，把「方法可信」一起赔进去。"
    )
    lines.append("")
    lines.append(
        "**排序原则：先稳后难。** 零数据依赖、零 AI 风险的先铺，"
        "强依赖数据源、有复核成本的后铺；每一波都用前一波攒下的信任，"
        "换下一波所需的配合。"
    )
    lines.append("")
    lines.append(
        "> ⚠️ 时间轴（T0 / 第 N 月）是**规划模板**，是定性决策，"
        "不是算出来的。能力模式、场景数、年省工时才是实算。"
    )
    lines.append("")

    # ---- 日历总览 ----
    lines.append("## 推广波次总览")
    lines.append("")
    lines.append("| 波次 | 时间窗 | 推什么 | 达标判据（gate） |")
    lines.append("|---|---|---|---|")
    for w in waves:
        if w.pattern_id and w.pattern_id in pmap:
            p = pmap[w.pattern_id]
            what = f"**{p.name}**（{len(p.scenario_names)} 场景）"
        else:
            what = f"**{w.title}**"
        lines.append(f"| {w.no} | {w.phase} | {what} | {w.gate} |")
    lines.append("")

    # ---- 逐波次展开 ----
    lines.append("---")
    lines.append("")
    lines.append("## 逐波次明细")
    lines.append("")
    for w in waves:
        lines.append(f"### 波次 {w.no} · {w.phase}：{w.title}")
        lines.append("")
        if w.pattern_id and w.pattern_id in pmap:
            p = pmap[w.pattern_id]
            hours = f"{p.total_hours:.0f} 小时/年" if p.total_hours > 0 else "—"
            lines.append(
                f"- **能力模式**：{p.name}（跨境已验证 {len(p.scenario_names)} 场景，年省 {hours}）"
            )
            lines.append(f"- **做法**：{p.recipe}")
        else:
            lines.append("- **性质**：复制母版（元动作，不属于单一能力模式）")
        lines.append(f"- **达标判据**：{w.gate}")
        lines.append("")
        lines.append("**动作**：")
        lines.append("")
        for a in w.actions:
            lines.append(f"- {a}")
        lines.append("")
        lines.append(f"**为什么排在这一波**：{w.rationale}")
        lines.append("")

    # ---- 贯穿全程的劝退闸 ----
    reject = pmap.get("honest_reject")
    lines.append("---")
    lines.append("")
    lines.append("## 贯穿每一波的「劝退闸」")
    lines.append("")
    if reject:
        lines.append(
            f"四种能力模式里，「**{reject.name}**」不是独立波次，而是**每一波的前置提问**。"
        )
        lines.append("")
        lines.append("每铺一条新业务线，先问两句：")
        lines.append("")
        lines.append("1. **数据源就位吗？** 不在自己系统里 → 先补数据登记，别上自动化")
        lines.append(
            "2. **动作可逆吗？** 出错外部可见（申报/改价/发给客户）→ 交专业人士，AI 只做预检"
        )
        lines.append("")
        lines.append(
            f"跨境母版已用 {len(reject.scenario_names)} 个劝退案例"
            f"（{'、'.join(reject.scenario_names)}）验证了这套闸的价值："
            "敢在数据源没就位时说「先别做」，是复制的底气。"
        )
    lines.append("")

    # ---- 节奏原则收束 ----
    lines.append("---")
    lines.append("")
    lines.append("## 节奏原则（为什么是这个顺序）")
    lines.append("")
    lines.append("| 波次 | 依赖 | 风险 | 复制的信任成本 |")
    lines.append("|---|---|---|---|")
    lines.append("| 1 规则搬运 | 无数据依赖 | 零 AI 风险 | 最低 —— 拿来即用 |")
    lines.append("| 2 阈值预警 | 需阈值标定 | 误报风险 | 低 —— 比值讲清楚即可 |")
    lines.append("| 3 AI 草拟 | **强依赖数据源** | 复核成本 | 高 —— 要客户开放数据 |")
    lines.append("")
    lines.append("把强依赖数据源的 AI 草拟放最后，不是因为它不重要，")
    lines.append("而是它需要的「数据配合」只能靠前两波的成功换来。")
    lines.append("**顺序错了，方法再对也会翻车。**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"> 本日历由 `scripts/gen_rollout_calendar.py` 自动生成。"
        f"能力模式/场景数/年省工时从 `diagnosis.py` 实算"
        f"（覆盖 {n_scenarios} 个已诊断场景）；"
        "波次时间轴为规划模板（定性决策）。改场景包后重跑 "
        "`python scripts/gen_rollout_calendar.py` 更新模式部分。"
    )
    return "\n".join(lines)


def main() -> int:
    results = diagnose_all(load_scenarios())
    patterns = collect_patterns(results)
    waves = list(_WAVE_TEMPLATES)
    OUT.write_text(render(waves, patterns, len(results)), encoding="utf-8")
    print(f"✅ 已生成 {OUT}")
    print(f"   {len(waves)} 个推广波次（基于 {len(patterns)} 种能力模式）：")
    for w in waves:
        print(f"   · 波次{w.no} [{w.phase}] {w.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
