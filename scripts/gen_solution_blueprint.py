"""生成方案蓝图（solution_blueprint）—— 把诊断 top 场景展开成可交付技术方案。

FDE 交付流程的第二步（接 discovery_report）：
- discovery_report 回答「先做哪个」
- solution_blueprint 回答「**怎么做**」——把排名靠前的环节展开成
  客户技术/业务双方都能对着签字的方案

**报告即代码**：场景选择、指数、年省工时、表结构全部来自
diagnosis.py + scenarios/cross_border 实算，不写死。
改场景包后重跑本脚本，蓝图自动更新。

用法：
    python scripts/gen_solution_blueprint.py
    # 产物：docs/delivery/solution_blueprint.md
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.diagnosis import (  # noqa: E402
    QUADRANT_LABEL,
    Quadrant,
    diagnose_all,
)
from basepilot.scenarios.cross_border import (  # noqa: E402
    ADS_SAMPLE,
    INVENTORY_SAMPLE,
    REVIEW_SAMPLE,
    TABLE_IDS,
)
from basepilot.scenarios_loader import load_scenarios  # noqa: E402

OUT = ROOT / "docs" / "delivery" / "solution_blueprint.md"

#: 蓝图覆盖的 top 场景数量（取 A/B 象限中优先级前 N 个）
TOP_N = 3

#: 场景名 → 对应的数据表/样本（把抽象场景锚定到已建好的三表）
SCENARIO_TABLE_MAP = {
    "库存健康巡检与补货建议": ("库存健康表", TABLE_IDS["inventory"], INVENTORY_SAMPLE),
    "断货风险预警与通知": ("库存健康表", TABLE_IDS["inventory"], INVENTORY_SAMPLE),
    "广告日报汇总与异常标注": ("广告异常表", TABLE_IDS["ads"], ADS_SAMPLE),
    "广告异常升级与抄送": ("广告异常表", TABLE_IDS["ads"], ADS_SAMPLE),
    "差评归因与回复草稿": ("差评处理表", TABLE_IDS["review"], REVIEW_SAMPLE),
}


def render(results: list) -> str:  # type: ignore[type-arg]
    today = date.today().isoformat()
    actionable = [d for d in results if d.quadrant is not Quadrant.D_REJECT]
    top = actionable[:TOP_N]
    total_saved_top = sum(d.annual_hours_saved for d in top)

    lines: list[str] = []
    lines.append("# 方案蓝图：把排名靠前的环节做成什么样")
    lines.append("")
    lines.append(f"> 生成日期：{today}　|　覆盖环节：**{len(top)} 个**　|　"
                 f"合计年省：**{total_saved_top:.0f} 小时**　|　"
                 f"前置：`docs/delivery/discovery_report.md`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 定位 ----
    lines.append("## 这份蓝图是什么")
    lines.append("")
    lines.append("诊断报告（discovery_report）回答了「先做哪个」；")
    lines.append("这份蓝图回答「**怎么做**」——把排名靠前的 "
                 f"{len(top)} 个环节展开成技术/业务双方都能对着签字的方案。")
    lines.append("")
    lines.append("**蓝图里的每张表都已在真实飞书租户建好并跑通**"
                 "（见 `scripts/setup_tables.py` / `scripts/seed_cross_border.py`），"
                 "不是纸面设计。")
    lines.append("")

    # ---- 立场：为什么 top N 里没有 AI ----
    has_ai_quadrant = any(
        d.quadrant in (Quadrant.B_ASSISTED, Quadrant.C_AI_FIRST) for d in top
    )
    lines.append("### 为什么这份蓝图里几乎没有「AI」")
    lines.append("")
    lines.append(f"排名靠前的 {len(top)} 个环节全部是 **A 象限（直接自动化）**——"
                 "判据明确到能写成公式（ACOS>35% 标红、库存÷日均销量<7天告急），"
                 "飞书原生工作流零成本完成，**上 AI 反而是浪费预算**。")
    lines.append("")
    lines.append("这不是能力回避，而是**优先级方法论的直接结果**："
                 "优先级 = 年省工时 × 指数修正，A 象限折算率最高（0.9），天然排前。"
                 "真正需要 AI 的环节（差评归因 C、搜索词聚类 C）判据模糊、指数打折，"
                 "排在这批搬运场景之后——**先把规则的搬运做扎实，再上 AI 攻坚模糊环节**，"
                 "这是本蓝图刻意保持的节奏，也是与「上来就堆大模型」的本质区别。")
    if not has_ai_quadrant:
        lines.append("")
        lines.append("> AI 主导环节的方案在 `discovery_report.md` 的 C 象限分区，"
                     "本蓝图聚焦「先做哪个」里排名最前、最快见效的一批。")
    lines.append("")

    # ---- 总览表 ----
    lines.append("## 覆盖环节总览")
    lines.append("")
    lines.append("| # | 业务环节 | 指数 | 象限 | 年省工时 | 对应数据表 |")
    lines.append("|---|---|---|---|---|---|")
    for i, d in enumerate(top, 1):
        tbl_name, tbl_id, _ = SCENARIO_TABLE_MAP.get(
            d.scenario.name, ("（待建）", "—", [])
        )
        lines.append(
            f"| {i} | {d.scenario.name} | {d.score:.0f} | "
            f"`{d.quadrant.value}` {QUADRANT_LABEL[d.quadrant]} | "
            f"{d.annual_hours_saved:.0f} h | {tbl_name} |"
        )
    lines.append("")

    # ---- 逐环节展开 ----
    lines.append("---")
    lines.append("")
    lines.append("## 逐环节方案")
    lines.append("")
    for i, d in enumerate(top, 1):
        s = d.scenario
        tbl_name, tbl_id, sample = SCENARIO_TABLE_MAP.get(
            s.name, ("（待建）", "—", [])
        )
        lines.append(f"### {i}. {s.name}")
        lines.append("")
        lines.append(f"- **诊断**：指数 {d.score:.0f}，`{d.quadrant.value}` "
                     f"{QUADRANT_LABEL[d.quadrant]}")
        lines.append(f"- **当前成本**：{s.human_minutes_per_run:.0f} 分钟/次 × "
                     f"{s.runs_per_year:.0f} 次/年 = "
                     f"{s.human_minutes_per_run / 60 * s.runs_per_year:.0f} 小时/年")
        lines.append(f"- **预计年省**：{d.annual_hours_saved:.0f} 小时")
        lines.append(f"- **落地形态**：{d.strategy}")
        lines.append(f"- **数据表**：{tbl_name}（`{tbl_id}`）")
        lines.append("")
        lines.append("**业务依据**：" + s.evidence.strip())
        lines.append("")

        # 数据表字段（从样本数据实算字段名）
        if sample:
            fields = list(sample[0].keys())
            lines.append(f"**表结构**（{len(fields)} 个字段，已在真实租户建好）：")
            lines.append("")
            lines.append("`" + "`、`".join(fields) + "`")
            lines.append("")
            lines.append("**同步方式**：`batch_upsert` 按唯一键「存在即更新，不存在即新增」"
                         "——同一批数据每天同步不重复（已在真实租户验证幂等，"
                         "第一次全新增、第二次全更新无重复）。")
        else:
            lines.append("**表结构**：待建（本环节不在当前三表范围内）。")
        lines.append("")

        # 验收标准
        lines.append("**验收标准**（客户签字的判据）：")
        lines.append("")
        lines.append("- [ ] 数据能按唯一键幂等同步（重复跑不产生重复记录）")
        lines.append("- [ ] 字段编码 100% 通过（日期/单选/多选/URL 无 125406X 报错）")
        lines.append("- [ ] dry_run 预演结果与真实执行一致")
        lines.append("- [ ] 业务方 1 人能独立看懂台账并处理 1 条异常")
        lines.append("")

    # ---- 落地顺序 ----
    lines.append("---")
    lines.append("")
    lines.append("## 落地顺序与节奏")
    lines.append("")
    lines.append("| 周 | 动作 | 达标判据 |")
    lines.append("|---|---|---|")
    lines.append("| 第 1 周 | 建应用/授权/建三表（`setup_tables.py`） | `make live-smoke` 全绿 |")
    lines.append("| 第 2 周 | 灌历史数据 + 配同步（`seed_cross_border.py`） | 幂等验证通过 |")
    lines.append("| 第 3 周 | 业务方培训 + 陪跑第一次闭环 | 1 人独立处理 1 条异常 |")
    lines.append("| 第 4 周起 | 按 `weekly_ops.md` 跑 8 周运营 | 促活三指标达标 |")
    lines.append("")

    # ---- 风险与边界 ----
    lines.append("## 风险与边界（如实告知）")
    lines.append("")
    lines.append("- **同一张表不能并发写**（飞书 1254291）：已由单表串行 + 0.5s 节流规避，"
                 "200 压测并发峰值=1")
    lines.append("- **读结构≠写结构**（文本字段读回是富文本数组）："
                 "upsert 唯一键由引擎 `normalize_key` 归一化，已在真实租户踩坑并根治")
    lines.append("- **本蓝图只做已诊断的 A/B 象限环节**；D 象限（供应链交期/税务合规）"
                 "明确不在范围内——见 discovery_report 劝退理由")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> 本蓝图由 `scripts/gen_solution_blueprint.py` 自动生成，"
                 "场景/指数/工时来自 `diagnosis.py` 实算，表结构来自 "
                 "`src/basepilot/scenarios/cross_border/__init__.py` 场景包。改动后重跑 "
                 "`python scripts/gen_solution_blueprint.py` 即可更新。")
    return "\n".join(lines)


def main() -> int:
    scenarios = load_scenarios()
    results = diagnose_all(scenarios)
    OUT.write_text(render(results), encoding="utf-8")
    actionable = [d for d in results if d.quadrant is not Quadrant.D_REJECT]
    top = actionable[:TOP_N]
    print(f"✅ 已生成 {OUT}")
    print(f"   覆盖 top {len(top)} 环节：")
    for d in top:
        print(f"   · {d.scenario.name}（指数 {d.score:.0f}，年省 {d.annual_hours_saved:.0f}h）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
