"""清洗已录制的 cassette：把租户标识符替换为占位符。

**为什么需要这个脚本**：cassette.py 的脱敏能力是在发现泄漏之后补上的，
存量 cassette 是在补强之前录制的，里面仍含真实 app_id / app_token /
table_id / record_id。

**为什么 path 也要替换**：重放时 `ReplayTransport` 会断言实发 path == 录制 path。
如果只脱敏 request body 而不动 path，path 里依然是真实标识符；
反之若两侧都脱敏，断言依然成立（两侧过同一套规则，结果一致）。

**幂等**：对已脱敏的文件再跑一次不会改变内容（占位符不匹配任何识别规则）。

用法：
    python scripts/scrub_cassettes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.cassette import redact_identifiers  # noqa: E402

CASSETTE_DIR = ROOT / "tests" / "cassettes"


def scrub_entry(entry: dict) -> dict:  # type: ignore[type-arg]
    """对单条 cassette 记录做就地脱敏（path + 递归 body）。"""
    out = dict(entry)
    out["path"] = redact_identifiers(str(entry.get("path", "")))
    # body 递归交给 cassette._redact_json 的规则集；此处 secrets 传空集，
    # 因为录制时的 secret/token 早已在录制阶段脱敏过。
    from basepilot.cassette import _redact_json

    out["request"] = {"json": _redact_json(entry.get("request", {}).get("json"), set())}
    resp = dict(entry.get("response", {}))
    resp["json"] = _redact_json(resp.get("json"), set())
    out["response"] = resp
    return out


def main() -> int:
    files = sorted(CASSETTE_DIR.glob("*.jsonl"))
    if not files:
        print(f"未找到 cassette：{CASSETTE_DIR}", file=sys.stderr)
        return 1

    changed_total = 0
    for path in files:
        lines = [
            ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        new_lines: list[str] = []
        changed = 0
        for ln in lines:
            entry = json.loads(ln)
            scrubbed = scrub_entry(entry)
            new_ln = json.dumps(scrubbed, ensure_ascii=False)
            if new_ln != ln:
                changed += 1
            new_lines.append(new_ln)

        if changed:
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(lines)} 条，脱敏改动 {changed} 条")
        changed_total += changed

    print(f"✅ 清洗完成，共改动 {changed_total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
