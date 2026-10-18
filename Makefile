.PHONY: help verify lint fmt typecheck test eval live-smoke clean evidence docs docs-check troubleshoot

# mypy 2.x 在部分环境直接 spawn 会失败，用 `python -m` 更稳；
# RUFF_CACHE_DIR 指向 /tmp 避免沙箱下写 .ruff_cache 失败。
MYPY      := .venv/bin/python -m mypy
RUFF_ENV  := RUFF_CACHE_DIR=/tmp/ruff_cache_basepilot

help:
	@echo "BasePilot —— 可用命令"
	@echo "  make verify      离线全量校验（lint + 类型 + 测试 + 评测 + 文档），CI 跑这个"
	@echo "  make lint        ruff 静态检查"
	@echo "  make fmt         ruff 自动修复"
	@echo "  make typecheck   mypy strict"
	@echo "  make test        pytest（全离线）"
	@echo "  make eval        评测：指标由代码实算，未实现项标 pending"
	@echo "  make docs        从代码生成排障 SOP"
	@echo "  make docs-check  校验文档链接与代码零漂移（CI 门禁）"
	@echo "  make evidence    生成证据卡数字"
	@echo "  make live-smoke  连真实飞书租户跑全链路（D5 之后可用）"

verify: lint typecheck test eval docs-check
	@echo ""
	@echo "✅ verify 通过：lint + 类型 + 测试 + 评测 + 文档校验 全部绿"

lint:
	@$(RUFF_ENV) uv run ruff check src tests eval scripts

fmt:
	@$(RUFF_ENV) uv run ruff check --fix src tests eval scripts
	@$(RUFF_ENV) uv run ruff format src tests eval scripts

typecheck:
	@$(MYPY) src

test:
	@uv run pytest

eval:
	@uv run python eval/runner.py

docs:
	@uv run python scripts/gen_troubleshooting.py

docs-check:
	@uv run python scripts/check_doc_links.py
	@uv run python scripts/gen_troubleshooting.py --check

troubleshoot:
	@uv run basepilot-mcp troubleshooting

evidence:
	@uv run python scripts/gen_evidence.py

live-smoke:
	@uv run python scripts/live_smoke.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true