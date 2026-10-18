"""生成客户诊断报告（discovery_report）—— FDE 交付流程的第一步产出。

与 `make diagnose` 的区别：
- `make diagnose` 是**顾问内部**的完整诊断（15 个场景全量 + 四象限图）
- discovery_report 是**给客户看的**现场版——同样的实算数据，
  但叙事结构是「你的业务 → 我们怎么判断 → 先做什么 → 不做什么」

**所有数字都来自 diagnosis.py 实算，不写死。** 改 scenarios.yaml 后
重跑本脚本，报告自动更新 —— 这是「报告即代码」的交付纪律。

用法：
    python scripts/gen_discovery_report.py
    # 产物：docs/delivery/discovery_report.md
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.diagnosis import (  # noqa: E402
    DEFAULT_WEIGHTS,
    DIMENSION_LABEL,
    QUADRANT_LABEL,
    QUADRANT_STRATEGY,
    Quadrant,
    diagnose_all,
)
from basepilot.scenarios_loader import load_scenarios  # noqa: E402

OUT = ROOT / "docs" / "delivery" / "discovery_report.md"


def render(results: list) -> str:  # type: ignore[type-arg]
    today = date.today().isoformat()
    actionable = [d for d in results if d.quadrant is not Quadrant.D_REJECT]
    rejected = [d for d in results if d.quadrant is Quadrant.D_REJECT]
    total_saved = sum(d.annual_hours_saved for d in results)
    top = actionable[0] if actionable else None

    lines: list[str] = []
    lines.append("# 客户业务诊断报告：哪个环节值得上 AI")
    lines.append("")
    lines.append(f"> 生成日期：{today}　|　评估环节：**{len(results)} 个**　|　"
                 f"建议投入：**{len(actionable)} 个**　|　明确劝退：**{len(rejected)} 个**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 1. 这份报告回答什么问题 ----
    lines.append("## 这份报告回答什么问题")
    lines.append("")
    lines.append("您已经有不少环节在用人工跑：每天导 CSV、贴台账、标异常、跟差评。")
    lines.append("想上 AI，但第一个问题不是「怎么上」，而是——")
    lines.append("")
    lines.append("> **哪个环节值得先上？哪个环节上了也是浪费钱？**")
    lines.append("")
    lines.append("这份报告用一套**可复现的打分方法**（不是拍脑袋），")
    lines.append(f"对您 {len(results)} 个业务环节逐一评估，给出「先做哪个、不做什么」的明确结论。")
    lines.append("")

    # ---- 2. 判断标准（五维） ----
    lines.append("## 我们怎么判断：五个维度")
    lines.append("")
    lines.append("判断标准来自一线运营的真实经验，每个维度回答一个「值不值」的问题：")
    lines.append("")
    lines.append("| 维度 | 回答的问题 | 权重 |")
    lines.append("|---|---|---|")
    weights_note = {
        "frequency": ("这个事发生多频繁？", "决定值不值，是第一维度"),
        "rule_clarity": ("判据写得出来吗？", "写得出来 → 工作流就够，不必上 AI"),
        "data_readiness": ("有历史数据喂 AI 吗？", "没数据 → 模型再强也学不会"),
        "fault_tolerance": ("出错了兜得住吗？", "不可逆动作（改价/发给客户）必须降权"),
        "loss_impact": ("不做会亏多少？", "防损型环节的价值不体现在工时上"),
    }
    for key, (question, _why) in weights_note.items():
        lines.append(
            f"| **{DIMENSION_LABEL[key]}** | {question} | {DEFAULT_WEIGHTS[key]:.2f} |"
        )
    lines.append("")
    lines.append("> 特别注意「避损失」这一维：断货一次亏的钱，可能超过客服一年省下的工时。")
    lines.append("> **「省时间」和「避损失」是两回事**，所以指数和优先级是两个排序。")
    lines.append("")

    # ---- 3. 结论总览 ----
    lines.append("## 结论：先做什么")
    lines.append("")
    lines.append("（按**投入优先级**排序：年省工时 × 指数修正。象限的完整做法见下文分区）")
    lines.append("")
    lines.append("| # | 业务环节 | 指数 | 象限 | 年省工时 |")
    lines.append("|---|---|---|---|---|")
    for i, d in enumerate(results, 1):
        lines.append(
            f"| {i} | {d.scenario.name} | {d.score:.0f} | "
            f"`{d.quadrant.value}` {QUADRANT_LABEL[d.quadrant]} | "
            f"{d.annual_hours_saved:.0f} h |"
        )
    lines.append("")
    if top:
        lines.append(f"**建议从「{top.scenario.name}」起步**："
                     f"指数 {top.score:.0f}、年省 {top.annual_hours_saved:.0f} 小时，"
                     f"且 {QUADRANT_LABEL[top.quadrant]}，落地最稳。")
        lines.append("")

    # ---- 4. 四象限落地形态 ----
    lines.append("## 四个象限，四种做法")
    lines.append("")
    lines.append("不是所有环节都用同一种方式上 AI。我们按「指数 + 规则明确度」分成四类：")
    lines.append("")
    for q in Quadrant:
        group = [d for d in results if d.quadrant is q]
        if not group:
            continue
        lines.append(f"### 象限 {q.value} · {QUADRANT_LABEL[q]}（{len(group)} 个）")
        lines.append("")
        lines.append(f"**做法**：{QUADRANT_STRATEGY[q]}")
        lines.append("")
        for d in group:
            lines.append(f"- **{d.scenario.name}**（指数 {d.score:.0f}，"
                         f"年省 {d.annual_hours_saved:.0f}h）")
            if d.reject_reason:
                lines.append(f"  - 劝退理由：{d.reject_reason}")
            lines.append(f"  - 业务依据：{d.scenario.evidence.strip()}")
        lines.append("")

    # ---- 5. 我们不建议做什么 ----
    if rejected:
        lines.append("## 同样重要：我们不建议做什么")
        lines.append("")
        lines.append("一份只会说「都能做 AI」的诊断报告，恰恰证明没诊断过。")
        lines.append(f"以下 **{len(rejected)} 个环节我们明确劝退**，理由写在这里：")
        lines.append("")
        for d in rejected:
            lines.append(f"- **{d.scenario.name}**：{d.reject_reason}")
        lines.append("")
        lines.append("> 主动排除一个不值得做的环节，比多做一个勉强上线的场景更负责。")
        lines.append("")

    # ---- 6. 汇总与下一步 ----
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- 评估环节：{len(results)} 个")
    lines.append(f"- 建议投入：{len(actionable)} 个（排除 {len(rejected)} 个劝退项）")
    lines.append(f"- 合计年省工时：**{total_saved:.0f} 小时**")
    lines.append("")
    lines.append("## 下一步")
    lines.append("")
    lines.append("1. 本报告确认后，进入「方案蓝图」（`docs/delivery/solution_blueprint.md`）——")
    lines.append("   把排名靠前的 1-2 个环节展开成可交付的技术方案")
    lines.append("2. 建表与灌数据：`scripts/setup_tables.py` + `scripts/seed_cross_border.py`")
    lines.append("3. 上线后按 `docs/delivery/weekly_ops.md` 跑 8 周运营")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> 本报告由 `scripts/gen_discovery_report.py` 自动生成，"
                 "所有数字来自 `src/basepilot/diagnosis.py` 实算。"
                 "场景清单改动后重跑 `python scripts/gen_discovery_report.py` 即可更新。")
    return "\n".join(lines)


def main() -> int:
    scenarios = load_scenarios()
    results = diagnose_all(scenarios)
    OUT.write_text(render(results), encoding="utf-8")
    print(f"✅ 已生成 {OUT}")
    print(f"   评估 {len(results)} 个环节，"
          f"建议投入 {sum(1 for d in results if d.quadrant is not Quadrant.D_REJECT)} 个，"
          f"劝退 {sum(1 for d in results if d.quadrant is Quadrant.D_REJECT)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
