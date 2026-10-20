"""serve 子命令的传输参数传递测试（不起真实服务，全离线）。

**为什么锁这两个行为**：
1. 默认 stdio 必须保持 `server.run()` 裸调用 —— 新增远程传输不能改变
   存量用户（Claude Code / Cursor 本地接入）的启动行为，这是兼容性底线。
2. --transport/--host/--port/--path 必须原样传入 `server.run()` ——
   参数「解析了但没传下去」是 CLI 包装层最常见的静默失效。
"""

from __future__ import annotations

from typing import Any

import pytest

from basepilot import server as server_module


class _RecordingServer:
    """记录 run() 调用参数的假 FastMCP。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> _RecordingServer:
    """替换 build_server，拦截 serve 的启动调用（不依赖环境变量凭证）。"""
    fake = _RecordingServer()
    monkeypatch.setattr("basepilot.tools.build_server", lambda: fake)
    return fake


def test_serve_default_stdio_bare_run(fake_server: _RecordingServer) -> None:
    """默认 serve 必须是 stdio 裸调用，一个参数都不多带。"""
    assert server_module.main(["serve"]) == 0
    assert fake_server.calls == [{}]


def test_serve_http_transport_passthrough(fake_server: _RecordingServer) -> None:
    """--transport http 时 host/port/path 全部透传给 server.run()。"""
    rc = server_module.main(["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "3000"])
    assert rc == 0
    assert fake_server.calls == [
        {"transport": "http", "host": "0.0.0.0", "port": 3000, "path": None}
    ]


def test_serve_sse_with_custom_path(fake_server: _RecordingServer) -> None:
    """sse 走同一套远程参数；--path 自定义挂载点。"""
    rc = server_module.main(["serve", "--transport", "sse", "--path", "/events"])
    assert rc == 0
    assert fake_server.calls == [
        {"transport": "sse", "host": "127.0.0.1", "port": 8000, "path": "/events"}
    ]


def test_serve_streamable_http_explicit(fake_server: _RecordingServer) -> None:
    """streamable-http 显式写法与 http 别名同效，参数照传。"""
    rc = server_module.main(["serve", "--transport", "streamable-http", "--port", "9000"])
    assert rc == 0
    assert fake_server.calls[0]["transport"] == "streamable-http"
    assert fake_server.calls[0]["port"] == 9000
