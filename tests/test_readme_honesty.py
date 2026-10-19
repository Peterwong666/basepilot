"""README 诚信门禁 —— 防止文档数字与代码实况脱节（全离线）。

**为什么需要这个文件**：README 承诺的测试数如果与实际跑出来的不一致，
面试时对方一跑就发现 —— 这是最廉价的失信方式（代码没问题，文档撒了谎）。

本项目已犯过一次同类错误：进度表写「建设中」而代码已完成，
测试数写 252 而实际已 286。**所以必须有机器门禁，而不是靠记性。**

锁三个行为：
1. README 声明的测试数与实际收集数一致
2. README 的「当前进度」表里不出现「建设中」「TODO」「进行中」等未完成表述
3. 声明的错误码条数与 errors.py 实际规则数一致
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def _readme() -> str:
    assert README.exists(), f"README 缺失：{README}"
    return README.read_text(encoding="utf-8")


def _collect_per_file() -> dict[str, int]:
    """收集测试用例，返回 {相对路径: 用例数}。

    本项目 pytest 版本的 `--collect-only -q` 输出是逐文件格式
    （`tests/x.py: 5`），故按文件求和，不依赖汇总行格式。
    """
    import subprocess

    out = subprocess.run(
        [".venv/bin/python", "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = out.stdout + out.stderr
    pairs = re.findall(r"^(tests/\S+\.py):\s*(\d+)\s*$", combined, re.M)
    if not pairs:
        raise AssertionError(f"无法从 pytest 输出解析测试数：\n{combined[-500:]}")
    return {path: int(n) for path, n in pairs}


def test_readme_declared_test_count_matches_reality() -> None:
    """README 承诺的测试数必须等于实际收集数。

    **计数排除本门禁文件自身**：否则这是个自指问题——门禁新增测试会让
    它要校验的数字变化。排除后「项目测试总数」是稳定量，
    加门禁本身不会引发假失败。
    """
    md = _readme()
    m = re.search(r"离线全绿（(\d+) tests?）", md)
    assert m, "README「实测验证」段必须声明测试数（格式：`离线全绿（N tests）`）"

    declared = int(m.group(1))

    per_file = _collect_per_file()
    actual = sum(per_file.values()) - per_file.get(
        "tests/test_readme_honesty.py", 0
    )

    assert declared == actual, (
        f"README 声明 {declared} tests，项目实际（不含本门禁自身）{actual} 个 —— "
        "请同步更新 README（这是最容易发生的文档失信）"
    )


def test_readme_progress_table_has_no_unfinished_wording() -> None:
    """「当前进度」表不得出现未完成表述（代码完成≠文案还在建设）。"""
    md = _readme()
    start = md.find("## ✅ 当前进度")
    assert start > 0, "README 缺少「当前进度」段"
    section = md[start : md.find("\n---", start)]

    for word in ("建设中", "进行中", "TODO", "待完成", "暂未"):
        assert word not in section, (
            f"进度表出现「{word}」—— 代码已完成就别让文案停在建设期"
        )


def test_readme_error_code_count_matches_errors_py() -> None:
    """README 声明的错误码条数必须与 errors.py 实际规则数一致。"""
    md = _readme()
    m = re.search(r"\*\*(\d+) 条规则\*\*", md)
    assert m, "README 必须声明错误码规则条数（格式：**N 条规则**）"
    declared = int(m.group(1))

    # 直接导入权威来源，不在测试里用正则重新实现一套统计
    from basepilot.errors import RULES

    assert declared == len(RULES), (
        f"README 声明 {declared} 条错误码规则，errors.RULES 实际 {len(RULES)} 条"
    )
