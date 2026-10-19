"""生成 shields.io endpoint 徽章 JSON —— 让 README 首屏数字不再是手写。

**为什么需要**：README 的「304 tests」「9 项 eval 全绿」这类数字一旦手写在
徽章里，就会和代码实况漂移（本项目在测试数上真实漂移过一次：297 vs 300）。
shields.io 的 endpoint 机制允许把徽章内容指向仓库内的 JSON 文件，
于是数字可以从权威来源**实算生成**：

- `.github/badges/tests.json` —— 从 `pytest --collect-only` 收集数生成
  （与 `tests/test_readme_honesty.py` 同口径：含门禁脚本自身）；
- `.github/badges/eval.json` —— 从 `eval/reports/eval_report.json`
  逐项核对 9 项指标是否全部达标生成。

README 用 `https://img.shields.io/endpoint?url=...` 引用这两个文件，
合入 main 后徽章自动展示最新提交里的数字。

用法：
    python scripts/gen_badges.py           # 生成/更新 .github/badges/
    python scripts/gen_badges.py --check   # 校验已提交 JSON 与实算零漂移（CI 门禁）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BADGE_DIR = ROOT / ".github" / "badges"
EVAL_REPORT = ROOT / "eval" / "reports" / "eval_report.json"

#: eval 9 项指标的达标判据 —— 与 README「评测：9 项指标全部实算」逐项对应，
#: 字段名即 eval/runner.py 的 EvalReport 字段。
EVAL_CHECKS: tuple[tuple[str, Callable[[dict[str, Any]], bool]], ...] = (
    ("golden_cases", lambda r: r["golden_cases_passed"] == r["golden_cases_total"] > 0),
    ("field_encoding_accuracy", lambda r: r["field_encoding_accuracy"] == 1.0),
    ("unsafe_write_rejection_rate", lambda r: r["unsafe_write_rejection_rate"] == 1.0),
    ("error_code_coverage", lambda r: r["error_code_coverage"] == r["error_code_total_rules"] > 0),
    ("max_inflight_write_per_table", lambda r: r["max_inflight_write_per_table"] == 1),
    ("dry_run_purity", lambda r: r["dry_run_purity"] == 0),
    ("dryrun_prediction_accuracy", lambda r: r["dryrun_prediction_accuracy"] == 1.0),
    ("retry_success_rate", lambda r: r["retry_success_rate"] == 1.0),
    ("token_fetch_count", lambda r: r["token_fetch_count"] == 1),
)


def _endpoint(label: str, message: str, color: str) -> dict[str, Any]:
    """shields.io endpoint 徽章的标准信封。"""
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def _collect_test_count() -> int:
    """pytest 收集总数（用 sys.executable，不假设 .venv 存在 —— 干净 clone 也能跑）。"""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = out.stdout + out.stderr
    pairs = re.findall(r"^(tests/\S+\.py):\s*(\d+)\s*$", combined, re.M)
    if not pairs:
        raise RuntimeError(f"无法从 pytest 输出解析测试数：\n{combined[-500:]}")
    return sum(int(n) for _, n in pairs)


def compute_badges() -> dict[str, dict[str, Any]]:
    """实算两个徽章的内容，返回 {文件名: endpoint JSON}。"""
    test_count = _collect_test_count()

    report = json.loads(EVAL_REPORT.read_text(encoding="utf-8"))
    failed = [name for name, ok in EVAL_CHECKS if not ok(report)]
    passed = len(EVAL_CHECKS) - len(failed)
    total = len(EVAL_CHECKS)

    eval_color = "brightgreen" if not failed else ("orange" if passed else "red")
    eval_message = f"{passed}/{total} 全绿" if not failed else f"{passed}/{total}"

    return {
        "tests.json": _endpoint("tests", str(test_count), "brightgreen"),
        "eval.json": _endpoint("eval", eval_message, eval_color),
    }


def _render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str]) -> int:
    badges = compute_badges()

    if "--check" in argv:
        drifted: list[str] = []
        for name, payload in sorted(badges.items()):
            path = BADGE_DIR / name
            current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if current != payload:
                drifted.append(name)
        if drifted:
            print("❌ 徽章 JSON 与实算漂移：" + ", ".join(drifted))
            print("   修复：运行 `make badges` 重新生成并提交 .github/badges/")
            return 1
        print(f"✅ 徽章与实算一致（{len(badges)} 个 endpoint JSON）")
        return 0

    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in sorted(badges.items()):
        (BADGE_DIR / name).write_text(_render(payload), encoding="utf-8")
        print(f"已生成 .github/badges/{name}: {payload['label']}={payload['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
