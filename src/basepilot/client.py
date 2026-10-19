"""裸 httpx 客户端 —— 把 auth/errors/ratelimit/coerce/serialization 五层串成一条调用链。

为什么不直接用官方 SDK / lark-mcp，见 ADR-005。一句话：我们需要对
「限流 / 串行 / 字段适配 / 错误处置」做**可断言的计数与注入**，
包一层黑盒就拿不到这些抓手。

一次写请求的完整路径：

    调用方
      → coerce_record()        字段编码适配（入口宽容，出口严格）
      → serializer.run()       per-table 串行 + 0.5s 节流
      → limiter.acquire(WRITE) 令牌桶限流
      → token_cache.get()      拿/换 tenant_access_token（100 请求换 1 次）
      → httpx 真正发请求
      → errors 处置            命中规则表：重试 / 长退避 / 换幂等键 / fail-fast

读请求（search / field.list）不走串行器，只过限流与鉴权。
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from .auth import TokenCache
from .coerce import coerce_record, normalize_key
from .config import (
    BACKOFF_BASE,
    BATCH_CREATE_MAX,
    BATCH_DELETE_MAX,
    BATCH_UPDATE_MAX,
    BITABLE_FIELDS_PATH,
    BITABLE_RECORDS_PATH,
    LIST_MAX_PAGE_SIZE,
    OPEN_API_BASE,
    RETRY_MAX_ATTEMPTS,
    RETRYABLE_HTTP_STATUS,
    SEARCH_MAX_PAGE_SIZE,
)
from .errors import RULES, Action
from .ratelimit import Bucket, RateLimiter
from .serialization import WriteSerializer

logger = logging.getLogger(__name__)


class FeishuAPIError(RuntimeError):
    """飞书业务错误（HTTP 200 但 code != 0）。

    message 直接采用错误码规则表的客户可执行指引（若有），
    否则回退到飞书原始 msg。
    """

    def __init__(self, code: int, msg: str, *, http_status: int = 200) -> None:
        self.code = code
        self.raw_msg = msg
        self.http_status = http_status
        rule = RULES.get(code)
        guidance = rule.build_message() if rule else f"[{code}] {msg}"
        super().__init__(guidance)


class BitableClient:
    """多维表格客户端。

    所有依赖都可注入，测试用 MockTransport 完全离线。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        token_cache: TokenCache | None = None,
        limiter: RateLimiter | None = None,
        serializer: WriteSerializer | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=OPEN_API_BASE, timeout=30.0)
        self._token_cache = token_cache or TokenCache(app_id, app_secret, http_client=self._http)
        self._limiter = limiter or RateLimiter()
        self._serializer = serializer or WriteSerializer()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> BitableClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bucket: Bucket,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """带鉴权 + 限流 + 错误处置的一次请求（含可重试错误的退避重试）。"""
        attempt = 0
        last_error: FeishuAPIError | None = None

        while attempt < RETRY_MAX_ATTEMPTS:
            attempt += 1
            await self._limiter.acquire(bucket)
            token = await self._token_cache.get()
            resp = await self._http.request(
                method,
                path,
                json=json_body,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )

            # HTTP 层错误
            if resp.status_code != 200:
                if resp.status_code in RETRYABLE_HTTP_STATUS and attempt < RETRY_MAX_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise FeishuAPIError(resp.status_code, resp.text, http_status=resp.status_code)

            data: dict[str, Any] = resp.json()
            code = int(data.get("code", 0))
            if code == 0:
                result: dict[str, Any] = data.get("data", {})
                return result

            # 业务错误：查规则表决定处置
            err = FeishuAPIError(code, str(data.get("msg", "")), http_status=200)
            rule = RULES.get(code)
            action = rule.action if rule else Action.RETRY

            if action is Action.FAIL_FAST:
                raise err
            if action is Action.REGEN_IDEMPOTENCY:
                # 幂等键冲突：调用方应换 client_token 重试，这里直接抛由上层处理
                raise err
            if attempt >= RETRY_MAX_ATTEMPTS:
                raise err

            last_error = err
            if action is Action.LONG_BACKOFF:
                schedule = (3.0, 6.0, 12.0)
                await asyncio.sleep(schedule[min(attempt - 1, len(schedule) - 1)])
            else:  # RETRY
                await self._backoff(attempt)

        raise last_error or FeishuAPIError(-1, "unknown error")

    async def _backoff(self, attempt: int) -> None:
        # 退避抖动用 random 即可，非加密用途
        delay = BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.1)  # noqa: S311
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # 元信息
    # ------------------------------------------------------------------

    async def list_fields(self, app_token: str, table_id: str) -> dict[str, int]:
        """拉取表字段元信息，返回 {字段名: type 编号}。

        这是 coerce_record 的 fields_meta 来源。写记录前必须先调它，
        否则无法知道每个字段的类型。
        """
        path = BITABLE_FIELDS_PATH.format(app_token=app_token, table_id=table_id)
        fields: dict[str, int] = {}
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": LIST_MAX_PAGE_SIZE}
            if page_token:
                params["page_token"] = page_token
            data = await self._request("GET", path, bucket=Bucket.LIST, params=params)
            for item in data.get("items", []):
                fields[str(item["field_name"])] = int(item["type"])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return fields

    # ------------------------------------------------------------------
    # 记录写（走串行器）
    # ------------------------------------------------------------------

    async def create_records(
        self,
        app_token: str,
        table_id: str,
        records: list[dict[str, Any]],
        *,
        fields_meta: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """批量新增记录。

        - 先按 fields_meta 做字段编码（缺省自动拉取）
        - 超过 BATCH_CREATE_MAX 自动分片
        - 走 per-table 串行 + 限流
        """
        if not records:
            return {"created": 0, "record_ids": []}
        meta = fields_meta or await self.list_fields(app_token, table_id)

        created_ids: list[str] = []
        for start in range(0, len(records), BATCH_CREATE_MAX):
            chunk = records[start : start + BATCH_CREATE_MAX]
            body_records = [{"fields": coerce_record(meta, rec)} for rec in chunk]
            path = (
                BITABLE_RECORDS_PATH.format(app_token=app_token, table_id=table_id)
                + "/batch_create"
            )

            async def op(
                _path: str = path, _body: list[dict[str, Any]] = body_records
            ) -> dict[str, Any]:
                return await self._request(
                    "POST", _path, bucket=Bucket.WRITE, json_body={"records": _body}
                )

            data = await self._serializer.run(table_id, op)
            created_ids.extend(str(r["record_id"]) for r in data.get("records", []))
        return {"created": len(created_ids), "record_ids": created_ids}

    async def update_records(
        self,
        app_token: str,
        table_id: str,
        records: list[dict[str, Any]],
        *,
        fields_meta: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """批量更新记录。records 每项须含 record_id 与 fields。"""
        if not records:
            return {"updated": 0}
        meta = fields_meta or await self.list_fields(app_token, table_id)

        updated = 0
        for start in range(0, len(records), BATCH_UPDATE_MAX):
            chunk = records[start : start + BATCH_UPDATE_MAX]
            body_records = [
                {
                    "record_id": rec["record_id"],
                    "fields": coerce_record(meta, rec["fields"]),
                }
                for rec in chunk
            ]
            path = (
                BITABLE_RECORDS_PATH.format(app_token=app_token, table_id=table_id)
                + "/batch_update"
            )

            async def op(
                _path: str = path, _body: list[dict[str, Any]] = body_records
            ) -> dict[str, Any]:
                return await self._request(
                    "POST", _path, bucket=Bucket.WRITE, json_body={"records": _body}
                )

            data = await self._serializer.run(table_id, op)
            updated += len(data.get("records", []))
        return {"updated": updated}

    async def upsert_records(
        self,
        app_token: str,
        table_id: str,
        records: list[dict[str, Any]],
        key_field: str,
        *,
        fields_meta: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """按唯一键「存在即更新，不存在即新增」（跨境同步核心操作）。

        为什么键提取必须在引擎层：API 读回的文本字段是富文本数组
        ``[{"type":"text","text":...}]``，直接当 dict 键会
        ``TypeError: unhashable type``，``str(list)`` 又永远比对不上写入值。
        引擎统一用 :func:`normalize_key` 归一化，调用方不需要知道
        「读结构 ≠ 写结构」这个坑。

        Args:
            records: 记录列表，每条须含 key_field。
            key_field: 唯一键字段名，如 "SKU" / "订单号"。
            fields_meta: 可选，缺省自动拉取（create/update 会复用，只拉一次）。

        Returns:
            {"created": n, "updated": m, "skipped": k}
            skipped = 缺 key_field 而被跳过的记录数。
        """
        if not records:
            return {"created": 0, "updated": 0, "skipped": 0}

        meta = fields_meta or await self.list_fields(app_token, table_id)

        # 查出 key_field 已存在的记录 → {归一化键: record_id}
        found = await self.search_records(app_token, table_id, field_names=[key_field])
        existing: dict[str, str] = {}
        for item in found:
            k = normalize_key((item.get("fields") or {}).get(key_field))
            if k:
                existing[k] = str(item.get("record_id", ""))

        to_update: list[dict[str, Any]] = []
        to_create: list[dict[str, Any]] = []
        skipped = 0
        for rec in records:
            if key_field not in rec:
                skipped += 1
                continue
            kval = normalize_key(rec[key_field])
            if kval in existing:
                to_update.append({"record_id": existing[kval], "fields": rec})
            else:
                to_create.append(rec)

        result: dict[str, Any] = {"created": 0, "updated": 0, "skipped": skipped}
        if to_create:
            r = await self.create_records(app_token, table_id, to_create, fields_meta=meta)
            result["created"] = r["created"]
        if to_update:
            r = await self.update_records(app_token, table_id, to_update, fields_meta=meta)
            result["updated"] = r["updated"]
        return result

    async def delete_records(
        self, app_token: str, table_id: str, record_ids: list[str]
    ) -> dict[str, Any]:
        """批量删除记录。超过 BATCH_DELETE_MAX(500，保守值) 自动分片。"""
        if not record_ids:
            return {"deleted": 0}
        path = BITABLE_RECORDS_PATH.format(app_token=app_token, table_id=table_id) + "/batch_delete"

        deleted = 0
        for start in range(0, len(record_ids), BATCH_DELETE_MAX):
            chunk = record_ids[start : start + BATCH_DELETE_MAX]

            async def op(_path: str = path, _body: list[str] = chunk) -> dict[str, Any]:
                return await self._request(
                    "POST", _path, bucket=Bucket.WRITE, json_body={"records": _body}
                )

            await self._serializer.run(table_id, op)
            deleted += len(chunk)
        return {"deleted": deleted}

    # ------------------------------------------------------------------
    # 记录读（不走串行器）
    # ------------------------------------------------------------------

    async def search_records(
        self,
        app_token: str,
        table_id: str,
        *,
        filter_: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        page_size: int = SEARCH_MAX_PAGE_SIZE,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """查询记录，自动翻页。max_pages 防止一次调用打爆配额。"""
        path = BITABLE_RECORDS_PATH.format(app_token=app_token, table_id=table_id) + "/search"

        body: dict[str, Any] = {"page_size": min(page_size, SEARCH_MAX_PAGE_SIZE)}
        if filter_:
            body["filter"] = filter_
        if field_names:
            body["field_names"] = field_names

        items: list[dict[str, Any]] = []
        page_token: str | None = None
        pages = 0

        while pages < max_pages:
            if page_token:
                body["page_token"] = page_token
            data = await self._request("POST", path, bucket=Bucket.SEARCH, json_body=body)
            items.extend(data.get("items", []))
            pages += 1
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return items


__all__ = ["BitableClient", "FeishuAPIError"]
