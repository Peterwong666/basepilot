"""飞书 FDE 交付工具箱 —— MCP Server 组装与 CLI 入口。

CLI 子命令：
- `basepilot-mcp serve`         启动 MCP Server（默认 stdio，供 Claude Code/Cursor 接入；
  `--transport http/sse` 用于远程部署）
- `basepilot-mcp init`          凭证引导：交互式验证凭证与 table_id，生成 mcpServers 配置
- `basepilot-mcp doctor`        环境自检：当前能力与配置
- `basepilot-mcp troubleshooting` 错误码处置速查（离线）
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Literal

from . import __version__

#: serve 支持的传输协议（与 FastMCP 4.x 的 Transport 取值对齐：
#: http 是 streamable-http 的别名，sse 是旧版协议）
ServeTransport = Literal["stdio", "http", "sse", "streamable-http"]


def _cmd_serve(
    transport: ServeTransport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str | None = None,
) -> int:
    """启动 MCP Server（默认 stdio；http/sse 走远程传输）。"""
    from .tools import build_server

    server = build_server()  # 从环境变量读凭证
    if transport == "stdio":
        server.run()  # 裸调用：默认 stdio 行为与之前完全一致
        return 0
    server.run(transport=transport, host=host, port=port, path=path)
    return 0


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
            "implemented": [
                "describe_table",
                "create_records",
                "update_records",
                "delete_records",
                "search_records",
                "batch_upsert",
                "dry_run_create",
                "diagnose_scenarios",
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
    sub.add_parser(
        "init",
        help="凭证引导：交互式验证 app_id/app_secret 与 table_id，生成 mcpServers 配置",
    )
    serve = sub.add_parser(
        "serve",
        help="启动 MCP Server（默认 stdio，供 Claude Code/Cursor 接入）",
    )
    serve.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default="stdio",
        help="传输协议：stdio=本地接入（默认）；http=Streamable HTTP（streamable-http 的别名）；"
        "sse=旧版 SSE 协议",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP/SSE 监听地址（默认 127.0.0.1 仅本机；绑 0.0.0.0 前请确认有反代+鉴权）",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP/SSE 监听端口（默认 8000）",
    )
    serve.add_argument(
        "--path",
        default=None,
        help="HTTP/SSE 挂载路径（默认用 FastMCP 内置：http→/mcp/，sse→/sse/）",
    )

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "init":
        from .init_wizard import run_wizard

        return run_wizard()
    if args.command == "troubleshooting":
        return _cmd_troubleshooting()
    if args.command == "serve":
        return _cmd_serve(
            transport=args.transport,
            host=args.host,
            port=args.port,
            path=args.path,
        )

    parser.print_help()
    print("\n提示：启动 MCP Server 用 `basepilot-mcp serve`（需先配置 BASEPILOT_APP_ID/SECRET）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
