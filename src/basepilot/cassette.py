"""cassette —— 真实 HTTP 交互的录制与重放（JSONL 格式，零三方依赖）。

为什么不用 vcrpy：我们要对「请求体长什么样」做**断言级检查**
（比如文本字段写入是不是纯字符串），vcrpy 把交互封在黑盒里，
拿请求体要绕一层。自研 50 行换来完全的透明度和可注入性。

格式（JSONL，每行一次交互）：
    {"seq": 0, "method": "POST", "path": "/open-apis/.../tenant_access_token/internal",
     "request": {"json": {...}},          # 脱敏：app_secret 已替换
     "response": {"status": 200, "json": {...}}}  # 脱敏：token 已替换

脱敏原则（cassette 要入库，绝不泄密）：
- app_secret / tenant_access_token 一律替换为占位符
- record_id / open_id 保留（它们是演示资产的有机部分，且不含凭证）

录制：包一层 httpx.AsyncClient 的 transport，记所有 request/response。
重放：MockTransport 按 seq 顺序回包，断言请求与录制时一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

#: 占位符（入库的 cassette 里真实凭证都被换成这些，本身就是脱敏标记非密钥）
REDACTED_SECRET = "__REDACTED_APP_SECRET__"  # noqa: S105
REDACTED_TOKEN = "__REDACTED_TENANT_TOKEN__"  # noqa: S105


def _redact_json(obj: Any, secrets: set[str]) -> Any:
    """递归把 json 里的真实凭证值替换为占位符。"""
    if isinstance(obj, dict):
        return {k: _redact_json(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json(v, secrets) for v in obj]
    if isinstance(obj, str):
        for s in secrets:
            if s and s in obj:
                obj = obj.replace(s, REDACTED_TOKEN if s.startswith("t-") else REDACTED_SECRET)
        return obj
    return obj


class RecordingTransport(httpx.AsyncBaseTransport):
    """包一层真实 transport，把每次交互追加到 JSONL。"""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        cassette_path: Path,
        *,
        secrets: set[str] | None = None,
    ) -> None:
        self._inner = inner
        self._path = cassette_path
        self._secrets = secrets or set()
        self._seq = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        req_body: dict[str, Any] | None = None
        if request.content:
            try:
                req_body = json.loads(request.content)
            except (json.JSONDecodeError, UnicodeDecodeError):
                req_body = {"_raw": "<binary>"}

        # 追踪 token（它在响应里，录制时才能拿到真实值再脱敏）
        response = await self._inner.handle_async_request(request)
        # 流式响应必须先 read() 才能 .json()；读出后响应仍可被上层正常消费
        await response.aread()
        resp_json: dict[str, Any] | None = None
        try:
            resp_json = response.json()
        except (json.JSONDecodeError, ValueError):
            resp_json = {"_raw": "<non-json>"}

        # 如果这次响应里有 tenant_access_token，记下来后续脱敏
        if resp_json and "tenant_access_token" in resp_json:
            tok = str(resp_json["tenant_access_token"])
            if tok:
                self._secrets.add(tok)

        entry = {
            "seq": self._seq,
            "method": request.method,
            "path": request.url.path,
            "request": {"json": _redact_json(req_body, self._secrets)},
            "response": {
                "status": response.status_code,
                "json": _redact_json(resp_json, self._secrets),
            },
        }
        self._seq += 1

        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class ReplayTransport(httpx.MockTransport):
    """按 JSONL 顺序重放，断言请求与录制时一致。

    用法：
        replay = ReplayTransport.from_cassette(path)
        client = httpx.AsyncClient(transport=replay, base_url=...)
        # client 的每次请求都会先断言 method/path 一致，再回录制的响应
        assert replay.exhausted  # 所有录制的交互都被消费完
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries
        self._idx = 0
        self.request_log: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if self._idx >= len(self._entries):
                raise AssertionError(
                    f"重放越界：cassette 只有 {len(self._entries)} 条，"
                    f"却来了第 {self._idx + 1} 个请求 {request.method} {request.url.path}"
                )
            expected = self._entries[self._idx]
            self._idx += 1

            # 断言 method/path 与录制一致
            assert request.method == expected["method"], (
                f"seq={expected['seq']} method 不匹配："
                f"实发 {request.method} != 录制 {expected['method']}"
            )
            assert request.url.path == expected["path"], (
                f"seq={expected['seq']} path 不匹配："
                f"实发 {request.url.path} != 录制 {expected['path']}"
            )

            # 记录实发请求体（供测试断言「文本字段是不是纯字符串」）
            if request.content:
                try:
                    self.request_log.append(
                        {"seq": expected["seq"], "json": json.loads(request.content)}
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.request_log.append({"seq": expected["seq"], "json": None})

            resp = expected["response"]
            return httpx.Response(resp["status"], json=resp["json"])

        super().__init__(handler)

    @classmethod
    def from_cassette(cls, path: Path) -> ReplayTransport:
        entries = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(entries)

    @property
    def exhausted(self) -> bool:
        """所有录制的交互都被消费完（调多了/调少了都会暴露）。"""
        return self._idx == len(self._entries)


def make_replay_client(cassette_path: Path) -> httpx.AsyncClient:
    """从 cassette 建一个重放用 httpx.AsyncClient。"""
    return httpx.AsyncClient(
        transport=ReplayTransport.from_cassette(cassette_path),
        base_url="https://open.feishu.cn/open-apis",
    )


__all__ = [
    "REDACTED_SECRET",
    "REDACTED_TOKEN",
    "RecordingTransport",
    "ReplayTransport",
    "make_replay_client",
]
