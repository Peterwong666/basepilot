"""飞书 FDE 交付工具箱 —— MCP Server 组装。

当前状态：**工具层尚未实现**（计划 D5）。

这里先放一个可运行的最小入口，原因是 `pyproject.toml` 声明了
`basepilot-mcp = "basepilot.server:main"`，若文件不存在则
`pip install` 之后执行该命令会 ImportError —— 属于"承诺未兑现"。

D5 会把真实的 6 个MCP 工具挂到 `mcp` 实例上。
在那之前，本入口只提供自检与诊断命令，让仓库处于**可运行**状态。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__


def _cmd_doctor() -> int:
    """环境自检：告诉使用者当前能做什么、还差什么。"""
    from .config import BATCH_CREATE_MAX, TOKEN_REFRESH_THRESHOLD, WRITE_MIN_INTERVAL
    from .errors import RULES

    payload: dict[str, Any] = {
        "version": __version__,
        "feishu_constraints": {
            "batch_create_max": BATCH_CREATE_MAX,
            "write_min_interval_s": WRITE_MIN_INTERVAL,
            "token_refresh_threshold_s": TOKEN_REFRESH_THRESHOLD,
        },
        "error_rules": len(RULES),
        "tools": {
            "implemented": [],
            "planned": [
                "bitable_inspect_schema",
                "bitable_search_records",
                "bitable_create_records",
                "bitable_update_records",
                "bitable_delete_records",
                "bitable_upload_attachment",
            ],
        },
        "delivery_docs": [
            "docs/delivery/delivery_playbook.md",
            "docs/delivery/troubleshooting.md",
            "docs/delivery/client_training.md",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_troubleshooting() -> int:
    """打印错误码处置速查（离线，不需网络）。"""
    from .errors import RULES

    by_action: dict[str, int] = {}
    for rule in RULES.values():
        by_action[rule.action.value] = by_action.get(rule.action.value, 0) + 1

    print(f"飞书多维表格错误码处置规则（共 {len(RULES)} 条）\n")
    for action, count in sorted(by_action.items(), key=lambda kv: -kv[1]):
        print(f"  {action:<20} {count} 条")
    print("\n完整对照表见 docs/delivery/troubleshooting.md（由 errors.py 自动生成）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="basepilot-mcp",
        description="飞书 FDE 交付工具箱 —— 多维表格 MCP Server（工具层建设中）",
    )
    parser.add_argument("--version", action="version", version=f"basepilot {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="环境自检：当前能力与待实现项")
    sub.add_parser("troubleshooting", help="打印错误码处置速查")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "troubleshooting":
        return _cmd_troubleshooting()

    parser.print_help()
    print(
        "\n提示：MCP 工具层尚未上线（D5）。"
        "离线校验请用 `make verify`，连真实租户请用 `make live-smoke`。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())