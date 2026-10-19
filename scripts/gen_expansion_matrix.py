"""生成可复制矩阵（expansion_matrix）—— 把一次性项目升级成可复用交付资产。

FDE 交付流程的第四步（接 case_backtest）：
- discovery_report 回答「先做哪个」
- solution_blueprint 回答「怎么做」
- case_backtest 回答「凭什么信你」
- expansion_matrix 回答「**这套打法能复制到哪**」——客户买的不是一个台账，
  而是一套能铺到任何业务线的诊断 + 落地方法

**报告即代码**：能力模式由 diagnosis 的四象限归纳，每种模式的
场景数/合计年省工时都从 scenarios.yaml 实算，不手写。
「可复制到」是定性判断（写在模式的 evidence 里），但锚定到已验证场景。

用法：
    python scripts/gen_expansion_matrix.py
    # 产物：docs/delivery/expansion_matrix.md
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.diagnosis import (  # noqa: E402
    Quadrant,
    diagnose_all,
)
from basepilot.scenarios_loader import load_scenarios  # noqa: E402

OUT = ROOT / "docs" / "delivery" / "expansion_matrix.md"


@dataclass(frozen=True)
class CapabilityPattern:
    """一种可复制的能力模式（由一组同象限场景归纳）。"""

    id: str
    name: str
    #: 这种模式的做法（一句话）
    recipe: str
    #: 可复制到的业务域（定性）
    replicate_to: str
    #: 属于本模式的场景名（跨境已验证，由象限归入）
    scenario_names: tuple[str, ...]
    #: 合计年省工时（实算填入）
    total_hours: float = 0.0


#: 能力模式定义：把四象限映射成四种可对外讲的「打法」。
#: scenario_names 留空，由 collect 按象限规则实算填入，避免手写漂移。
_PATTERNS: tuple[CapabilityPattern, ...] = (
    CapabilityPattern(
        id="rule_pipeline",
        name="规则搬运",
        recipe="判据明确到能写成公式/阈值 → 飞书原生工作流直接自动化，不上 AI",
        replicate_to="任何电商/零售的日报汇总、合规自查、异常抄送 —— 判据可枚举即搬",
        scenario_names=(),
    ),
    CapabilityPattern(
        id="threshold_alert",
        name="阈值预警",
        recipe="一个除法或比价即触发（库存÷销量<7天、低于我方X%）→ 工作流盯死",
        replicate_to="库存、价格、现金流、SLA —— 任何「一个比值定生死」的场景",
        scenario_names=(),
    ),
    CapabilityPattern(
        id="ai_drafting",
        name="AI 草拟 + 人工确认",
        recipe="规则写不出来（语义归因/文本归类）→ AI 出草案，人工点确认才生效",
        replicate_to="客服工单、评论回复、搜索词聚类、VOC 挖掘 —— 文本密集且判据模糊",
        scenario_names=(),
    ),
    CapabilityPattern(
        id="honest_reject",
        name="诚实劝退",
        recipe="缺数据源 或 动作不可逆 → 明确不做，写进报告，给前置动作",
        replicate_to="任何「数据在别人系统里」或「出错外部可见」的环节 —— 先补数据源/交专业人士",
        scenario_names=(),
    ),
)

#: 象限 → 能力模式 id 的归组规则（A 拆两种打法：纯搬运 vs 阈值预警）。
_QUADRANT_TO_PATTERN: dict[Quadrant, str] = {
    Quadrant.A_AUTO: "rule_pipeline",
    Quadrant.B_ASSISTED: "ai_drafting",
    Quadrant.C_AI_FIRST: "ai_drafting",
    Quadrant.D_REJECT: "honest_reject",
}

#: A 象限里属于「阈值预警」的场景（判据是单个比值/比价）。
#: 这是定性切分，但必须点名真实场景，不允许凭空。
_THRESHOLD_ALERT_NAMES = {"断货风险预警与通知", "竞品价格监控"}


def collect_patterns(results: list) -> list[CapabilityPattern]:  # type: ignore[type-arg]
    """按象限把场景归入能力模式，实算每种模式的场景数与合计年省。"""
    names_by_pattern: dict[str, list[str]] = {p.id: [] for p in _PATTERNS}
    hours_by_pattern: dict[str, float] = {p.id: 0.0 for p in _PATTERNS}

    for d in results:
        name = d.scenario.name
        if d.quadrant is Quadrant.A_AUTO and name in _THRESHOLD_ALERT_NAMES:
            pid = "threshold_alert"
        else:
            pid = _QUADRANT_TO_PATTERN[d.quadrant]
        names_by_pattern[pid].append(name)
        hours_by_pattern[pid] += d.annual_hours_saved

    out: list[CapabilityPattern] = []
    for p in _PATTERNS:
        out.append(
            CapabilityPattern(
                id=p.id,
                name=p.name,
                recipe=p.recipe,
                replicate_to=p.replicate_to,
                scenario_names=tuple(names_by_pattern[p.id]),
                total_hours=hours_by_pattern[p.id],
            )
        )
    return out


def render(patterns: list[CapabilityPattern], total_scenarios: int) -> str:
    today = date.today().isoformat()
    grand_hours = sum(p.total_hours for p in patterns)
    actionable_hours = sum(p.total_hours for p in patterns if p.id != "honest_reject")

    lines: list[str] = []
    lines.append("# 可复制矩阵：这套打法能铺到哪")
    lines.append("")
    lines.append(
        f"> 生成日期：{today}　|　归纳能力模式：**{len(patterns)} 种**　|　"
        f"覆盖已诊断场景：**{total_scenarios} 个**　|　"
        f"可落地年省：**{actionable_hours:.0f} 小时**　|　"
        f"前置：`docs/delivery/case_backtest.md`"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 定位 ----
    lines.append("## 这份矩阵是什么")
    lines.append("")
    lines.append("前面三份文档交付了**一个**跨境运营台账：诊断、方案、回测。")
    lines.append("但一次性的项目不是 FDE 的终点 —— 客户真正该买走的，")
    lines.append("是**一套能铺到任何业务线的方法**。")
    lines.append("")
    lines.append(
        f"这份矩阵把跨境三表里跑通的 {total_scenarios} 个场景，"
        f"归纳成 **{len(patterns)} 种能力模式**。"
        "每种模式都标注了：它是什么做法、跨境哪个场景已验证、能复制到哪些业务域。"
    )
    lines.append("")
    lines.append("**一句话：我交付的不是一个台账，而是一套诊断 + 落地的可复制资产。**")
    lines.append("")

    # ---- 矩阵总览 ----
    lines.append("## 能力模式矩阵")
    lines.append("")
    lines.append("| 能力模式 | 做法 | 跨境已验证场景 | 合计年省 | 可复制到 |")
    lines.append("|---|---|---|---|---|")
    for p in patterns:
        n = len(p.scenario_names)
        hours = f"{p.total_hours:.0f} h" if p.total_hours > 0 else "—（劝退）"
        lines.append(f"| **{p.name}** | {p.recipe} | {n} 个 | {hours} | {p.replicate_to} |")
    lines.append("")

    # ---- 逐模式展开 ----
    lines.append("---")
    lines.append("")
    lines.append("## 逐模式明细")
    lines.append("")
    for i, p in enumerate(patterns, 1):
        lines.append(f"### {i}. {p.name}")
        lines.append("")
        lines.append(f"- **做法**：{p.recipe}")
        lines.append(f"- **可复制到**：{p.replicate_to}")
        hours = f"{p.total_hours:.0f} 小时/年" if p.total_hours > 0 else "0（明确不投入）"
        lines.append(f"- **跨境已验证**（{len(p.scenario_names)} 个场景，合计年省 {hours}）：")
        lines.append("")
        for name in p.scenario_names:
            lines.append(f"  - {name}")
        lines.append("")

    # ---- 商业叙事 ----
    lines.append("---")
    lines.append("")
    lines.append("## 为什么这是资产，不是项目")
    lines.append("")
    lines.append("| | 一次性项目 | 可复制资产（本矩阵） |")
    lines.append("|---|---|---|")
    lines.append("| 交付物 | 一个跨境台账 | 一套诊断方法 + 4 种能力模式 |")
    lines.append("| 复用 | 只服务当前业务线 | 铺到任何「判据可枚举/文本密集」的业务域 |")
    lines.append("| 价值衰减 | 交付即封顶 | 每接入一个新场景，边际成本递减 |")
    lines.append("| 对客户的意义 | 解决一个痛点 | 获得一套能自己往下铺的判断框架 |")
    lines.append("")
    lines.append(
        f"四种模式合计覆盖年省 **{grand_hours:.0f} 小时**"
        f"（其中可落地 **{actionable_hours:.0f} 小时**，"
        "其余为诚实劝退、明确不投）。"
    )
    lines.append("客户接走的不是「做完的事」，而是「知道哪些该做、哪些不该做、怎么做」的能力。")
    lines.append("")

    # ---- 收束 ----
    lines.append("## 复制的边界（如实告知）")
    lines.append("")
    lines.append(
        "- **能力模式可复制，具体判据不可照搬**：库存÷销量的「7 天」是宠物类目的经验值，"
        "换类目要重新标定"
    )
    lines.append(
        "- **AI 草拟模式强依赖数据源**：差评归因能复制，前提是目标业务也有历史文本沉淀；"
        "没有就退回「诚实劝退」"
    )
    lines.append(
        "- **诚实劝退是资产，不是失败**：它让客户在「数据源没就位」的环节不浪费预算 —— "
        "这本身就是交付价值"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "> 本矩阵由 `scripts/gen_expansion_matrix.py` 自动生成，"
        "能力模式由四象限归纳、场景数与年省工时从 `diagnosis.py` 实算，"
        "「可复制到」为定性判断。改场景包后重跑 "
        "`python scripts/gen_expansion_matrix.py` 即可更新。"
    )
    return "\n".join(lines)


def main() -> int:
    results = diagnose_all(load_scenarios())
    patterns = collect_patterns(results)
    OUT.write_text(render(patterns, len(results)), encoding="utf-8")
    print(f"✅ 已生成 {OUT}")
    print(f"   归纳 {len(patterns)} 种能力模式（覆盖 {len(results)} 个已诊断场景）：")
    for p in patterns:
        print(f"   · {p.name}：{len(p.scenario_names)} 个场景，年省 {p.total_hours:.0f}h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
