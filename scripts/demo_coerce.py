"""演示「入口宽容，出口严格」—— BasePilot 适配层的核心价值。

**这不是截图脚本**，而是真实可运行的演示：把LLM 常见的四种错误输入
（单选传数组 / 日期传秒级 / 人员传字符串 / 勾选传"true"）喂给适配层，
展示它们被自动纠正成飞书要求的格式。

**为什么值得单独演示**：这是本项目解决的真问题 —— 不是技术选型问题，
是没人把多维表格的真实约束包一层。跑一遍就能理解。

用法：
    python scripts/demo_coerce.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.coerce import (  # noqa: E402
    CoerceError,
    coerce_checkbox,
    coerce_datetime,
    coerce_single_select,
    coerce_user,
)
from basepilot.schema import FieldType  # noqa: E402


def _line(label: str, got: object, want: str) -> str:
    return f"  {label:<14} 输入 {got!r:<28} → 输出 {want!r}"


def main() -> int:
    print("入口宽容，出口严格 —— LLM 常见的四种错误输入被自动纠正")
    print()
    print("1) 单选字段传了数组（LLM 最常犯：多维表格选项看起来像列表）")
    print(_line("单选站点", ["US"], coerce_single_select("站点", FieldType.SINGLE_SELECT, ["US"])))
    print()
    print("2) 日期传了秒级时间戳（Python time.time() 返回秒，飞书要毫秒）")
    print(
        _line(
            "复核日期",
            1674206443,
            coerce_datetime("复核日期", FieldType.DATETIME, 1674206443),
        )
    )
    print(
        _line(
            "复核日期",
            "2026-10-18",
            coerce_datetime("复核日期", FieldType.DATETIME, "2026-10-18"),
        )
    )
    print()
    print("3) 人员字段传了字符串（飞书只接受数组对象，且只认 id）")
    print(
        _line(
            "负责人",
            "ou_7f3a9c2e",
            coerce_user("负责人", FieldType.USER, "ou_7f3a9c2e"),
        )
    )
    try:
        coerce_user("负责人", FieldType.USER, "张三")
    except CoerceError as exc:
        first = str(exc).split("：")[0]
        print(_line("负责人", '"张三"', f"拒绝 → {first}"))
    print("    （姓名不是合法标识，fail-fast 比静默写错值更安全 —— 出口严格）")
    print()
    print("4) 勾选字段传了字符串 \"true\"")
    print(_line("是否加急", "true", coerce_checkbox("是否加急", FieldType.CHECKBOX, "true")))
    print()
    print("结果：上面四种输入，如果直接调飞书 API 会分别报")
    print("  1254062 SingleSelectFieldConvFail / 1254064 DatetimeFieldConvFail /")
    print("  1254066 UserFieldConvFail / 1254060 TextFieldConvFail")
    print("适配层把它们全部吃掉，调用方不需要知道这些规则。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
