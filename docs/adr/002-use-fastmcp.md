# ADR-002：使用 FastMCP 而非裸 MCP SDK

- **状态**：已接受
- **日期**：2026-10-18

## 背景

MCP（Model Context Protocol）官方提供 Python SDK（`mcp` 包），
需要手工声明工具 schema、处理请求分发、维护会话状态。
`FastMCP` 是基于它的高层封装，用装饰器即可声明工具。

## 决策

**使用 FastMCP**，与 PawPilot 保持一致。

## 理由

### 1. 与既有项目技术栈一致

PawPilot（`github.com/Peterwong666/pawpilot`）已用 FastMCP 封装了 10 个业务工具。
BasePilot 沿用同一套模式，两个项目的工具声明代码风格一致，
维护成本低，也避免面试时被问"两个项目为什么用了两套框架"。

### 2. 工具 schema 自动导出

FastMCP 从函数签名与类型注解自动生成 MCP 工具 schema。
本项目的工具大量使用 Pydantic 模型作为参数（如 `BitableRef`、
`RecordWrite`），由 FastMCP 自动转换可少写大量胶水代码。

### 3. 装饰器声明，可读性强

```python
@mcp.tool
async def bitable_search_records(app_token: str, table_id: str, ...) -> dict:
    ...
```

对比裸 SDK 需要实现 handler 类、注册方法、描述 schema，
FastMCP 的声明更接近业务语义，代码审查时容易看懂。

## 代价

- FastMCP 是第三方封装，API 可能随版本变化。已在 `pyproject.toml` 锁定
  `fastmcp>=2.3`，并把「FastMCP API 变更」列为需盯的风险。
- 多一层抽象，排查 MCP 协议层问题时需要穿透FastMCP。
  缓解手段：`client.py` 的业务逻辑与FastMCP 解耦，
  MCP 层出问题时可直接用 `httpx` 层测试覆盖。

## 验证方式

工具层在 D8完成后用「真实租户全链路 smoke」验证：
建表 → 写 1000 条 → 查 → 更新 → 删 1 条。