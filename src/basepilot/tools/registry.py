"""MCP Server 组装 —— 把工具挂到 FastMCP，注入共享的 BitableClient。

FastMCP 的工具是普通 Python 函数，docstring 自动作为给 LLM 看的
工具描述。这里用闭包把共享 client 绑进每个工具（`functools.partial`
不被 fastmcp 接受，必须用 def 包装），LLM 调用时只需传业务参数。
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from ..client import BitableClient
from . import atomic, meta, ops


def build_server(client: BitableClient | None = None) -> FastMCP:
    """组装 MCP Server。

    Args:
        client: 共享的 BitableClient。为 None 时从环境变量
            BASEPILOT_APP_ID / BASEPILOT_APP_SECRET 构造；
            测试时注入带 MockTransport 的 client。
    """
    mcp = FastMCP(
        name="basepilot",
        instructions=(
            "飞书多维表格交付工具箱。写记录前先用 describe_table 拿字段类型；"
            "真正写之前先用 dry_run_create 预演。"
        ),
    )

    if client is None:
        app_id = os.environ.get("BASEPILOT_APP_ID", "")
        app_secret = os.environ.get("BASEPILOT_APP_SECRET", "")
        if not app_id or not app_secret:
            raise RuntimeError(
                "缺少 BASEPILOT_APP_ID / BASEPILOT_APP_SECRET 环境变量。"
                "请在 .env 或环境中配置飞书自建应用凭证。"
            )
        client = BitableClient(app_id, app_secret)
    assert client is not None  # 窄化类型
    c = client

    # ---- 元信息 ----

    @mcp.tool
    async def describe_table(app_token: str, table_id: str) -> dict[str, Any]:
        """获取数据表的字段结构（写记录前必查）。

        返回每个字段的名称、type 编号、可读类型名、是否系统只读。
        用 type 编号做后续 create/update 的字段编码依据，不要凭字段名猜类型。

        Args:
            app_token: 多维表格的 app_token（URL 里 /base/ 后面那段）。
            table_id: 数据表 ID（URL 里 &table= 后面那段）。
        """
        return await meta.describe_table(c, app_token, table_id)

    # ---- 原子读写 ----

    @mcp.tool
    async def create_records(
        app_token: str, table_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """批量新增记录。

        字段值格式（重要，错了会被 1254062 拒）：
        - 文本：字符串；数字：数值
        - 单选：选项名字符串（不是数组），如 "正常"
        - 多选：字符串数组，如 ["A", "B"]
        - 日期：13 位毫秒时间戳，如 1674206443000（秒级会自动×1000）
        - 人员：open_id，如 "ou_xxxx"；关联：record_id 数组
        - 系统只读字段（公式/创建时间等）不能写
        建议先 describe_table 拿字段 type，真正写之前先 dry_run_create 预演。

        Args:
            records: 记录列表，每条 {字段名: 字段值}。超 1000 条自动分片。
        """
        return await atomic.create_records(c, app_token, table_id, records)

    @mcp.tool
    async def update_records(
        app_token: str, table_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """批量更新记录。每条含 {"record_id": ..., "fields": {...}}。

        Args:
            records: 更新列表，字段值格式同 create_records。
        """
        return await atomic.update_records(c, app_token, table_id, records)

    @mcp.tool
    async def delete_records(
        app_token: str, table_id: str, record_ids: list[str]
    ) -> dict[str, Any]:
        """批量删除记录。⚠️ 不可恢复，超 500 条自动分片。建议先 search 确认。

        Args:
            record_ids: 要删除的 record_id 列表。
        """
        return await atomic.delete_records(c, app_token, table_id, record_ids)

    @mcp.tool
    async def search_records(
        app_token: str,
        table_id: str,
        filter_: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        page_size: int = 500,
    ) -> dict[str, Any]:
        """查询记录（自动翻页）。

        Args:
            filter_: 飞书筛选表达式，如
                {"conjunction": "and", "conditions": [
                    {"field_name": "状态", "operator": "is", "value": ["异常"]}]}
            field_names: 只返回这些字段。
            page_size: 每页条数，最大 500。
        """
        return await atomic.search_records(
            c, app_token, table_id, filter_, field_names, page_size
        )

    @mcp.tool
    async def batch_upsert(
        app_token: str,
        table_id: str,
        records: list[dict[str, Any]],
        key_field: str,
    ) -> dict[str, Any]:
        """按键字段「存在即更新，不存在即新增」。

        跨境电商同步核心操作：按 SKU/订单号 等唯一键同步，避免重复创建。

        Args:
            records: 记录列表，每条必须含 key_field。
            key_field: 唯一键字段名，如 "SKU" / "订单号"。
        """
        return await atomic.batch_upsert(c, app_token, table_id, records, key_field)

    # ---- 交付操作 ----

    @mcp.tool
    async def dry_run_create(
        app_token: str, table_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """预演批量新增 —— 走完整校验但不写真实数据。

        真正执行 create_records 前先跑这个：确认每条字段能否编码成功、
        会分几片、哪些是系统只读会被拒。dry_run 不发任何写请求。

        Args:
            records: 准备新增的记录列表。
        """
        return await ops.dry_run_create(c, app_token, table_id, records)

    @mcp.tool
    async def diagnose_scenarios(scenarios_path: str | None = None) -> dict[str, Any]:
        """业务诊断 —— 哪些环节值得上 AI，跑打分器出四象限。

        对客户说「我帮你诊断哪些流程值得自动化」，比「我会调 API」有价值。
        返回按投入优先级排序的诊断：指数/象限/落地形态/年省工时/业务依据。

        Args:
            scenarios_path: 自定义场景清单 YAML 路径（默认内置 15 个跨境场景）。
        """
        return await ops.diagnose_scenarios(c, scenarios_path)

    return mcp


__all__ = ["build_server"]
