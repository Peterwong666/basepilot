"""交付操作工具 —— dry_run 预演 + diagnose 业务诊断。

这两个工具是「做过交付」和「只调过 API」的分水岭：

- **dry_run**：真正执行前预演一遍。客户最怕的是"AI 一个手滑
  把 2000 条记录写错了"。dry_run 走完整条调用链（字段编码/校验/
  分片）但**不发真实写请求**，只告诉你"如果执行会发生什么"。
  指标：dry_run 时真实 HTTP 写调用数 = 0。

- **diagnose**：业务诊断打分器的工具化。客户问"我这堆流程哪些
  值得上 AI"，不用拍脑袋，跑一遍打分器出四象限图。
"""

from __future__ import annotations

from typing import Any

from ..client import BitableClient
from ..coerce import CoerceError, coerce_record
from ..diagnosis import QUADRANT_LABEL, QUADRANT_STRATEGY, diagnose_all
from ..scenarios_loader import load_scenarios


async def dry_run_create(
    client: BitableClient,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """预演批量新增 —— 走完整校验但**不写真实数据**。

    真正执行 create_records 之前先跑这个，确认：
    - 每条记录的字段能不能编码成功（字段类型/格式）
    - 会分几片（超过 1000 条自动分片）
    - 哪些字段是系统只读会被拒

    dry_run 不会发任何写请求，只读字段元信息。
    返回每条记录的预演结果 + 汇总会发生什么。

    Args:
        records: 准备新增的记录列表。
    """
    from ..config import BATCH_CREATE_MAX

    meta = await client.list_fields(app_token, table_id)

    per_record: list[dict[str, Any]] = []
    ok = 0
    failed = 0
    for i, rec in enumerate(records):
        try:
            encoded = coerce_record(meta, rec)
            per_record.append({"index": i, "ok": True, "encoded": encoded})
            ok += 1
        except CoerceError as e:
            per_record.append({"index": i, "ok": False, "error": str(e)})
            failed += 1

    batches = (len(records) + BATCH_CREATE_MAX - 1) // BATCH_CREATE_MAX
    return {
        "dry_run": True,
        "would_write": False,
        "total": len(records),
        "ok": ok,
        "failed": failed,
        "batches": batches,
        "batch_size": BATCH_CREATE_MAX,
        "records": per_record,
        "hint": "预演通过后可调 create_records 真实执行；有 failed 的记录先修字段格式",
    }


async def diagnose_scenarios(
    client: BitableClient,
    scenarios_path: str | None = None,
) -> dict[str, Any]:
    """业务诊断 —— 哪些环节值得上 AI，跑一遍打分器出四象限。

    对客户说「我帮你诊断一下哪些流程值得自动化」，
    比「我会调飞书 API」有价值得多。

    返回按投入优先级排序的完整诊断：每个场景的
    可自动化指数、象限、落地形态、年省工时、业务依据。
    D 象限（不建议做）会明确标注劝退理由。

    Args:
        scenarios_path: 自定义场景清单 YAML 路径（默认用内置 15 个跨境场景）。
    """
    del client  # 签名与其它工具保持一致，本工具不联网
    from pathlib import Path

    path = Path(scenarios_path) if scenarios_path else None
    scenarios = load_scenarios(path)
    results = diagnose_all(scenarios)

    by_quadrant: dict[str, int] = {}
    for d in results:
        by_quadrant[d.quadrant.value] = by_quadrant.get(d.quadrant.value, 0) + 1

    return {
        "total_scenarios": len(results),
        "by_quadrant": by_quadrant,
        "results": [
            {
                "name": d.scenario.name,
                "score": round(d.score, 1),
                "quadrant": d.quadrant.value,
                "quadrant_label": QUADRANT_LABEL[d.quadrant],
                "strategy": QUADRANT_STRATEGY[d.quadrant],
                "annual_hours_saved": round(d.annual_hours_saved, 1),
                "priority": round(d.priority, 1),
                "reject_reason": d.reject_reason,
                "evidence": d.scenario.evidence,
            }
            for d in results
        ],
    }


__all__ = ["dry_run_create", "diagnose_scenarios"]
