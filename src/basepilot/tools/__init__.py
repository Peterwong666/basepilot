"""MCP 工具层 —— 把五层引擎包装成 Claude Code / Cursor 可调用的工具。

设计原则：**工具是给 LLM 用的，参数必须自描述，返回值必须可直接读。**

每个工具的 docstring 就是给 LLM 看的说明书：
- 参数是什么、什么格式、什么单位
- 会碰哪些坑（字段类型、限流、权限）
- 返回值怎么解读

工具分三类：
- `meta`   元信息：list_tables / describe_table（写前必先 describe）
- `atomic` 原子读写：create / update / delete / search / batch_upsert
- `ops`    交付操作：dry_run（预演）+ diagnose（业务诊断）
"""

from __future__ import annotations

from .registry import build_server

__all__ = ["build_server"]
