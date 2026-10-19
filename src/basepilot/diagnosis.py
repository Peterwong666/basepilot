"""业务诊断：把"该不该上 AI"变成可计算、可复现的结论。

## 为什么这个模块存在

飞书 FDE 岗位的核心要求不是写接口，而是**在动手之前判断哪个环节值得投入**。
典型 JD 原文（负熵云 · 飞书官方认证服务商，2026-10-18 实采）：

> 「判断标准很实在：**高频、重复、耗人、又有足够数据喂给 AI 的环节**，
> 就是值得做的场景。」

这四句话本身就是四个评分维度。把它们做成打分器，就把"我懂业务"
从口头主张变成 CI 里可复现的数字 —— 这是本项目里**唯一无法被AI 替代**的部分。

## 五维打分

| 维度 | 权重 | 含义 | 为什么是这个权重 |
|---|---|---|---|
| `frequency` 高频 | 0.26 | 发生频率 | 决定"值不值"，是第一维度 |
| `rule_clarity` 规则明确 | 0.20 | 是否有清晰判据 | 规则明确 → 原生工作流就够，**不必上 AI** |
| `data_readiness` 有数据 | 0.20 | 是否有历史结构化数据 | 无数据 → 模型再强也学不会 |
| `fault_tolerance` 错得起 | 0.14 | 出错的代价可逆性 | 不可逆动作（改价/发消息给客户）必须降权 |
| `loss_impact` 损失规避 | 0.20 | **不做的代价** | 见下|

### 关于第五维 `loss_impact`：一个被自己的指标逼出来的维度

最初只有 JD 原文提到的四个维度（高频/重复/耗人/有数据）。但写完打分器后，
**秩相关检验自己暴露了方法的缺陷**（见 `tests/test_diagnosis.py`）：

| 场景 | 年可省工时 | 人工标注 | 模型原排序 |
|---|---|---|---|
| 客服工单分类与转派 | **213 h**（最高） | 第 9 位 | 第 3 位 |
| 断货风险预警与通知 | 122 h | **第 2 位** | 第 5 位 |

工时最省的不是最该先做的 —— 因为**"省时间"和"避损失"是两回事**。
断货在跨境业务里意味着 Listing 权重下滑 + 广告费白烧 + 排名重建，
一次可能损失数万元；而工单分类省下的时间，只是运营人员的键盘操作。

所以补了 `loss_impact`（不做的代价）。这不是为了凑指标，
而是**让模型能表达一个真实的业务事实**：防损型环节的价值不体现在工时上。

这也正是诊断报告要同时输出「指数」和「优先级」两个排序的原因。

## 四象限 → 落地形态

| 象限 | 条件 | 结论 | 落地形态 |
|---|---|---|---|
| **A** | 高频 + 高规则 + 高容错 | **直接自动化** | 飞书原生工作流即可，**不需要 AI** |
| **B** | 高频 + 高规则 + 低容错 | **AI 辅助 + 人工确认** | 工作流触发，AI 出草案，人工点确认 |
| **C** | 高频 + 低规则 + 有数据 | **AI 主导** | RAG / Agent + 引用溯源 |
| **D** | 低频 或 无数据 | **不做** | **明确劝退，写进报告** |

**D 象限是本模块最有价值的输出。** 一份只会说"都能做 AI"的诊断报告，
恰恰证明没诊断过；敢写"这个环节不建议做，因为月频且无历史结构化数据"
才是咨询底色。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

SCENARIO_FILE = Path(__file__).parent.parent.parent / "diagnosis" / "scenarios.yaml"

Score = Literal[0, 1, 2, 3, 4, 5]


class Quadrant(StrEnum):
    """四象限。"""

    A_AUTO = "A"
    B_ASSISTED = "B"
    C_AI_FIRST = "C"
    D_REJECT = "D"


QUADRANT_LABEL: dict[Quadrant, str] = {
    Quadrant.A_AUTO: "直接自动化",
    Quadrant.B_ASSISTED: "AI 辅助 + 人工确认",
    Quadrant.C_AI_FIRST: "AI 主导",
    Quadrant.D_REJECT: "不做（明确劝退）",
}

QUADRANT_STRATEGY: dict[Quadrant, str] = {
    Quadrant.A_AUTO: "飞书原生工作流即可，**不需要 AI** —— 上 AI 反而是浪费预算",
    Quadrant.B_ASSISTED: "工作流做触发，AI 生成草案，**人工点确认后才生效**",
    Quadrant.C_AI_FIRST: "RAG / Agent 主导，**必须带引用溯源**，便于人工复核",
    # D 象限的具体理由因场景而异（缺数据/ 不可逆 / 频率过低），
    # 由 `Scenario.reject_reason()` 提供，此处只给通用表述。
    Quadrant.D_REJECT: "**不建议投入** —— 见下方具体劝退理由",
}

#: 默认权重。顺序与 `Scenario.dimensions` 一致。
DEFAULT_WEIGHTS: dict[str, float] = {
    "frequency": 0.26,
    "rule_clarity": 0.20,
    "data_readiness": 0.20,
    "fault_tolerance": 0.14,
    "loss_impact": 0.20,
}

DIMENSION_LABEL: dict[str, str] = {
    "frequency": "高频",
    "rule_clarity": "规则明确",
    "data_readiness": "有数据",
    "fault_tolerance": "错得起",
    "loss_impact": "避损失",
}

#: 象限阈值（可自动化指数）
THRESHOLD_AUTO = 70.0
THRESHOLD_ASSISTED = 45.0

#: 规则明确度的「模糊线」：≤ 此值视为规则写不出来。
#: 低于或等于此值时，工作流无法胜任，必须 AI 主导（C 象限）——
#: 即使加权总分很高也不例外。理由见 `Scenario.quadrant`。
FUZZY_RULE_THRESHOLD = 2

#: 硬性劝退条件：出现任一则直接判D，不看总分。
#: 理由：再高频，没数据也白搭；再低频，一次性投入也收不回。
HARD_REJECT: dict[str, str] = {
    "frequency_zero": "该环节几乎不发生（低频），一次性投入无法收回",
    "no_data": "缺少历史结构化数据，模型无从学习/检索",
    "irreversible": "动作不可逆且出错代价外部可见",
}


class DiagnosisError(ValueError):
    """场景定义非法。"""


@dataclass(frozen=True)
class Scenario:
    """一个待评估的业务环节。"""

    id: str
    name: str
    #: 五维打分，键为 DEFAULT_WEIGHTS 的键，值 0-5
    dimensions: dict[str, int]
    #: 单次执行的人工耗时（分钟），用于测算收益
    human_minutes_per_run: float
    #: 年发生次数（365=日频，52=周频，12=月频，1=年频）
    runs_per_year: float
    #: 一手业务依据 —— 这个分数是凭什么给的
    evidence: str
    #: 可选的硬性劝退原因键，见 HARD_REJECT
    hard_reject: str | None = None
    #: 可选的人工优先级标注（1=最高），用于与打分器排序做相关性校验
    human_rank: int | None = None
    notes: str = field(default="")

    # -- 校验 ----------------------------------------------------------

    def validate(self) -> None:
        unknown = set(self.dimensions) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise DiagnosisError(f"{self.id}: 未知维度 {sorted(unknown)}")
        missing = set(DEFAULT_WEIGHTS) - set(self.dimensions)
        if missing:
            raise DiagnosisError(f"{self.id}: 缺少维度 {sorted(missing)}")
        for key, val in self.dimensions.items():
            if not isinstance(val, int) or not 0 <= val <= 5:
                raise DiagnosisError(f"{self.id}.{key}: 取值必须是 0-5 的整数，实际 {val!r}")
        if self.human_minutes_per_run < 0:
            raise DiagnosisError(f"{self.id}: human_minutes_per_run 不能为负")
        if self.runs_per_year < 0:
            raise DiagnosisError(f"{self.id}: runs_per_year 不能为负")
        if self.hard_reject is not None and self.hard_reject not in HARD_REJECT:
            raise DiagnosisError(
                f"{self.id}: 未知 hard_reject {self.hard_reject!r}，合法值 {sorted(HARD_REJECT)}"
            )

    # -- 评分 ----------------------------------------------------------

    def score(self, weights: dict[str, float] | None = None) -> float:
        """可自动化指数 = Σ(维度分/5 × 权重) / 权重和 × 100。"""
        w = weights or DEFAULT_WEIGHTS
        total_w = sum(w.values())
        if total_w <= 0:
            raise DiagnosisError("权重之和必须为正")
        acc = sum(self.dimensions[k] / 5 * w[k] for k in w)
        return acc / total_w * 100

    def quadrant(self, weights: dict[str, float] | None = None) -> Quadrant:
        """判定象限。

        **规则明确度是闸门，不是普通加权项。**

        这是本模块最关键的一条设计决策，理由很实际：
        飞书原生工作流只能做「条件明确 → 执行确定动作」的搬运。
        如果一个场景的判据本身是模糊的（比如给差评归因），
        那它**无论指数多高，都不可能靠工作流完成** ——
        必须用 AI。而如果只按加权总分判，它会因为「高频+有数据」拿到高分，
        误判进A 象限「不需要 AI」，这是逻辑上自相矛盾的。

        所以判定顺序是：
        1. 硬性劝退 → D
        2. 规则模糊（rule_clarity ≤ 2）→ C（必须 AI 主导）
        3. 其余按指数落 A / B
        """
        if self.hard_reject is not None:
            return Quadrant.D_REJECT

        # 闸门：规则写不出来 → 工作流做不了，只能 AI 主导
        if self.dimensions["rule_clarity"] <= FUZZY_RULE_THRESHOLD:
            return Quadrant.C_AI_FIRST

        s = self.score(weights)
        if s >= THRESHOLD_AUTO:
            return Quadrant.A_AUTO
        if s >= THRESHOLD_ASSISTED:
            return Quadrant.B_ASSISTED
        return Quadrant.C_AI_FIRST

    def priority_rank(self, weights: dict[str, float] | None = None) -> float:
        """投入优先级（越大越该先做）。

        **刻意不等于 `score`。**

        `score` 衡量的是「多适合自动化」（0-100 之间的可解释分数），
        优先级衡量的是「值多少、先做哪个」（用于排序的绝对量）。

        早期版本用 `score × annual_hours_saved`，
        但那样写是**尺度不变**的 —— 无论怎么调权重，乘积排序都可能不变，
        导致「调权重能改变优先级」这件事根本不成立（已被测试抓到）。
        改用「小时数为主、指数为修正」的形式，权重的变化才能真实传导到排序：

            priority = 年省工时 × (指数 / 100)

        指数在这里起的是**调节**作用：同样省 100 小时，
        一个"规则清晰、数据齐备、避损大"的场景（指数 95）
        会排在"规则模糊、只是频次高"的场景（指数 60）之前 ——
        前者落地更稳、误报更少。
        """
        return self.annual_hours_saved() * (self.score(weights) / 100.0)

    def annual_hours_saved(self) -> float:
        """一年能省的人工小时数。

        按象限给不同的折算率，理由是**人机分工不同**：

        | 象限 | 分工 | 折算率 |
        |---|---|---|
        | A 直接自动化 | 工作流全跑，人不参与 | 90%（仍需抽查） |
        | B AI 辅助+确认 | AI 出草案，人点确认 | 60% |
        | C AI 主导 | AI 做主体，人复核 | 50% |
        | D 不做 | —— | 0% |

        注意 A 象限不是 100%：自动化产物仍需抽查，
        **宣称"完全不用人"是不诚实的**。
        """
        total = self.human_minutes_per_run / 60 * self.runs_per_year
        factor = {
            Quadrant.A_AUTO: 0.9,
            Quadrant.B_ASSISTED: 0.6,
            Quadrant.C_AI_FIRST: 0.5,
            Quadrant.D_REJECT: 0.0,
        }[self.quadrant()]
        return total * factor

    def reject_reason(self) -> str | None:
        """劝退理由（仅 D 象限非空）。"""
        if self.hard_reject is None:
            return None
        return HARD_REJECT[self.hard_reject]


@dataclass(frozen=True)
class Diagnosis:
    """单个场景的完整诊断结论。"""

    scenario: Scenario
    score: float
    quadrant: Quadrant
    reject_reason: str | None
    annual_hours_saved: float
    priority: float = 0.0

    @property
    def strategy(self) -> str:
        return QUADRANT_STRATEGY[self.quadrant]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.scenario.id,
            "name": self.scenario.name,
            "score": round(self.score, 1),
            "quadrant": self.quadrant.value,
            "quadrant_label": QUADRANT_LABEL[self.quadrant],
            "strategy": self.strategy,
            "reject_reason": self.reject_reason,
            "annual_hours_saved": round(self.annual_hours_saved, 1),
            "priority": round(self.priority, 1),
            "dimensions": self.scenario.dimensions,
            "human_minutes_per_run": self.scenario.human_minutes_per_run,
            "runs_per_year": self.scenario.runs_per_year,
            "evidence": self.scenario.evidence,
        }


def diagnose(scenario: Scenario, weights: dict[str, float] | None = None) -> Diagnosis:
    """对单个场景做诊断。"""
    scenario.validate()
    return Diagnosis(
        scenario=scenario,
        score=scenario.score(weights),
        quadrant=scenario.quadrant(weights),
        reject_reason=scenario.reject_reason(),
        annual_hours_saved=scenario.annual_hours_saved(),
        priority=scenario.priority_rank(weights),
    )


def diagnose_all(
    scenarios: list[Scenario], weights: dict[str, float] | None = None
) -> list[Diagnosis]:
    """批量诊断，按**投入优先级**降序（不是按指数）。

    指数衡量「多适合自动化」，优先级衡量「值多少、先做哪个」。
    报告会同时给出两种排序 —— 这是诊断方法论的核心区别。
    """
    results = [diagnose(s, weights) for s in scenarios]
    return sorted(results, key=lambda d: d.priority, reverse=True)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def render_markdown(results: list[Diagnosis]) -> str:
    """生成 Markdown 诊断报告（可直接贴进交付文档）。"""
    lines: list[str] = []
    lines.append("# 业务诊断报告：哪个环节值得上 AI")
    lines.append("")
    lines.append(
        f"评估 **{len(results)} 个业务环节**。判断标准：高频、规则明确、有数据、错得起、避损失。"
    )
    lines.append("")
    lines.append(
        ">排序依据是**投入优先级**（年省工时 × 指数修正），不是单纯按指数 —— "
        "指数回答「能不能做」，优先级回答「先做哪个」。"
    )
    lines.append("")
    lines.append("| # | 业务环节 | 指数 | 象限 | 结论 | 年省工时 |")
    lines.append("|---|---|---|---|---|---|")
    for i, d in enumerate(results, 1):
        lines.append(
            f"| {i} | {d.scenario.name} | {d.score:.0f} | "
            f"`{d.quadrant.value}` {QUADRANT_LABEL[d.quadrant]} | "
            f"{d.strategy} | {d.annual_hours_saved:.0f} h |"
        )
    lines.append("")

    # 分象限汇总
    for q in Quadrant:
        group = [d for d in results if d.quadrant is q]
        if not group:
            continue
        lines.append(f"## 象限 {q.value} · {QUADRANT_LABEL[q]}（{len(group)} 个）")
        lines.append("")
        for d in group:
            lines.append(f"### {d.scenario.name}（指数 {d.score:.0f}）")
            lines.append("")
            if d.reject_reason:
                lines.append(f"- **劝退理由**：{d.reject_reason}")
            else:
                lines.append(f"- **落地形态**：{d.strategy}")
            lines.append(
                "- **五维打分**："
                + "、".join(f"{DIMENSION_LABEL[k]} {v}" for k, v in d.scenario.dimensions.items())
            )
            lines.append(
                f"- **当前成本**：{d.scenario.human_minutes_per_run:.0f} 分钟/次 × "
                f"{d.scenario.runs_per_year:.0f} 次/年 = "
                f"{d.scenario.human_minutes_per_run / 60 * d.scenario.runs_per_year:.0f} 小时/年"
            )
            if d.annual_hours_saved > 0:
                lines.append(f"- **预计年省**：{d.annual_hours_saved:.0f} 小时")
            lines.append(f"- **业务依据**：{d.scenario.evidence}")
            lines.append("")

    total_saved = sum(d.annual_hours_saved for d in results)
    actionable = [d for d in results if d.quadrant is not Quadrant.D_REJECT]
    lines.append("## 汇总")
    lines.append("")
    lines.append(
        f"- **建议投入**：{len(actionable)} 个环节"
        f"（排除 {len(results) - len(actionable)} 个不建议做的）"
    )
    lines.append(f"- **合计年省工时**：{total_saved:.0f} 小时")
    lines.append(
        f"- **优先起步**：{results[0].scenario.name}"
        if results and results[0].quadrant is not Quadrant.D_REJECT
        else "- **优先起步**：无（最高分场景仍在劝退名单内，需重新评估业务假设）"
    )
    lines.append("")
    lines.append(
        "> 象限 D 的存在不是失败。**主动排除一个不值得做的环节，"
        "比多做一个勉强上线的场景更负责** —— 这是本方法论的核心立场。"
    )
    return "\n".join(lines)


def render_quadrant_mermaid(results: list[Diagnosis]) -> str:
    """生成四象限图（Mermaid），用于诊断报告的可视化。"""
    lines = ["```mermaid", "quadrantChart", "    title 业务环节四象限（横轴：可自动化指数）"]

    buckets: dict[Quadrant, list[Diagnosis]] = {q: [] for q in Quadrant}
    for d in results:
        buckets[d.quadrant].append(d)

    def add(q: Quadrant, axis: str, max_score: float) -> None:
        for d in buckets[q]:
            label = f"{d.scenario.name} {d.score:.0f}"
            # 坐标值去掉浮点尾噪：82.4 而不是 82.40000000000001。
            # 直接写 repr 会把 IEEE754 的二进制误差暴露给读者，
            # 而这是交付物里最容易被截图传播出去的「不专业细节」。
            coord = round(min(d.score, max_score), 1)
            lines.append(f"    {axis} {coord:g}: {label}")

    add(Quadrant.A_AUTO, "A 直接自动化", 100)
    add(Quadrant.B_ASSISTED, "B AI辅助", 100)
    add(Quadrant.C_AI_FIRST, "C AI主导", 100)
    add(Quadrant.D_REJECT, "D 不做", 100)

    lines.append("```")
    return "\n".join(lines)


def render_json(results: list[Diagnosis]) -> str:
    """JSON 输出，供 MCP 工具消费。"""
    return json.dumps(
        {
            "weights": DEFAULT_WEIGHTS,
            "thresholds": {
                "auto": THRESHOLD_AUTO,
                "assisted": THRESHOLD_ASSISTED,
            },
            "total_annual_hours_saved": round(sum(d.annual_hours_saved for d in results), 1),
            "results": [d.to_dict() for d in results],
        },
        ensure_ascii=False,
        indent=2,
    )
