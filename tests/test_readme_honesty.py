"""README 诚信门禁 —— 防止文档数字与代码实况脱节（全离线）。

**为什么需要这个文件**：README 承诺的测试数如果与实际跑出来的不一致，
面试时对方一跑就发现 —— 这是最廉价的失信方式（代码没问题，文档撒了谎）。

本项目已犯过一次同类错误：进度表写「建设中」而代码已完成，
测试数写 252 而实际已 286。**所以必须有机器门禁，而不是靠记性。**

锁三个行为：
1. README 声明的测试数与实际收集总数一致（含本门禁自身），且注明口径
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

    **用 `sys.executable` 而非硬编码 `.venv/bin/python`**：
    干净 clone（如 CI）里没有 .venv，硬编码会 FileNotFoundError。
    门禁自己不该依赖「本机恰好有这个路径」—— 这类环境假设会让门禁
    在 CI 里假失败（已踩过一次）。
    """
    import subprocess
    import sys

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
        raise AssertionError(f"无法从 pytest 输出解析测试数：\n{combined[-500:]}")
    return {path: int(n) for path, n in pairs}


def test_readme_declared_test_count_matches_reality() -> None:
    """README 承诺的测试数必须等于实际收集总数，且口径说明也与实况一致。

    **口径：含本门禁自身**。读者跑 `make verify` 看到的总数就是收集总数，
    README 写「排除门禁后的数字」会与实际输出对不上（本项目真实发生过
    297 vs 300 的漂移）。声明总数 + 注明「含门禁脚本自身 N 个测试」
    对两边都诚实。代价：本门禁增删测试时需同步 README 的总数与口径说明，
    不同步则本测试失败并提示 —— 这正是门禁存在的意义。
    """
    md = _readme()
    m = re.search(r"离线全绿（\*{0,2}(\d+)\s*tests?\*{0,2}[^）]*）", md)
    assert m, (
        "README「当前进度」段必须声明测试数"
        "（格式：`离线全绿（N tests，含门禁脚本自身 3 个测试）`，数字可加粗）"
    )

    declared = int(m.group(1))

    per_file = _collect_per_file()
    actual = sum(per_file.values())

    assert declared == actual, (
        f"README 声明 {declared} tests，实际收集（含门禁自身）{actual} 个 —— "
        "请同步更新 README（这是最容易发生的文档失信）"
    )

    note = re.search(r"含门禁脚本自身\s*(\d+)\s*个测试", m.group(0))
    assert note, (
        "声明测试数时必须注明口径（如「含门禁脚本自身 3 个测试」），"
        "否则读者跑 pytest 看到的总数会与 README 对不上"
    )
    gate_count = per_file.get("tests/test_readme_honesty.py", 0)
    assert int(note.group(1)) == gate_count, (
        f"口径说明写「门禁自身 {note.group(1)} 个测试」，"
        f"本门禁实际 {gate_count} 个 —— 请同步口径说明"
    )


def test_readme_progress_table_has_no_unfinished_wording() -> None:
    """「当前进度」段不得出现未完成表述（代码完成 ≠ 文案还在建设）。"""
    md = _readme()
    # 标题可能带装饰（如「## ✅ 当前进度」），用宽松匹配定位
    m = re.search(r"^##\s*(?:[^\w\n]{0,4})*\s*当前进度", md, re.M)
    assert m, "README 缺少「当前进度」段"
    section = md[m.start() : md.find("\n---", m.start())]

    for word in ("建设中", "进行中", "TODO", "待完成", "暂未"):
        assert word not in section, f"进度表出现「{word}」—— 代码已完成就别让文案停在建设期"


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
