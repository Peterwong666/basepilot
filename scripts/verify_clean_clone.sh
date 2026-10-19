#!/bin/sh
# 在**干净 clone** 里跑 verify —— 提交前复现 CI 的真实环境。
#
# **为什么需要这个脚本**：本项目已经两次「本地绿、CI 红」：
#   1. `make verify` 漏了 `ruff format --check`（已修，但说明门禁会漂移）
#   2. `docs/limitations.md` 引用 `tests/contract/` —— 那是本机**空目录**，
#      git 不追踪空目录，所以本机校验通过、干净 checkout 里失效
#
# 第2 类问题只有干净环境能暴露 —— 本机有的文件（未追踪、gitignore、空目录）
# 不一定在仓库里。凡是「校验依赖文件是否存在」的门禁，都该在干净 clone 里验。
#
# 用法：
#   sh scripts/verify_clean_clone.sh          # 默认校验 origin/main
#   sh scripts/verify_clean_clone.sh HEAD     # 校验本地未推送的 commit

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${1:-origin/main}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "▶ 干净 clone $ROOT@$REF ..."
git clone --quiet --depth 1 --branch "$REF" "$ROOT" "$TMP/repo" 2>/dev/null ||
    git clone --quiet --depth 1 "$ROOT" "$TMP/repo"

cd "$TMP/repo"

# 关键：**不复用本机 .venv**。用 `uv sync` 在 clone 里装独立环境 ——
# 复用本机 venv 会掩盖「依赖声明缺失」「路径假设」这类只在干净环境
# 才暴露的问题（已踩过：门禁硬编码 .venv/bin/python，clone 里必然失败）。
echo "▶ 安装依赖（独立环境，不复用本机 venv）..."
if command -v uv >/dev/null 2>&1; then
    uv sync --all-extras --dev >/dev/null 2>&1 || {
        echo "❌ uv sync 失败"; exit 1; }
    PY=".venv/bin/python"
else
    echo "  （无 uv，退化为 python3 -m pip install -e .[dev]）"
    python3 -m venv .venv
    .venv/bin/python -m pip install --quiet -e ".[dev]" || {
        echo "❌ 依赖安装失败"; exit 1; }
    PY=".venv/bin/python"
fi
[ -x "$PY" ] || { echo "❌ 未找到 $PY"; exit 1; }

echo "▶ ruff check ..."
RUFF_CACHE_DIR=/tmp/ruff_ci_clone "$PY" -m ruff check src tests eval scripts

echo "▶ ruff format --check ..."
RUFF_CACHE_DIR=/tmp/ruff_ci_clone "$PY" -m ruff format --check src tests eval scripts

echo "▶ pytest（全离线）..."
"$PY" -m pytest -q

echo "▶ 文档链接校验 ..."
"$PY" scripts/check_doc_links.py

echo "▶ 敏感信息门禁 ..."
"$PY" -m pytest tests/test_no_secrets_in_repo.py -q

echo ""
echo "✅ 干净 clone 校验全部通过 —— 推送后 CI 不会再红"
