"""从 scenarios.yaml 加载场景清单。

用 PyYAML 解析，因为场景清单是**给人看也要给机器读**的资产：
直接在 YAML 里写业务依据与打分依据，交付时可以直接给客户看原文件。

YAML 不可用时降级到一个内置的最小清单，保证核心功能不因缺依赖而瘫。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .diagnosis import Scenario

SCENARIO_FILE = Path(__file__).parent.parent.parent / "diagnosis" / "scenarios.yaml"

try:  # pragma: no cover - 环境相关
    import yaml
except ImportError:  # pragma: no cover
    # PyYAML 缺失时降级到内置清单，保证诊断功能不瘫。
    # PyYAML 是可选增强：没有它也能跑，只是读不了外部 YAML。
    yaml = None  # type: ignore[assignment]


def _scenario_from_dict(raw: dict[str, Any]) -> Scenario:
    """把 YAML 的一条记录转成 Scenario。"""
    return Scenario(
        id=str(raw["id"]),
        name=str(raw["name"]),
        dimensions={
            "frequency": int(raw["frequency"]),
            "rule_clarity": int(raw["rule_clarity"]),
            "data_readiness": int(raw["data_readiness"]),
            "fault_tolerance": int(raw["fault_tolerance"]),
            "loss_impact": int(raw["loss_impact"]),
        },
        human_minutes_per_run=float(raw["human_minutes_per_run"]),
        runs_per_year=float(raw["runs_per_year"]),
        evidence=str(raw.get("evidence", "")).strip(),
        hard_reject=raw.get("hard_reject"),
        human_rank=int(raw["human_rank"]) if raw.get("human_rank") else None,
        notes=str(raw.get("notes", "")).strip(),
    )


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    """加载场景清单。"""
    target = path or SCENARIO_FILE
    if not target.exists():
        return _fallback_scenarios()
    if yaml is None:
        return _fallback_scenarios()

    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"{target} 顶层必须是列表"
        raise ValueError(msg)

    scenarios = [_scenario_from_dict(item) for item in raw]
    seen: set[str] = set()
    for s in scenarios:
        if s.id in seen:
            msg = f"场景 id 重复：{s.id}"
            raise ValueError(msg)
        seen.add(s.id)
        s.validate()
    return scenarios


def _fallback_scenarios() -> list[Scenario]:
    """缺 PyYAML 或文件缺失时的最小内置清单。

    保留 4 个代表性场景（含 1 个 D 象限），保证 `make diagnose` 不会因环境问题直接崩。
    """
    return [
        Scenario(
            id="ads_daily_report",
            name="广告日报汇总与异常标注",
            dimensions={
                "frequency": 5,
                "rule_clarity": 4,
                "data_readiness": 5,
                "fault_tolerance": 5,
                "loss_impact": 5,
            },
            human_minutes_per_run=90,
            runs_per_year=365,
            evidence="每日导出多份广告 CSV 人工合并，判据为 ACOS 阈值",
        ),
        Scenario(
            id="review_triage_draft",
            name="差评归因与回复草稿",
            dimensions={
                "frequency": 5,
                "rule_clarity": 2,
                "data_readiness": 4,
                "fault_tolerance": 4,
                "loss_impact": 4,
            },
            human_minutes_per_run=30,
            runs_per_year=365,
            evidence="差评文本口语化，归因需语义理解 —— LLM 擅长",
        ),
        Scenario(
            id="supplier_lead_time_tracking",
            name="供应链交期跟踪",
            dimensions={
                "frequency": 3,
                "rule_clarity": 3,
                "data_readiness": 0,
                "fault_tolerance": 3,
                "loss_impact": 3,
            },
            human_minutes_per_run=40,
            runs_per_year=156,
            hard_reject="no_data",
            evidence="交期数据在供应商系统，无历史结构化沉淀",
        ),
        Scenario(
            id="stockout_risk_alert",
            name="断货风险预警与通知",
            dimensions={
                "frequency": 5,
                "rule_clarity": 5,
                "data_readiness": 5,
                "fault_tolerance": 5,
                "loss_impact": 5,
            },
            human_minutes_per_run=20,
            runs_per_year=365,
            evidence="判据为库存÷日均销量 < 7 天，规则可写成公式",
        ),
    ]