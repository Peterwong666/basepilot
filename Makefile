.PHONY: help verify lint format-check fmt typecheck test eval live-smoke clean evidence docs docs-check troubleshoot diagnose adoption

# 直接用 .venv 里的二进制，不走 `uv run`：
#  1. mypy 2.x 直接 spawn 会失败，`python -m` 更稳
#  2. `uv run` 会先做 auto-sync，在文件被占用时会失败
#  3. RUFF_CACHE_DIR 指向 /tmp，避免沙箱下写 .ruff_cache 失败
PY  := .venv/bin/python
MYPY := $(PY) -m mypy
RUFF := $(PY) -m ruff
RUFF_ENV := RUFF_CACHE_DIR=/tmp/ruff_cache_basepilot

help:
	@echo "BasePilot —— 可用命令"
	@echo "  make verify      离线全量校验（lint + 格式 + 类型 + 测试 + 评测 + 文档），CI 跑这个"
	@echo "  make diagnose    生成业务诊断报告（四象限 + 劝退结论）"
	@echo "  make lint        ruff 静态检查 + 格式检查"
	@echo "  make fmt         ruff 自动修复 + 格式化"
	@echo "  make typecheck   mypy strict"
	@echo "  make test        pytest（全离线）"
	@echo "  make eval        评测：指标由代码实算，未实现项标 pending"
	@echo "  make docs        从代码生成排障 SOP"
	@echo "  make docs-check  校验文档链接与代码零漂移（CI 门禁）"
	@echo "  make troubleshoot 打印错误码处置速查（离线）"
	@echo "  make evidence    生成证据卡数字"
	@echo "  make adoption    促活三指标（覆盖率/SLA逾期率/采用率），出 Markdown 周报片段"
	@echo "  make live-smoke  连真实飞书租户跑全链路（D5 之后可用）"
	@echo "  make setup       安装依赖（首次或改动 pyproject 后）"

# 注意：`verify` 必须包含 `format-check`。
#踩过的坑：原本 verify 只跑 `ruff check`，本地全绿，
# 但 CI 里`ruff format --check` 红了 —— 本地漏检。
# 「本地能过」不等于「CI 能过」，门禁要跟CI 逐条对齐。
verify: lint format-check typecheck test eval docs-check
	@echo ""
	@echo "✅ verify 通过：lint + 格式 + 类型 + 测试 + 评测 + 文档校验 全部绿"

setup:
	uv sync --all-extras --dev

diagnose:
	@$(PY) scripts/diagnose.py

lint:
	@$(RUFF_ENV) $(RUFF) check src tests eval scripts

# 与 CI 的 `ruff format --check` 逐条对齐（缺了它本地会假绿）
format-check:
	@$(RUFF_ENV) $(RUFF) format --check src tests eval scripts

fmt:
	@$(RUFF_ENV) $(RUFF) check --fix src tests eval scripts
	@$(RUFF_ENV) $(RUFF) format src tests eval scripts

typecheck:
	@$(MYPY) src

test:
	@$(PY) -m pytest

eval:
	@$(PY) eval/runner.py

docs:
	@$(PY) scripts/gen_troubleshooting.py

docs-check:
	@$(PY) scripts/check_doc_links.py
	@$(PY) scripts/gen_troubleshooting.py --check

troubleshoot:
	@.venv/bin/basepilot-mcp troubleshooting

evidence:
	@$(PY) scripts/gen_evidence.py

live-smoke:
	@$(PY) scripts/live_smoke.py $(APP) $(TBL)

adoption:
	@$(PY) scripts/adoption.py --app $(APP) --table $(TBL) \
		--key-field $(KEY) --baseline $(BASELINE) $(EXTRA)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true