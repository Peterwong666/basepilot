"""诊断报告生成 —— `make diagnose`

输出三种格式：
- Markdown 报告（可直接贴进交付文档）
- Mermaid 四象限图
- JSON（供 MCP 工具消费）

用法：
    python scripts/diagnose.py                 # Markdown + 象限图
    python scripts/diagnose.py --json          # JSON
    python scripts/diagnose.py --quadrant C    # 只看某个象限
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.diagnosis import (  # noqa: E402
    QUADRANT_LABEL,
    Quadrant,
    diagnose_all,
    render_json,
    render_markdown,
    render_quadrant_mermaid,
)
from basepilot.scenarios_loader import load_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="生成业务诊断报告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--quadrant",
        choices=[q.value for q in Quadrant],
        help="只显示某个象限的场景",
    )
    parser.add_argument("--out", help="输出文件路径（默认打印到stdout）")
    args = parser.parse_args()

    scenarios = load_scenarios()
    results = diagnose_all(scenarios)

    if args.quadrant:
        q = Quadrant(args.quadrant)
        results = [d for d in results if d.quadrant is q]
        if not results:
            print(f"象限 {q.value}（{QUADRANT_LABEL[q]}）下没有场景")
            return 0

    if args.json:
        output = render_json(results)
    else:
        output = render_markdown(results) + "\n\n---\n\n" + render_quadrant_mermaid(results)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"✅ 已写入 {args.out}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
