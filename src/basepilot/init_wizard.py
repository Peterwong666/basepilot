"""凭证引导向导 —— `basepilot-mcp init`。

交互式引导完成首次配置，解决「凭证从哪来、填到哪、怎么知道填对了」三个问题：

1. 输入 app_id / app_secret（`BASEPILOT_APP_ID` / `BASEPILOT_APP_SECRET`
   环境变量非空时作为预填默认值，回车直接采用）；
2. 调 `tenant_access_token` 端点验证凭证连通性 —— 这是飞书 OpenAPI
   最便宜的调用，复用 :class:`~basepilot.auth.TokenCache` 的换取链路
   （含 `code != 0` 的错误解析），不另造一套 HTTP 逻辑；
3. 输入 app_token + table_id，用字段列表接口（`describe_table` 的同款
   调用链）验证表可达，错误信息直接来自错误码规则表（如 1254004 WrongTableId）；
4. 输出可直接粘贴的 mcpServers JSON 配置（uvx 与本地开发各一份）。

无 TTY（CI / 管道）时不猜测：打印非交互配置指引并以退出码 2 退出。
所有依赖（input / 输出 / HTTP client）均可注入，测试用 MockTransport 完全离线。
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .auth import AuthError, TokenCache
from .client import BitableClient, FeishuAPIError

#: 非 TTY 环境的退出码 —— 与「凭证/表校验失败」的 1 区分开，便于脚本判断
NON_TTY_EXIT_CODE = 2

#: 飞书开放平台应用管理后台（创建自建应用 / 拿 App ID 的入口）
FEISHU_APP_CONSOLE = "https://open.feishu.cn/app"


@dataclass
class WizardAnswers:
    """向导收集到的四个值（app_secret 只会出现在最终 JSON 里，不回显日志）。"""

    app_id: str
    app_secret: str
    app_token: str
    table_id: str


async def verify_credentials(
    app_id: str, app_secret: str, *, http_client: httpx.AsyncClient | None = None
) -> None:
    """用 tenant_access_token 端点验证凭证（仓库里最便宜的飞书调用）。

    凭证无效时抛 :class:`~basepilot.auth.AuthError`。
    """
    cache = TokenCache(app_id, app_secret, http_client=http_client)
    try:
        await cache.get()
    finally:
        await cache.aclose()


async def verify_table(
    answers: WizardAnswers, *, http_client: httpx.AsyncClient | None = None
) -> int:
    """用 list_fields（describe_table 同款调用链）验证表可达，返回字段数。

    table_id 错误 / 无权限时抛 :class:`~basepilot.client.FeishuAPIError`，
    message 已是错误码规则表给出的客户可执行指引。
    """
    async with BitableClient(answers.app_id, answers.app_secret, http_client=http_client) as client:
        fields = await client.list_fields(answers.app_token, answers.table_id)
    return len(fields)


def _prompt(
    input_fn: Callable[[str], str],
    label: str,
    env_name: str,
    *,
    mask_default: bool = False,
) -> str:
    """提示输入；环境变量非空时作为默认值（回车接受预填）。

    mask_default=True（用于 app_secret）时预填提示不回显真实值，
    避免向导把环境里的 secret 打到终端上。
    """
    default = os.environ.get(env_name, "").strip()
    hint = ""
    if default:
        hint = " [环境变量已配置，回车采用]" if mask_default else f" [{default}]"
    value = input_fn(f"{label}{hint}: ").strip()
    return value or default


def _mcp_config_snippets(answers: WizardAnswers) -> dict[str, dict[str, Any]]:
    """生成两份可直接粘贴的 mcpServers 配置。

    - uvx 形式：免安装，直接从 git 仓库拉起（PyPI 发布后可简化为 `--from basepilot`）；
    - 本地开发形式：clone 仓库后用 `uv run --directory` 跑 entry point。

    env 段只放 server 真正读取的 `BASEPILOT_APP_ID` / `BASEPILOT_APP_SECRET`
    （见 `tools/registry.py` 的 build_server）；app_token / table_id
    由 LLM 作为工具参数逐次传入，不属于进程级凭证。
    """
    env = {
        "BASEPILOT_APP_ID": answers.app_id,
        "BASEPILOT_APP_SECRET": answers.app_secret,
    }
    return {
        "uvx": {
            "mcpServers": {
                "basepilot": {
                    "command": "uvx",
                    "args": [
                        "--from",
                        "git+https://github.com/Peterwong666/basepilot.git",
                        "basepilot-mcp",
                        "serve",
                    ],
                    "env": env,
                }
            }
        },
        "local_dev": {
            "mcpServers": {
                "basepilot": {
                    "command": "uv",
                    "args": [
                        "run",
                        "--directory",
                        "<clone 路径>",
                        "basepilot-mcp",
                        "serve",
                    ],
                    "env": env,
                }
            }
        },
    }


def _print_non_tty_guidance(out: Callable[[str], None]) -> None:
    out("检测到非交互环境（stdin 不是 TTY），`basepilot-mcp init` 需要交互输入。")
    out("非交互配置方式：直接设置环境变量后运行 `basepilot-mcp serve`：")
    out("  export BASEPILOT_APP_ID=cli_xxx")
    out("  export BASEPILOT_APP_SECRET=xxx")
    out("或在 MCP 客户端配置的 mcpServers.env 段填入同名变量（见 README「快速开始」）。")


def run_wizard(
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
    out: Callable[[str], None] = print,
    http_client: httpx.AsyncClient | None = None,
    stdin_isatty: bool | None = None,
) -> int:
    """执行交互式向导，返回进程退出码（0 成功 / 1 校验失败 / 2 非 TTY）。

    依赖全部可注入：测试用 MockTransport + 假 input 完全离线。
    """
    isatty = sys.stdin.isatty() if stdin_isatty is None else stdin_isatty
    if not isatty:
        _print_non_tty_guidance(out)
        return NON_TTY_EXIT_CODE

    out("BasePilot 凭证引导 —— 三步拿到可粘贴的 MCP 配置\n")

    out("第 1/3 步：飞书自建应用凭证")
    out(f"  还没有应用？到 {FEISHU_APP_CONSOLE} 创建「企业自建应用」，")
    out("  开通多维表格权限（bitable:app）后在「凭证与基础信息」页拿 App ID / App Secret。")
    app_id = _prompt(input_fn, "App ID", "BASEPILOT_APP_ID")
    app_secret = _prompt(secret_fn, "App Secret", "BASEPILOT_APP_SECRET", mask_default=True)
    if not app_id or not app_secret:
        out("App ID / App Secret 不能为空。")
        return 1

    out("\n第 2/3 步：验证凭证连通性（tenant_access_token）")
    try:
        asyncio.run(verify_credentials(app_id, app_secret, http_client=http_client))
    except AuthError as exc:
        out(f"❌ 凭证校验失败：{exc}")
        out("请到飞书开放平台核对 App ID / App Secret（注意是企业自建应用，不是商店应用）。")
        return 1
    out("✅ 凭证有效")

    out("\n第 3/3 步：验证数据表可达（describe_table 同款调用链）")
    out("  app_token 与 table_id 从多维表格 URL 取：/base/<app_token>?table=<table_id>")
    app_token = _prompt(input_fn, "app_token", "BASEPILOT_APP_TOKEN")
    table_id = _prompt(input_fn, "table_id", "BASEPILOT_TABLE_ID")
    if not app_token or not table_id:
        out("app_token / table_id 不能为空。")
        return 1
    answers = WizardAnswers(
        app_id=app_id, app_secret=app_secret, app_token=app_token, table_id=table_id
    )
    try:
        field_count = asyncio.run(verify_table(answers, http_client=http_client))
    except FeishuAPIError as exc:
        out(f"❌ 数据表校验失败：{exc}")
        return 1
    out(f"✅ 数据表可达（{field_count} 个字段）")

    snippets = _mcp_config_snippets(answers)
    out("\n=== 配置就绪，粘贴到 MCP 客户端（Claude Code / Cursor）===")
    out("\n① uvx 形式（免安装，推荐分发给同事）：")
    out(json.dumps(snippets["uvx"], ensure_ascii=False, indent=2))
    out("\n② 本地开发形式（clone 仓库后，把 <clone 路径> 替换为实际路径）：")
    out(json.dumps(snippets["local_dev"], ensure_ascii=False, indent=2))
    out(
        "\n说明：env 段只含 server 真正读取的 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET；\n"
        f"app_token={answers.app_token} 与 table_id={answers.table_id} "
        "由 LLM 调用工具时作为参数传入。\n"
        "凭证只经本地环境变量传递，请勿提交进任何仓库。"
    )
    return 0


__all__ = [
    "NON_TTY_EXIT_CODE",
    "WizardAnswers",
    "run_wizard",
    "verify_credentials",
    "verify_table",
]
