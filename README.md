# BasePilot

> 面向企业交付的**飞书多维表格 MCP Server** —— 用 MCP 工具把多维表格变成
> Claude Code / Cursor 可**安全读写**的业务台账。

[![CI](https://github.com/Peterwong666/basepilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Peterwong666/basepilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## ⚠️ 当前进度（请先看这里）

这是一个**在建中**的项目。README 里每个指标都标注了是「已实测」还是「目标」，
**未实现的不会写成已达成** —— 这是本项目的铁律。

| 模块 | 状态 |
|---|---|
| 飞书约束常量（`config.py`） | ✅ 已完成，每个数值标注官方出处 |
| token 缓存（`auth.py`） | ✅ 已完成，**100 请求换 1 次 token 已实测断言** |
| 错误码处置（`errors.py`） | ✅ 已完成，**32 条规则**，含客户现场指引 |
| 接口分桶限流（`ratelimit.py`） | ✅ 已完成 |
| 交付文档（4 份） | ✅ 已完成，排障 SOP 由代码自动生成 |
| 字段编码适配（`coerce.py`） | ⏳ 建设中 |
| 客户端与并发控制（`client.py` / `serialization.py`） | ⏳ 建设中 |
| MCP 工具层（6 个工具） | ⏳ 建设中 |
| 业务诊断打分器（`diagnosis.py`） | ⏳ 建设中 |

**因此当前仓库还不能连真实飞书跑通。** `make verify` 可离线全绿，
`make live-smoke` 需要 D5 之后才有意义。

判断进度的方式：`uv run basepilot-mcp doctor`（会如实列出已实现与待实现项）。

---

## 这个项目解决什么问题

**场景**：中小企业已经在用飞书多维表格承载业务台账（库存、广告、差评跟进），
数据靠人工从 Seller Central / 广告后台导 CSV 再粘贴进去，每天 1-2 小时。
公司想上 AI，但第一件事就卡住了：

| 卡点 | 飞书返回 | 根因 |
|---|---|---|
| AI 给人员字段传了字符串 | `1254066` UserFieldConvFail | 必须是 `[{"id": "ou_xxx"}]` 数组对象 |
| AI 给日期字段传了秒级时间戳 | `1254064` DatetimeFieldConvFail | 必须是 **13 位毫秒**，差 1000 倍 |
| AI 给单选字段传了数组 | `1254062` SingleSelectFieldConvFail | 必须是**字符串**，不是数组 |
| AI 写得稍快一点 | `1254291` Write conflict | **同一数据表不支持并发写**，官方建议加 0.5-1 秒延迟 |

**这不是技术选型问题，是没有人把多维表格的真实约束包一层。**
业务等不了，AI 落地就停在这里 —— 这是很多"客户买过 AI 工具但没用起来"的真实原因。

BasePilot 就是那一层。

---

## 三个适配层（核心）

不是把 API 包装成工具，而是治理飞书的真实约束。

### 1. 鉴权层 —— token 缓存✅ 已实现

`tenant_access_token` 有效期 7200 秒。官方明确：**剩余有效期小于 30 分钟时返回新 token，
大于等于 30 分钟时返回原 token**。所以刷新窗口必须落在 `[0, 30min]` 区间内，
否则会拿到同一个 token，白白消耗配额。

实现：进程内缓存 + `asyncio.Lock` 单飞（并发下只换一次，其余复用）。

**实测指标：100 次业务请求 → 向飞书换 token 1 次。**
（`tests/test_auth.py::test_100_requests_fetch_token_once`，可复现）

### 2. 并发层 —— 单表写串行 ⏳ 建设中

官方错误码 `1254291` 的排查建议原文：「在接口与接口之间增加 **0.5 或 1 秒**的延迟」；
`1254607` 补充说明底层「基于版本维度的串行方式，**不支持并发**」。

规划实现：**per-`table_id` 的锁**（不是全局锁 —— 不同数据表之间仍可并行）+ 请求节流。

**目标指标：200 次压测下，单表最大并发写 = 1，`1254291` 计数 = 0。**
（`serialization.py` 与压测脚本尚未落地，故本项目**暂不声称达成**该指标）

### 3. 类型层 —— 字段编码适配 ⏳ 建设中

规划按 13 类字段自动编码为官方要求格式，并对**不可写字段 fail-fast**。

| type | 字段 | 正确格式 | 常见错误 |
|---|---|---|---|
| 3 | SingleSelect | `str` | ❌ 传数组 |
| 4 | MultiSelect | `list[str]` | |
| 5 | DateTime | **13 位毫秒** | ❌ 传秒级 |
| 7 | Checkbox | `bool` | ❌ 传 `"true"` |
| 11 | User | `[{"id": "ou_xxx"}]` | ❌ 传字符串 |
| 15 | Url | `{"link": "...", "text": "..."}` | ❌ 只传字符串 |
| 17 | Attachment | `[{"file_token": "..."}]` | ❌ 传本地路径 |
| 18/21 | 关联字段 | `list[str]`（record_id） | |
| 19/20/1001-1005/3001 | 公式/查找引用/创建时间等 | **拒绝写入** | ❌ 尝试写系统字段 |

设计原则：**入口宽容，出口严格** —— 允许 LLM 传 ISO 日期、秒级时间戳、单元素数组，
适配层内部统一转成官方格式。**LLM 出错的空间由适配层吃掉，而不是把 1254064 抛给客户。**

**目标指标：61 条黄金用例，字段编码正确率 100%。**
（`coerce.py` 尚未实现，故本项目**暂不声称达成**该指标）

---

## 交付层：给客户用的文档 ✅ 已交付

技术做得再好，客户不会用就是零。这部分**已完成**：

| 文档 | 内容 |
|---|---|
| `docs/delivery/delivery_playbook.md` | 客户现场 5 步交付手册：建应用 → 授权 → 建表 → 体检 → 培训陪跑 |
| `docs/delivery/troubleshooting.md` | 32 条错误码 → 现场动作对照表（**由 `errors.py` 自动生成，零漂移**） |
| `docs/delivery/client_training.md` | 给业务方的一页纸，不写代码也能用 |
| `docs/limitations.md` | 已知限制 + 3 个真实失败模式（单选传数组/日期传秒级/人员传字符串） |

---

## 快速开始

```bash
# 离线全量校验（lint + 类型 + 测试 + 评测，CI 也跑这个）
make verify

# 连真实飞书租户跑一遍全链路，输出 PASS/FAIL 表
make live-smoke
```

---

## 非目标（Non-goals）

**主动划边界比假装覆盖更可信。** 本项目**不做**：

- ❌ 删除整个多维表格（Base）
- ❌ 授予/变更权限
- ❌ OAuth 授权流程
- ❌ 直接发送飞书消息
- ❌ 事件订阅（长连接）—— roadmap 里写了设计要点与本期不做的原因

删除记录的工具有**双重护栏**：默认 `dry_run=true`，且须显式 `confirm=true` 才真删。
这是防LLM 幻觉批量删库的安全设计。

---

## 与官方 lark-mcp 的关系

官方 `@larksuiteoapi/lark-mcp` 把飞书 API 直出为 MCP 工具，覆盖度更广（40+ 工具）。
本项目**不做覆盖度竞争**，做**交付可靠性**：

| 能力 | 官方 lark-mcp | BasePilot |
|---|---|---|
| 单表写串行 + 节流 | ✗ | ✓ |
| 字段类型预检（dry-run） | ✗ | ✓ |
| 不可写字段拦截 | ✗ | ✓ |
| 错误码分类处置 + 现场指引 | ✗ | ✓ |
| 幂等键重生成 | 部分 | ✓ |
| 离线录制回放测试 | ✗ | ✓ |
| 业务语义工具（CSV 同步/ 风险标注 / 差评闭环） | ✗ | ✓ |
| 客户交付手册 + 排障 SOP | ✗ | ✓ |

详见 `docs/adr/005-why-not-wrap-official-lark-mcp.md`。

---

## 文档

| 文档 | 内容 |
|---|---|
| `docs/delivery/delivery_playbook.md` | 客户现场 5 步交付手册 |
| `docs/delivery/troubleshooting.md` | 错误码 → 现场动作排障 SOP（**由 `errors.py` 自动生成**） |
| `docs/delivery/client_training.md` | 客户培训手册（给业务方的一页纸） |
| `docs/limitations.md` | 已知限制与 badcase（含 3 个真实失败模式） |
| `docs/adr/` | 架构决策记录 |

---

## 许可

MIT