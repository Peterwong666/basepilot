"""make adoption —— 促活三指标一键计算（D12）。

把 weekly_ops.md 里「① 看促活指标（20 分钟）」的手动命令固化成一条命令。
输出 Markdown 周报片段，可直接贴进客户周报。

三个指标（与 delivery_playbook.md 步骤 4 的定义严格对齐）：

| 指标 | 定义 | 健康值 | 数据来源 |
|---|---|---|---|
| 台账覆盖率 | 有记录的去重 SKU / 基准 SKU 数 | >90% | search_records 拉全量 ÷ --baseline |
| SLA 逾期率 | 超期未闭环 / 总未闭环 | <15% | status_field≠闭环 且 date_field 早于 N 天前 |
| 采用率 | 本周活跃创建人 / 目标人数 | >70% | **需表含 User 字段 + --target-users**，否则 pending |

采用率为什么常是 pending：跨境三表（库存/广告/差评）没有 User 字段
跟踪「谁建的记录」，且「目标使用人数」是客户业务参数（运营团队几个人），
不是代码能猜的。**如实报 pending，不编造数字** —— 这是
troubleshooting.md「不猜、不编」原则在运营工具上的延伸。

用法：
    # 只用库存表算覆盖率（基准=客户 ERP 导出的 SKU 总数）
    python scripts/adoption.py --app Fx3mb... --table tblLWu... \\
        --key-field SKU --baseline 100

    # 加 SLA 逾期扫描（差评表，7 天 SLA）
    python scripts/adoption.py --app Fx3mb... --table tbleb5... \\
        --key-field 订单号 --baseline 50 \\
        --status-field 处理状态 --closed-value 已闭环 \\
        --date-field 差评日期 --sla-days 7

退出码：0 正常；2 参数/凭证缺失。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from basepilot.client import BitableClient  # noqa: E402
from basepilot.coerce import normalize_key  # noqa: E402


def _pct(part: int, whole: int) -> str:
    """百分比格式化，分母为 0 时如实返回 N/A（不编造 100% 或 0%）。"""
    if whole == 0:
        return "N/A（分母为 0）"
    return f"{part / whole * 100:.1f}%"


def _load_env() -> None:
    """同步读 .env（阻塞 IO 挪出 async 函数）。"""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


async def compute(args: argparse.Namespace) -> dict[str, object]:
    app_id = os.environ.get("BASEPILOT_APP_ID", "")
    app_secret = os.environ.get("BASEPILOT_APP_SECRET", "")
    if not app_id or not app_secret:
        raise SystemExit("缺少 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET（见 .env）")

    async with BitableClient(app_id, app_secret) as client:
        # ---------- 指标 1：台账覆盖率 ----------
        items = await client.search_records(args.app, args.table, field_names=[args.key_field])
        keys = {normalize_key((it.get("fields") or {}).get(args.key_field)) for it in items}
        keys.discard("")
        unique_count = len(keys)
        coverage = {
            "unique_keys": unique_count,
            "baseline": args.baseline,
            "ratio": _pct(unique_count, args.baseline),
            "healthy": (unique_count / args.baseline > 0.9 if args.baseline else None),
        }

        # ---------- 指标 2：SLA 逾期率（可选，需配 status/date 字段） ----------
        sla: dict[str, object] = {"status": "pending_config"}
        if args.status_field and args.date_field:
            now_ms = int(time.time() * 1000)
            threshold_ms = now_ms - args.sla_days * 86_400_000
            open_items = await client.search_records(
                args.app,
                args.table,
                field_names=[args.key_field, args.status_field, args.date_field],
            )
            total_open = 0
            overdue = 0
            for it in open_items:
                f = it.get("fields") or {}
                status = normalize_key(f.get(args.status_field))
                if status == args.closed_value:
                    continue
                total_open += 1
                ts = f.get(args.date_field)
                if isinstance(ts, (int, float)) and ts < threshold_ms:
                    overdue += 1
            sla = {
                "status": "computed",
                "sla_days": args.sla_days,
                "total_open": total_open,
                "overdue": overdue,
                "ratio": _pct(overdue, total_open),
                "healthy": (overdue / total_open < 0.15) if total_open else True,
            }

        # ---------- 指标 3：采用率（需 User 字段 + 目标人数，否则 pending） ----------
        adoption: dict[str, object] = {
            "status": "pending_config",
            "reason": (
                "需表含 User 字段跟踪创建人 + --target-users 业务参数；"
                "跨境三表默认无 User 字段，如实报 pending 不编造"
            ),
        }

    return {"coverage": coverage, "sla": sla, "adoption": adoption}


def render(args: argparse.Namespace, r: dict[str, object]) -> str:
    cov = r["coverage"]
    sla = r["sla"]
    ado = r["adoption"]
    lines = [
        "## 促活指标（make adoption）",
        "",
        f"- 表：`{args.table}`  唯一键：`{args.key_field}`",
        "",
        "| 指标 | 值 | 健康值 | 状态 |",
        "|---|---|---|---|",
    ]

    # 覆盖率
    cov_ok = cov["healthy"]
    cov_mark = "✅" if cov_ok else ("⚠️" if cov_ok is False else "—")
    lines.append(
        f"| 台账覆盖率 | {cov['unique_keys']}/{cov['baseline']} = {cov['ratio']} "
        f"| >90% | {cov_mark} |"
    )

    # SLA
    if sla["status"] == "computed":
        sla_mark = "✅" if sla["healthy"] else "⚠️"
        lines.append(
            f"| SLA 逾期率（{sla['sla_days']}天） | "
            f"{sla['overdue']}/{sla['total_open']} = {sla['ratio']} | <15% | {sla_mark} |"
        )
    else:
        lines.append("| SLA 逾期率 | 未配置 | <15% | ⏭️ 加 --status-field/--date-field 启用 |")

    # 采用率
    lines.append(f"| 采用率 | pending | >70% | ⏭️ {ado['reason']} |")
    return "\n".join(lines)


async def amain() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app", required=True, help="多维表格 app_token")
    p.add_argument("--table", required=True, help="数据表 table_id")
    p.add_argument("--key-field", required=True, help="唯一键字段名（如 SKU/订单号）")
    p.add_argument(
        "--baseline", type=int, default=0, help="应覆盖的基准条数（客户 ERP 导出的 SKU/订单总数）"
    )
    p.add_argument("--status-field", default=None, help="状态字段名（启用 SLA 扫描）")
    p.add_argument("--closed-value", default="已闭环", help="表示已闭环的状态值")
    p.add_argument("--date-field", default=None, help="日期字段名（启用 SLA 扫描）")
    p.add_argument("--sla-days", type=int, default=7, help="SLA 天数（默认 7）")
    args = p.parse_args()

    _load_env()
    result = await compute(args)
    print(render(args, result))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
