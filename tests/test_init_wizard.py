"""init 凭证引导向导测试 —— 全离线（MockTransport + 假 input，无真实凭证）。

**锁四条路径**：
1. 凭证有效 + 表可达 → rc 0，输出两份 mcpServers JSON（含环境变量预填采用）
2. 凭证无效（token 端点 code != 0）→ rc 1 + 核对指引
3. table_id 错误（1254004 WrongTableId，FAIL_FAST 不重试）→ rc 1 + 规则表指引
4. 非 TTY → rc 2 + 非交互配置指引，且一个提示都不发起

为什么走注入而不是 respx：向导的 HTTP 层全部复用 TokenCache / BitableClient，
注入带 MockTransport 的 httpx.AsyncClient 即可完全离线 —— 与 eval/runner.py
实算指标用的是同一套手法。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from basepilot.init_wizard import NON_TTY_EXIT_CODE, run_wizard

#: 假答案串形态刻意短于敏感标识符的最小长度（见 tests/test_no_secrets_in_repo.py），
#: 防止测试自身触发发布前门禁。
_APP_ID = "cli_wizard"
_APP_SECRET = "sekrit"
_APP_TOKEN = "bascnWiz"
_TABLE_ID = "tblWiz1"

_TOKEN_OK = {"code": 0, "msg": "ok", "tenant_access_token": "t-wizard", "expire": 7200}
_FIELDS_OK = {
    "code": 0,
    "msg": "ok",
    "data": {"has_more": False, "items": [{"field_name": "状态", "type": 3}]},
}


def _handler_ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/tenant_access_token/internal"):
        return httpx.Response(200, json=_TOKEN_OK)
    if request.url.path.endswith("/fields"):
        return httpx.Response(200, json=_FIELDS_OK)
    return httpx.Response(500, json={"code": 500, "msg": "unexpected"})


def _handler_bad_credentials(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/tenant_access_token/internal"):
        return httpx.Response(200, json={"code": 10003, "msg": "invalid app_id or app_secret"})
    return httpx.Response(500, json={"code": 500, "msg": "unexpected"})


def _handler_wrong_table(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/tenant_access_token/internal"):
        return httpx.Response(200, json=_TOKEN_OK)
    if request.url.path.endswith("/fields"):
        return httpx.Response(200, json={"code": 1254004, "msg": "WrongTableId", "data": {}})
    return httpx.Response(500, json={"code": 500, "msg": "unexpected"})


def _fake_input(answers: list[str]) -> Callable[[str], str]:
    """按顺序吐出预置答案的假 input。"""
    it = iter(answers)
    return lambda _prompt: next(it)


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.feishu.cn/open-apis",
    )


def _run(
    input_answers: list[str],
    secret_answer: str,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[int, str]:
    """跑一次向导，返回 (退出码, 全部输出)。注入的 client 用完负责关。

    input_fn 与 secret_fn 是两条独立的输入流（真实环境下一个是 input、
    一个是 getpass），所以答案列表分开喂。
    """
    lines: list[str] = []
    client = _http(handler)
    try:
        rc = run_wizard(
            input_fn=_fake_input(input_answers),
            secret_fn=_fake_input([secret_answer]),
            out=lines.append,
            http_client=client,
            stdin_isatty=True,
        )
    finally:
        asyncio.run(client.aclose())
    return rc, "\n".join(lines)


def test_wizard_success_outputs_pasteable_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    """凭证有效 + 表可达 → rc 0，输出 uvx 与本地开发两份 mcpServers JSON。

    App ID 走环境变量预填（回车采用），其余手工输入 —— 两条取值路径都锁。
    """
    monkeypatch.setenv("BASEPILOT_APP_ID", _APP_ID)
    # App ID 回车 = 采用环境变量预填；app_token / table_id 手工输入
    rc, text = _run(["", _APP_TOKEN, _TABLE_ID], _APP_SECRET, _handler_ok)

    assert rc == 0
    assert "✅ 凭证有效" in text
    assert "✅ 数据表可达（1 个字段）" in text
    # 两份配置都在，且预填的 app_id 真正落进了 JSON
    assert '"mcpServers"' in text
    assert "git+https://github.com/Peterwong666/basepilot.git" in text
    assert "<clone 路径>" in text
    assert f'"BASEPILOT_APP_ID": "{_APP_ID}"' in text


def test_wizard_invalid_credentials_fails_with_guidance() -> None:
    """token 端点 code != 0 → rc 1，提示核对凭证，不再追问 table。"""
    rc, text = _run([_APP_ID], _APP_SECRET, _handler_bad_credentials)

    assert rc == 1
    assert "❌ 凭证校验失败" in text
    assert "code=10003" in text  # AuthError 透传飞书原始错误码
    assert "第 3/3 步" not in text  # 凭证挂了就不该往下走


def test_wizard_wrong_table_id_fails_with_rule_guidance() -> None:
    """1254004 WrongTableId（FAIL_FAST）→ rc 1，message 直接来自错误码规则表。"""
    rc, text = _run([_APP_ID, _APP_TOKEN, "tblNope1"], _APP_SECRET, _handler_wrong_table)

    assert rc == 1
    assert "✅ 凭证有效" in text  # 凭证这步是过的
    assert "❌ 数据表校验失败" in text
    assert "table_id 不正确" in text  # errors.py 规则表的客户指引，不是原始 msg


def test_wizard_non_tty_prints_guidance_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 TTY → rc 2 + 非交互配置指引，一个提示都不发、一个请求都不打。"""
    lines: list[str] = []

    def _boom(_prompt: str) -> str:
        raise AssertionError("非 TTY 下不应发起任何输入提示")

    def _boom_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        raise AssertionError("非 TTY 下不应创建 HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", _boom_client)  # type: ignore[assignment]
    rc = run_wizard(
        input_fn=_boom,
        secret_fn=_boom,
        out=lines.append,
        stdin_isatty=False,
    )

    text = "\n".join(lines)
    assert rc == NON_TTY_EXIT_CODE
    assert "非交互环境" in text
    assert "BASEPILOT_APP_ID" in text  # 指引里必须告诉用户环境变量名
