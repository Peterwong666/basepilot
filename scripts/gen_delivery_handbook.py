"""生成 FDE 交付手册合集页（delivery_handbook）—— 五份交付文档的导航与串联。

前面五份「报告即代码」文档各自回答交付流程里的一个问题：
- discovery_report 回答「先做哪个」
- solution_blueprint 回答「怎么做」
- case_backtest 回答「凭什么信你」
- expansion_matrix 回答「能复制到哪」
- rollout_calendar 回答「按什么节奏铺」

**为什么还需要一页合集**：
五份文档本身已经完整，但客户/面试官拿到的是「一叠散落的 Markdown」。
阅读顺序、每份回答什么问题、哪些数字是实算哪些是规划 —— 这些信息
分散在五份文档里，合集页把它收拢成一份可以转发的入口。

**报告即代码**：合集页里的统计数字（场景数/年省工时/回测条数/能力模式数/波次数）
全部从各生成脚本的产物或 diagnosis 实算，不手写。改场景包后重跑自动更新。

用法：
    python scripts/gen_delivery_handbook.py
    # 产物：docs/delivery/delivery_handbook.md
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.diagnosis import diagnose_all  # noqa: E402
from basepilot.scenarios_loader import load_scenarios  # noqa: E402

DELIVERY = ROOT / "docs" / "delivery"
OUT = DELIVERY / "delivery_handbook.md"


@dataclass(frozen=True)
class Doc:
    """交付文档链的一份文档。"""

    #: 文档 id（文件名去扩展名）
    id: str
    #: 流程第几步（1-5）
    step: int
    #: 一句话标题
    title: str
    #: 它回答的那个问题
    answers: str
    #: 给谁看
    audience: str
    #: 生成脚本
    script: str
    #: 本页要展示的关键数字键（从 headline 取）
    headline: str
    #: 数字口径说明（实算 / 规划），不得留空
    basis: str


#: 文档链定义。顺序即交付流程顺序，前置关系由 step 隐含表达。
DOCS: tuple[Doc, ...] = (
    Doc(
        id="discovery_report",
        step=1,
        title="客户业务诊断报告：哪个环节值得上 AI",
        answers="先做哪个",
        audience="客户业务负责人",
        script="scripts/gen_discovery_report.py",
        headline="诊断",
        basis="五维打分从 `scenarios.yaml` 实算",
    ),
    Doc(
        id="solution_blueprint",
        step=2,
        title="方案蓝图：把排名靠前的环节做成什么样",
        answers="怎么做",
        audience="客户业务 + 技术双方（可签字）",
        script="scripts/gen_solution_blueprint.py",
        headline="方案",
        basis="年省工时从 diagnosis 实算",
    ),
    Doc(
        id="case_backtest",
        step=3,
        title="案例回测：当初的预测，兑现了吗",
        answers="凭什么信你",
        audience="客户技术评审 / 采购",
        script="scripts/gen_case_backtest.py",
        headline="回测",
        basis="预测兑现数对 cassette + eval 落盘事实对账",
    ),
    Doc(
        id="expansion_matrix",
        step=4,
        title="可复制矩阵：这套打法能铺到哪",
        answers="能复制到哪",
        audience="客户管理层（决定二期范围）",
        script="scripts/gen_expansion_matrix.py",
        headline="矩阵",
        basis="场景数/年省按四象限实算；「可复制到」为定性判断",
    ),
    Doc(
        id="rollout_calendar",
        step=5,
        title="推广日历：单点跑通后，按什么节奏铺出去",
        answers="按什么节奏铺",
        audience="客户项目负责人（排期与里程碑）",
        script="scripts/gen_rollout_calendar.py",
        headline="日历",
        basis="波次划分是规划决策，时间轴为定性；已验证场景数实算",
    ),
)


def read_headline(doc_id: str) -> str:
    """读取一份交付文档首行的 `> ... |key:value| ...` 摘要行。"""
    path = DELIVERY / f"{doc_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"交付文档缺失：{path}（请先跑 {doc_id} 的生成脚本）")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            return line.lstrip("> ").strip()
    return ""


def _fact_block(results: list) -> tuple[int, float, float]:
    """实算诊断侧三个数字：评估环节数、可投入数、合计年省工时。

    劝退场景不计入可投入，也不贡献年省 —— 与 discovery_report 口径一致。
    """
    actionable = [d for d in results if d.quadrant.name != "D_REJECT"]
    hours = sum(d.annual_hours_saved for d in actionable)
    return len(results), len(actionable), hours


def render(results: list) -> str:
    """生成合集页 Markdown。"""
    today = date.today().isoformat()
    total_scenarios, actionable_count, actionable_hours = _fact_block(results)
    rejected_count = total_scenarios - actionable_count

    lines: list[str] = []
    lines.append("# FDE 交付手册：跨境运营台账项目")
    lines.append("")
    lines.append(
        f"> 生成日期：{today}　|　交付文档：**{len(DOCS)} 份**　|　"
        f"评估环节：**{total_scenarios} 个**　|　"
        f"建议投入：**{actionable_count} 个**　|　"
        f"明确劝退：**{rejected_count} 个**　|　"
        f"可落地年省：**{actionable_hours:.0f} 小时**"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 这份合集是什么 ----
    lines.append("## 这份合集是什么")
    lines.append("")
    lines.append(
        "它是一份**入口**：把一个真实交付项目的五份文档串成一条线，"
        "让你知道**先读哪份、每份回答什么问题、哪些数字是算出来的**。"
    )
    lines.append("")
    lines.append(
        "五份文档按交付顺序排列，每份解决客户心里的一个疑问 —— "
        "从「该做什么」到「凭什么信你」，再到「二期铺多大、按什么节奏」。"
    )
    lines.append("")
    lines.append(
        f"**一句话：{actionable_count} 个环节建议投入、{rejected_count} 个明确劝退、"
        f"合计年省 {actionable_hours:.0f} 小时 —— 每一步都有可核对的依据。**"
    )
    lines.append("")

    # ---- 五份文档一览 ----
    lines.append("---")
    lines.append("")
    lines.append("## 五份文档一览")
    lines.append("")
    lines.append("| # | 文档 | 回答什么问题 | 给谁看 | 关键数字口径 |")
    lines.append("|---|---|---|---|---|")
    for d in DOCS:
        lines.append(
            f"| {d.step} | [{d.title}]({d.id}.md) | **{d.answers}** "
            f"| {d.audience} | {d.basis} |"
        )
    lines.append("")

    # ---- 交付顺序 ----
    lines.append("---")
    lines.append("")
    lines.append("## 交付顺序：五个问题，一条线")
    lines.append("")
    lines.append("客户不会按你想的顺序读文档。真实顺序是**跟着他的疑问走**：")
    lines.append("")
    for d in DOCS:
        lines.append(f"{d.step}. **{d.answers}** → [`{d.id}.md`]({d.id}.md)　_{d.audience}_")
    lines.append("")
    lines.append(
        "顺序不能换。先说「怎么做」客户会问「凭什么做这个」，"
        "先说「能铺多大」客户会问「单点跑不跑得通」。"
        "**这条顺序本身就是交付方法的一部分。**"
    )
    lines.append("")

    # ---- 证据口径 ----
    lines.append("---")
    lines.append("")
    lines.append("## 哪些数字是算出来的，哪些不是")
    lines.append("")
    lines.append(
        "这是整份手册最该被先读懂的一节 —— "
        "**任何咨询交付都该经得起「你这个数哪来的」这一问。**"
    )
    lines.append("")
    lines.append("| 数字 | 来源 | 性质 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| 评估环节 {total_scenarios} 个 / 建议投入 {actionable_count} 个 | "
        "`diagnosis.py` 五维打分 | 🟢 实算 |"
    )
    lines.append(
        f"| 可落地年省 {actionable_hours:.0f} 小时 | "
        "diagnosis 的 `annual_hours_saved` 求和 | 🟢 实算 |"
    )
    lines.append(
        "| 字段编码正确率 / 重试成功率 / 单表最大并发 | "
        "`make eval` 压测与故障注入 | 🟢 实算 |"
    )
    lines.append(
        "| 飞书真实交互证据 | cassette 录制的真实租户请求 | 🟢 实测 |"
    )
    lines.append(
        "| 「可复制到」的业务域 | 从已验证场景抽象的定性判断 | 🟡 定性 |"
    )
    lines.append(
        "| 推广时间轴（T0 / 1-2 月 / 2-3 月 / 3-6 月） | 先稳后难的排期决策 | 🟡 规划 |"
    )
    lines.append("")
    lines.append(
        "**实算的会随场景包改动自动重算，定性的明确标注。** "
        "没有任何一个数字是手写进文档的。"
    )
    lines.append("")

    # ---- 五连摘要 ----
    lines.append("---")
    lines.append("")
    lines.append("## 五份文档摘要（读全本前先扫这段）")
    lines.append("")
    for d in DOCS:
        headline = read_headline(d.id)
        lines.append(f"### {d.step}. {d.title}")
        lines.append("")
        lines.append(f"- **回答**：{d.answers}　|　**给谁看**：{d.audience}")
        if headline:
            lines.append(f"- **摘要行**：{headline}")
        lines.append(f"- **生成脚本**：`{d.script}`")
        lines.append(f"- **本文档**：[`{d.id}.md`]({d.id}.md)")
        lines.append("")

    # ---- 诚实边界 ----
    lines.append("---")
    lines.append("")
    lines.append("## 这套方法不承诺什么")
    lines.append("")
    lines.append(
        "交付材料说清楚边界，比堆成功案例更能建立信任。这套打法有四条明确的局限："
    )
    lines.append("")
    lines.append(
        f"- **有 {rejected_count} 个环节明确不做**：数据在别人系统里、"
        "或动作出错会外部可见（对外可见动作交给专业人士）。"
        "劝退项写进报告并给前置动作，是交付价值的一部分，不是失败"
    )
    lines.append(
        "- **能力模式可复制，具体判据不可照搬**："
        "如库存÷销量的阈值是当前类目的经验值，换类目要重新标定"
    )
    lines.append(
        "- **AI 草拟强依赖数据源**：目标业务没有历史文本沉淀的环节，"
        "这套模式直接退回「诚实劝退」，不硬凑 AI"
    )
    lines.append(
        "- **时间轴是规划不是承诺**：波次顺序是先稳后难的决策，"
        "实际排期取决于客户侧数据就位速度"
    )
    lines.append("")
    lines.append(
        "更完整的局限清单见 [`limitations.md`](../limitations.md)。"
    )
    lines.append("")

    # ---- 怎么重新生成 ----
    lines.append("---")
    lines.append("")
    lines.append("## 这些文档怎么维护")
    lines.append("")
    lines.append(
        "五份文档 + 本合集页全部是**报告即代码**：内容由脚本从 `scenarios.yaml`、"
        "cassette、eval 实算生成，改数据源重跑即更新，不存在手写漂移。"
    )
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/gen_discovery_report.py    # 第 1 步")
    lines.append("python scripts/gen_solution_blueprint.py  # 第 2 步")
    lines.append("python scripts/gen_case_backtest.py       # 第 3 步")
    lines.append("python scripts/gen_expansion_matrix.py    # 第 4 步")
    lines.append("python scripts/gen_rollout_calendar.py    # 第 5 步")
    lines.append("python scripts/gen_delivery_handbook.py   # 本合集页（需前五份先生成）")
    lines.append("```")
    lines.append("")
    lines.append(
        "`make verify` 会校验全部文档的交叉引用有效性 —— "
        "五份文档任一缺失或改名，合集页的指针会立刻报错，不会静默失效。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "> 本合集页由 `scripts/gen_delivery_handbook.py` 自动生成。"
        "统计数字从 `diagnosis.py` 实算；各文档摘要行由对应产物实读，"
        "不手写。改文档链后重跑 "
        "`python scripts/gen_delivery_handbook.py` 即可更新。"
    )
    return "\n".join(lines)


def main() -> int:
    results = diagnose_all(load_scenarios())
    OUT.write_text(render(results), encoding="utf-8")
    total, actionable, hours = _fact_block(results)
    print(f"✅ 已生成 {OUT}")
    print(f"   聚合 {len(DOCS)} 份交付文档（流程第 1-{len(DOCS)} 步）")
    print(f"   实算：评估 {total} 环节 / 建议投入 {actionable} / 劝退 {total - actionable}")
    print(f"   实算：可落地年省 {hours:.0f} 小时")
    return 0


if __name__ == "__main__":
    sys.exit(main())
