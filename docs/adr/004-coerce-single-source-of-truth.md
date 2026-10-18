# ADR-004：字段适配是单一事实源，所有写入入口共享同一个 coerce

- **状态**：已接受
- **日期**：2026-10-18
- 相关：[ADR-003（单表串行）](003-serialization.md)、[ADR-006（读结构≠写结构）](006-read-write-schema-asymmetry.md)
- 证据：`src/basepilot/coerce.py`、`src/basepilot/client.py`、`src/basepilot/tools/ops.py`

## 背景

一个 MCP Server 里，「把 LLM 友好的输入转成飞书要求的格式」这件事，
会在**多个入口**被需要：

| 入口 | 什么时候触发 |
|---|---|
| `client.create_records` | 真实新增记录 |
| `client.update_records` | 真实更新记录 |
| `client.upsert_records` | batch_upsert 内部的 create/update 分支 |
| `tools.dry_run_create` | 预演：只校验不写入 |

如果每个入口自己实现一遍字段适配，会出现**经典的交付事故**：
「create 能写进去的日期格式，dry_run 说不能；upsert 走的编码和 create 不一样」——
**同一条记录，走不同入口得到不同结果**，客户无法预测行为。

## 决策

**`coerce.py` 是字段适配的唯一事实源（single source of truth）。**
所有写入入口**必须**调 `coerce_record()`，不允许任何入口自己拼字段格式：

```
create_records ─┐
update_records ─┼─→ coerce_record(fields_meta, record) ─→ 飞书格式
upsert_records ─┤        ↑
dry_run_create ─┘   唯一实现处
```

实测调用分布（grep 验证）：

| 能力 | 定义处 | 调用入口 |
|---|---|---|
| `coerce_record` | `coerce.py` | `client.py`（create/update/upsert）、`tools/meta.py`、`tools/ops.py`（dry_run） |
| `normalize_key` | `coerce.py` | `client.py`（upsert 键提取）、`tools/atomic.py`（batch_upsert） |
| `_serializer.run` | `serialization.py` | 仅 `client.py`（所有写请求统一过串行器） |

## 理由

### 理由一：行为可预测是交付底线

客户最怕的是「AI 一个手滑把 2000 条记录写错了」。
**可预测**的意思是：同一条记录，dry_run 说能写，create 就一定能写进去；
upsert 的编码结果和 create 完全一致。
这个承诺只有在「所有入口共享同一个编码器」时才成立。

### 理由二：修一次，全部入口免疫

「读结构≠写结构」的坑（ADR-006）就是这么根治的：
`normalize_key` 收进 `coerce.py` 后，`client.upsert_records` 和
`tools.batch_upsert` 自动免疫——不需要每个入口各自记得做归一化。
如果当时是四个入口各写一份键提取，这个 bug 要修四处，而且永远有一处会漏。

### 理由三：dry_run 的价值依赖单一事实源

dry_run 的全部价值在于「**预演结果和真实执行一致**」。
如果 dry_run 用一套编码、create 用另一套，预演就失去了意义。
eval 的 `dryrun_prediction_accuracy = 100%` 这个指标，
证明的正是「dry_run 和 create 走同一个 coerce」这件事。

## 反例（如果不这么做）

假设 `dry_run_create` 自己拼字段格式而不调 `coerce_record`：

- dry_run 说「这条记录能写」（它自己觉得格式对）
- create 实际执行被 `1254062` 拒（真实编码器认为不对）
- 客户在 dry_run 里看到的「安全」是假的——**预演成了安慰剂**

这就是为什么 dry_run 必须调 `coerce_record`，哪怕它「只是预演」。

## 验证方式

| 证据 | 锁什么 |
|---|---|
| `eval/runner.py::_measure_dryrun_prediction_accuracy` | dry_run 预测与真实 create 一致率 = 100% |
| `tests/test_tools.py` | dry_run 走完整编码链但不发真实写请求 |
| grep 调用分布 | `coerce_record` 只定义在 `coerce.py`，无第二处实现 |

## 会被问到的问题与回答

**"dry_run 不写入，为什么还要调真实编码器？模拟一下不行吗？"**

> 「不行。dry_run 的价值 = 预演结果和真实执行一致。
> 模拟一套编码逻辑，就是引入『两个实现』——它们什么时候漂移没人知道。
> dry_run 调 `coerce_record` 但不发 HTTP 写请求，
> 这样『能编码成功』和『不写数据』两件事同时为真。」

**"normalize_key 为什么也放 coerce.py？它不是编码。"**

> 「它是**解码**——把 API 读回的复合结构归一化成可比较的键。
> 编码（写入方向）和解码（读取方向）是同一个事实的两个方向：
> 文本字段写入是纯字符串、读回是富文本数组，这个不对称的认知
> 必须住在同一个模块里，否则 encode 改了 decode 不知道。」
