# BasePilot

> 面向企业交付的**飞书多维表格 MCP Server** —— 用 MCP 工具把多维表格变成
> Claude Code / Cursor 可**安全读写**的业务台账。

[![CI](https://github.com/Peterwong666/basepilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Peterwong666/basepilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## ✅ 当前进度

**全部模块已完成，已在真实飞书租户跑通全链路。** 每个指标都由代码实算
（`make eval`），未实测的不会写成已达成 —— 这是本项目的铁律。

| 模块 | 状态 |
|---|---|
| 飞书约束常量（`config.py`） | ✅ 已完成，每个数值标注官方出处 |
| token 缓存（`auth.py`） | ✅ 已完成，100 请求换 1 次 token 已实测断言 |
| 错误码处置（`errors.py`） | ✅ 已完成，**34 条规则**，含客户现场指引 |
| 接口分桶限流（`ratelimit.py`） | ✅ 已完成 |
| 字段编码适配（`coerce.py`） | ✅ 已完成，13 类编码器 + `normalize_key` 解码 |
| 客户端与并发控制（`client.py` / `serialization.py`） | ✅ 已完成，200 压测单表并发=1 |
| MCP 工具层（**8 个工具**） | ✅ 已完成（FastMCP，stdio 可跑） |
| 业务诊断打分器（`diagnosis.py`） | ✅ 已完成，15 场景四象限 |
| cassette 录制/重放（`cassette.py`） | ✅ 已完成，真实交互 CI 可重放 |
| 跨境三表场景包（`src/basepilot/scenarios/cross_border/__init__.py`） | ✅ 已完成，真实租户幂等验证 |
| 交付文档（playbook/training/troubleshooting/weekly_ops） | ✅ 已完成，排障 SOP 由代码生成 |

**实测验证**：`make verify` 离线全绿（252 tests）；`make live-smoke APP=.. TBL=..`
连真实飞书跑通鉴权→建表→写入→读回→清理；跨境三表 `batch_upsert` 幂等
（第一次全新增，第二次全更新无重复）。

判断进度的方式：`uv run basepilot-mcp doctor`（如实列出已实现项）。

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

### 2. 并发层 —— 单表写串行 ✅ 已实现

官方错误码 `1254291` 的排查建议原文：「在接口与接口之间增加 **0.5 或 1 秒**的延迟」；
`1254607` 补充说明底层「基于版本维度的串行方式，**不支持并发**」。

实现：**per-`table_id` 的锁**（不是全局锁 —— 不同数据表之间仍可并行）+ 0.5s 请求节流，
主动规避 1254291 而不是撞上再重试。

**实测指标：200 次压测下，单表最大并发写 = 1，`1254291` 计数 = 0。**
（`tests/test_client.py::test_same_table_writes_are_serialized`，可复现）

### 3. 类型层 —— 字段编码适配 ✅ 已实现

按 13 类字段自动编码为官方要求格式，并对**不可写字段 fail-fast**。
另有 `normalize_key()` 解码：API 读回的文本字段是富文本数组、URL 是对象，
upsert 唯一键提取必须归一化，否则「已存在」判为「不存在」导致重复创建
（详见 `docs/adr/006-read-write-schema-asymmetry.md`）。

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

**实测指标：19 条黄金用例，字段编码正确率 100%，不可写拦截率 100%。**
（`eval/runner.py` 实算，`make eval` 可复现）

---

## 交付层：给客户用的文档 ✅ 已交付

技术做得再好，客户不会用就是零。这部分**已完成**：

| 文档 | 内容 |
|---|---|
| `docs/delivery/delivery_playbook.md` | 客户现场 5 步交付手册：建应用 → 授权 → 建表 → 体检 → 培训陪跑 |
| `docs/delivery/troubleshooting.md` | 34 条错误码 → 现场动作对照表（**由 `errors.py` 自动生成，零漂移**） |
| `docs/delivery/client_training.md` | 给业务方的一页纸，不写代码也能用 |
| `docs/delivery/weekly_ops.md` | 上线后 8 周运营手册（促活指标/追闭环/挖场景，`make adoption` 一键出周报） |
| **`docs/delivery/delivery_handbook.md`** | **交付手册合集页 —— 五份交付文档的入口：先读哪份 / 每份回答什么问题 / 哪些数字是算的** |
| `docs/limitations.md` | 已知限制 + 真实失败模式（单选传数组/日期传秒级/人员传字符串/读结构≠写结构） |

**FDE 交付方法论五连**（全部「报告即代码」：数字从 `diagnosis.py`/cassette/eval 实算，改源数据重跑自动更新，测试锁结构）：

> 入口从 **`docs/delivery/delivery_handbook.md`** 进 —— 它串起下面五份并标注每份的数字口径。

| 文档 | 回答 | 生成脚本 |
|---|---|---|
| `docs/delivery/discovery_report.md` | **先做哪个**（五维诊断 + 四象限 + 2 劝退） | `scripts/gen_discovery_report.py` |
| `docs/delivery/solution_blueprint.md` | **怎么做**（top3 环节展开成可签字方案） | `scripts/gen_solution_blueprint.py` |
| `docs/delivery/case_backtest.md` | **凭什么信你**（真实证据回测当初预测） | `scripts/gen_case_backtest.py` |
| `docs/delivery/expansion_matrix.md` | **能复制到哪**（15 场景归纳 4 种能力模式） | `scripts/gen_expansion_matrix.py` |
| `docs/delivery/rollout_calendar.md` | **按什么节奏铺**（4 波次先稳后难推广日历） | `scripts/gen_rollout_calendar.py` |

---

## 快速开始

```bash
# 离线全量校验（lint + 类型 + 测试 + 评测 + 文档校验，CI 也跑这个）
make verify

# 实算评测指标（并发峰值/重试成功率/dry-run 一致率等，全部 MockTransport 压测得出）
make eval

# 连真实飞书租户跑全链路（鉴权→建表→写入→读回→清理）
make live-smoke APP=<app_token> TBL=<table_id>

# 跨境三表场景包灌数（batch_upsert 幂等，可重复跑）
python scripts/seed_cross_border.py

# 促活三指标（覆盖率/SLA逾期率/采用率），出 Markdown 周报片段
make adoption APP=<app> TBL=<表ID> KEY=<唯一键> BASELINE=<基准数>
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
| `docs/delivery/weekly_ops.md` | 上线后 8 周运营手册（`make adoption` 一键出促活周报） |
| **`docs/delivery/delivery_handbook.md`** | **交付手册合集页（五份方法论文档的入口与数字口径表）** |
| `docs/delivery/discovery_report.md` | FDE 方法论①先做哪个（诊断报告，报告即代码） |
| `docs/delivery/solution_blueprint.md` | FDE 方法论②怎么做（方案蓝图） |
| `docs/delivery/case_backtest.md` | FDE 方法论③凭什么信你（案例回测） |
| `docs/delivery/expansion_matrix.md` | FDE 方法论④能复制到哪（可复制矩阵） |
| `docs/delivery/rollout_calendar.md` | FDE 方法论⑤按什么节奏铺（推广日历） |
| `docs/limitations.md` | 已知限制与 badcase（含真实失败模式） |
| `docs/adr/` | 架构决策记录（含 006「读结构≠写结构」——cassette 实证） |
| `tests/cassettes/` | 真实租户交互录制（脱敏），`test_cassette_replay.py` CI 重放 |
| `docs/PROJECT_RETROSPECTIVE.md` | **项目复盘及学习文档**：主要节点（问题→分析→解决）+ 结构分析，全面了解项目从这里入手 |

---

## 许可

MIT