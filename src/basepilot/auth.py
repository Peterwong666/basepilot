"""tenant_access_token 服务端缓存与单飞刷新。

设计依据（飞书开放平台官方文档）
--------------------------------
- `tenant_access_token` 通过 app_id / app_secret 换取，响应含 `expire: 7200`（秒）。
- 官方明确说明：**剩余有效期小于 30 分钟时返回新 token，大于等于 30 分钟时返回原有 token**。

这两条事实直接决定了实现方式：

1. **必须服务端缓存**。每次业务请求都换一次 token 会立刻触发限流，而且毫无意义。
2. **刷新窗口必须落�� [30 分钟, 0] 区间内**。若在「剩余 > 30 分钟」时就刷新，
   官方会原样返回旧 token —— 这次调用白白消耗配额，token 却不会延长。
   所以 `TOKEN_REFRESH_THRESHOLD = 1800`（30 分钟）是官方文档给出的下界，不是随意取值。

为什么不直接用官方 SDK 的 `enable_token_cache`：
我们需要对「100 次业务请求只换 1 次 token」这条指标做**可断言的计数**，
自己实现才能在测试里mock 计数并写断言。见 ADR-001。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

import httpx

from .config import (
    AUTH_TOKEN_PATH,
    OPEN_API_BASE,
    TOKEN_REFRESH_THRESHOLD,
    TOKEN_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


class TokenFetcher(Protocol):
    """可替换的 token 获取器，便于测试注入。"""

    async def __call__(self) -> tuple[str, int]:  # pragma: no cover - 协议声明
        ...


class AuthError(RuntimeError):
    """鉴权失败。"""


class TokenCache:
    """带单飞锁的 token 缓存。

    并发场景下多个请求同时发现 token 即将过期时，只允许一个真正去换，
    其余等待并复用结果 —— 这是 `asyncio.Lock` 的核心用途（single-flight）。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        refresh_threshold: int = TOKEN_REFRESH_THRESHOLD,
        clock: Any = time.monotonic,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = http_client
        self._owns_client = http_client is None
        self._refresh_threshold = refresh_threshold
        self._clock = clock

        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

        # 观测指标：累计向飞书换取 token 的次数（评测指标之一）
        self.fetch_count = 0

    # -- 内部：真正发起换 token 请求 ----------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=OPEN_API_BASE, timeout=30.0)
        return self._client

    async def _fetch(self) -> tuple[str, int]:
        """向飞书换取新token，返回 (token, 有效期秒数)。"""
        client = self._ensure_client()
        self.fetch_count += 1

        payload = {
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }

        try:
            # 用绝对 URL：注入的 client 可能没有 base_url，
            # 而自己创建的 client 设了 base_url 也照样接受绝对 URL。
            resp = await client.post(f"{OPEN_API_BASE}{AUTH_TOKEN_PATH}", json=payload)
        except httpx.HTTPError as exc:
            raise AuthError(f"请求 tenant_access_token 失败：{exc}") from exc

        if resp.status_code != 200:
            raise AuthError(f"请求 tenant_access_token 失败：HTTP {resp.status_code}")

        body: dict[str, Any] = resp.json()

        # 飞书错误响应惯例：code != 0 表示失败，msg 给出原因
        code = body.get("code", 0)
        if code != 0:
            raise AuthError(f"获取 token 失败：code={code} msg={body.get('msg')}")

        token = body.get("tenant_access_token")
        if not token:
            raise AuthError("响应中缺少 tenant_access_token 字段")

        expire = int(body.get("expire", TOKEN_TTL_SECONDS))
        logger.info("已获取新的 tenant_access_token，有效期 %s 秒", expire)
        return str(token), expire

    # -- 对外：获取可用 token -------------------------------------------------

    async def get(self) -> str:
        """返回可用的 tenant_access_token，必要时先刷新。

        流程：
        -缓存命中且剩余有效期 >= 阈值 → 直接返回（零网络调用）
        - 需要刷新 → 持锁做 single-flight，其余协程复用同一结果
        """
        async with self._lock:
            now = self._clock()

            # 快路径：token 有效且未到刷新窗口
            if self._token is not None and (self._expires_at - now) >= self._refresh_threshold:
                return self._token

            # 慢路径：已持锁，向飞书换新 token
            token, expire = await self._fetch()
            self._token = token
            self._expires_at = self._clock() + expire
            return token

    async def remaining_ttl(self) -> int:
        """返回剩余有效秒数，供 `bitable_doctor` 体检展示。"""
        if self._token is None:
            return 0
        return max(0, int(self._expires_at - self._clock()))

    async def invalidate(self) -> None:
        """手动失效（如收到 401 时强制重取）。"""
        async with self._lock:
            self._token = None
            self._expires_at = 0.0

    async def aclose(self) -> None:
        """仅在内部创建了 client 时才关闭，避免影响注入的 client。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None