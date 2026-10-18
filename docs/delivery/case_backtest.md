# 案例回测：当初的预测，兑现了吗

> 生成日期：2026-10-18　|　回测案例：**4/4 兑现**　|　真实交互证据：**10 条**（cassette）　|　前置：`docs/delivery/solution_blueprint.md`

---

## 这份回测是什么

诊断（discovery_report）给的是**预测**，方案（solution_blueprint）给的是**承诺**；
这份回测回答的是客户最该问、也最难答的一句：**「凭什么信你？」**

做法是把当初写进诊断/方案/ADR 的每一条**可证伪预测**，
拿落盘的**真实证据**（cassette 录制的真实租户交互 + eval 压测实算）逐条对账：
预测说「会这样」，事实是不是「真这样」。

**回测的意义不在于全对，而在于「敢对账」。** 只讲预测、不回测的交付是单向输出；把预测摆出来让事实检验，才是可追责的工程。

## 回测总览

| # | 回测案例 | 当初预测来自 | 结果 |
|---|---|---|---|
| 1 | upsert 幂等：同键重复同步不产生重复记录 | tests/cassettes/cross_border_upsert.jsonl | ✅ 兑现 |
| 2 | 读结构≠写结构：文本按纯字符串写入零报错 | tests/cassettes/cross_border_upsert.jsonl | ✅ 兑现 |
| 3 | 字段编码：日期/单选/多选/URL 全部正确编码 | eval/reports/eval_report.json | ✅ 兑现 |
| 4 | 单表串行：同表并发写压到 1，重试全恢复 | eval/reports/eval_report.json | ✅ 兑现 |

---

## 逐条对账

### 1. upsert 幂等：同键重复同步不产生重复记录

- **当初的预测**：ADR-006 与蓝图验收标准预测：唯一键「存在即更新、不存在即新增」，重复跑不重复。
- **回测证据**：`tests/cassettes/cross_border_upsert.jsonl`（真实租户录制）
- **回测结果**：✅ **兑现**
- **实算明细**：cassette 录到 1 次批量新增、1 次批量更新，全程 HTTP/200、错误码 0。同键二次同步走 batch_update 而非再次 batch_create —— normalize_key 把读回的富文本数组归一成字符串键，upsert 幂等成立。

### 2. 读结构≠写结构：文本按纯字符串写入零报错

- **当初的预测**：ADR-006 预测：写入必须纯字符串（读回的富文本数组是另一套结构），否则 1254060。
- **回测证据**：`tests/cassettes/cross_border_upsert.jsonl`（真实租户录制）
- **回测结果**：✅ **兑现**
- **实算明细**：录制 2 次记录写路径（batch_create/batch_update），全部按「纯字符串」编码，未出现一次 1254060 TextFieldConvFail（code 恒 0）。这印证了「读结构≠写结构」不是文档想象，而是必须分侧处理的真坑。

### 3. 字段编码：日期/单选/多选/URL 全部正确编码

- **当初的预测**：ADR-004 预测：四写入口共享单一编码器，各字段类型都能正确编码。
- **回测证据**：`eval/reports/eval_report.json`（MockTransport 压测实算）
- **回测结果**：✅ **兑现**
- **实算明细**：黄金用例 19/19、字段编码正确率 100%、不安全写入拦截率 100%（7 类系统只读字段 fail-fast）。同一编码器喂四个写入口，预演与真实一致。

### 4. 单表串行：同表并发写压到 1，重试全恢复

- **当初的预测**：ADR-003 预测：per-table 锁把同表并发写压到 1，且不拖垮不同表吞吐。
- **回测证据**：`eval/reports/eval_report.json`（MockTransport 压测实算）
- **回测结果**：✅ **兑现**
- **实算明细**：200 并发压测下同表写峰值=1（串行成立），故障注入后重试成功率 100%。锁跟在版本维度（per-table_id），不全局串行 —— 不同表吞吐不受影响。

---

## 如果有预测没兑现

本次 4 条预测全部兑现。但这不构成「以后也会对」的承诺 ——
回测的价值在于**建立了对账机制**：场景包一改、cassette 一重录、
eval 一重跑，这份回测就会自动重算；哪条预测开始不兑现，会立刻暴露，
而不是等客户月底对账才发现。

## 回测和客户的关系

- **预测可证伪**：每条预测都写清「会这样」，留了被事实推翻的余地
- **证据可复算**：cassette / eval_report 都是机器产物，重跑一次就能重算，不靠嘴说
- **结论可追责**：兑现就是兑现，未兑现就归因 —— 这是 FDE 与「卖方案」的区别

---

> 本回测由 `scripts/gen_case_backtest.py` 自动生成，结论从 `tests/cassettes/cross_border_upsert.jsonl` 与 `eval/reports/eval_report.json` 实算，不手写。重录 cassette 或重跑 eval 后，执行 `python scripts/gen_case_backtest.py` 即可更新。