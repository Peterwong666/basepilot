# 贡献指南

感谢贡献。本项目是「约束治理」导向的 MCP Server，**门禁比代码多是有意的** ——
每一个门禁都对应一次真实踩坑（见各测试文件的 docstring）。贡献前请先读
`docs/PROJECT_RETROSPECTIVE.md` 了解项目脉络。

## 本地开发

```bash
git clone https://github.com/Peterwong666/basepilot.git
cd basepilot
uv sync                    # 或 make setup（需要 Python 3.11+）
cp .env.example .env       # 仅 live-smoke / 录制 cassette 需要真实凭证
```

## 提交前门禁（必须全绿）

```bash
make verify
```

一条命令跑完 CI 的全部检查：**ruff lint + ruff format --check + mypy strict +
pytest（全离线）+ eval 实算 + 文档链接/漂移校验**。CI 跑的就是这一套，
「本地能过」不等于「CI 能过」的情况已被门禁对齐，不要绕过单跑 pytest。

几条硬约束：

- **测试全离线**：新增测试不得访问真实飞书 API。用 `httpx.MockTransport` /
  respx 或 cassette 重放（`tests/cassettes/`）。
- **mypy strict**：`src/` 下不允许隐式 Any、缺类型标注。
- **README 数字口径**：测试总数、错误码条数等由 `tests/test_readme_honesty.py`
  机器锁定。你的改动若增减了测试或错误码规则，门禁会失败并提示同步 README ——
  照做即可，不要改门禁来迁就文档。
- **凭证零入库**：`tests/test_no_secrets_in_repo.py` 扫描全部入库文件，
  检出真实 app_id / app_token / table_id / record_id / `.env` 即失败
  （占位符如 `cli_xxxxxxxxxxxx` / `tblxxxxxxxxxxxx` 是允许的）。

## 录制新 cassette（真实 API 交互回放）

cassette 让真实租户的 API 交互在 CI 离线可重放，是本项目的核心测试资产。
为新场景录制时：

1. 在 `.env` 配好真实凭证与目标表（`BASEPILOT_APP_ID` / `BASEPILOT_APP_SECRET` /
   `BASEPILOT_APP_TOKEN` / `BASEPILOT_TABLE_*`）。
2. 参考 `scripts/record_cassette.py`：用 `basepilot.cassette.RecordingTransport`
   包住 `httpx.AsyncHTTPTransport`，并把 `app_secret` 传入 `secrets=` 参数 ——
   **录制阶段就脱敏**，不要录完再手工改。
3. 探测数据用显眼的一次性标记（如 `__CASSETTE_PROBE__`），跑完在脚本里自动清理，
   不在客户/自己租户留垃圾。
4. 产物写入 `tests/cassettes/*.jsonl`。若是补强脱敏能力之前录制的存量文件，
   跑 `python scripts/scrub_cassettes.py` 做二次清洗（幂等）。
5. 提交前自查：cassette 里不得出现任何真实租户标识符。脱敏规则
   （`cassette.redact_identifiers`）会抹平 app_id / app_token / table_id /
   record_id 但**保留结构差异**，这样重放时的 path 断言仍然有校验力 ——
   不要为了过门禁把断言能力洗没。
6. 重放测试写法参考 `tests/test_cassette_replay.py`。

## 提交与 PR

- commit message 用英文（`feat:` / `fix:` / `docs:` / `test:` / `chore:` 前缀），
  正文说清「为什么」，不只是「做了什么」。
- PR 描述勾完模板里的 checklist（含 `make verify` 全绿）。
- 改动了用户可见行为（CLI、工具参数、返回值结构）时，同步更新 README 与
  相关 `docs/`。
