"""校验 README / 文档里引用的仓库内文件真实存在。

**为什么需要这个脚本**：2026-10-18 审计发现 README 引用了 5 个不存在的文件
（4 份交付文档 + ADR-005）。这类"承诺未兑现"对求职项目的杀伤力极大——
面试官点开 README，3 秒内就能发现文档不存在，剩下的技术描述可信度会一起崩塌。

所以把校验做成 CI 硬门禁：README 里提到`docs/xxx.md` 但文件不存在 → 流水线直接红。

用法：
    python scripts/check_doc_links.py
退出码：
    0 = 全部存在
    1 = 有失效引用
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 匹配 markdown 里的仓库内路径引用：反引号包裹的 docs/xxx 或 src/xxx 等
# 允许在路径后跟 `::符号名`（如 `tests/test_auth.py::test_xxx`），需排除冒号及其后内容
CODE_PATH_PATTERN = re.compile(
    r"`((?:docs|src|tests|eval|scripts|scenarios|diagnosis)/[^`\s:]+(?:\.[a-z]{2,4})?)`"
)

# 匹配 markdown 链接：[text](docs/xxx.md)
LINK_PATTERN = re.compile(r"\]\(((?:docs|src|tests|eval|scripts|scenarios|diagnosis)/[^)]+)\)")

# 这些是目录，允许存在（不代表内容非空，但不该报错）
DIR_PREFIXES = ("docs/adr/",)

# 允许 README 预告但本期不实现的目标路径（显式白名单，避免"偷偷跳过"）
# 格式：路径 -> 计划完成阶段
# ⚠️ 完成后必须从这里移除，让「0 计划中」真实反映完成态
ALLOWED_PENDING: dict[str, str] = {
    "docs/delivery/case_backtest.md": "D11",
    "docs/delivery/expansion_matrix.md": "D11",
    "docs/delivery/rollout_calendar.md": "D11",
}


def collect_references() -> set[str]:
    """扫描 README 与 docs 下所有 markdown，收集仓库内路径引用。"""
    refs: set[str] = set()
    targets = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for md in targets:
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        refs.update(CODE_PATH_PATTERN.findall(text))
        refs.update(LINK_PATTERN.findall(text))
    return refs


def main() -> int:
    refs = collect_references()
    if not refs:
        print("⚠️  未从任何文档中提取到路径引用 —— 校验器本身可能失效，请检查")
        return 1

    missing: list[str] = []
    pending: list[str] = []
    ok: list[str] = []

    for ref in sorted(refs):
        # 目录引用：存在即可
        if ref.startswith(DIR_PREFIXES):
            target = ROOT / ref
            (ok if target.exists() else missing).append(ref)
            continue

        path = ROOT / ref
        if path.exists():
            ok.append(ref)
        elif ref in ALLOWED_PENDING:
            pending.append(ref)
        else:
            missing.append(ref)

    print(f"检查 {len(refs)} 个引用：{len(ok)} 存在 / {len(pending)} 计划中 / {len(missing)} 失效")

    if pending:
        print("\n📋 计划中（D5-D11 交付，当前尚未创建）：")
        for ref in pending:
            print(f"  · {ref}  → {ALLOWED_PENDING[ref]} 完成")

    if missing:
        print("\n❌ 失效引用（必须修）：")
        for ref in missing:
            hint = ""
            if ref.endswith(".md"):
                hint = "  → 补写该文档，或从 README 移除该承诺"
            print(f"  · {ref}{hint}")
        print("\n💡 修复方式二选一：")
        print("   A. 真的把文件补上（推荐：宁少不虚）")
        print("   B. 若确定本期不做，从 README 删除该引用，不要留死链")
        print("   C. 若确定本期做但还没做，加进 scripts/check_doc_links.py 的 ALLOWED_PENDING")
        return 1

    print("\n✅ 文档引用全部有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())