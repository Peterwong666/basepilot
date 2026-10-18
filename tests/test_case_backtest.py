"""gen_case_backtest 案例回测生成测试（全离线）。

锁四个行为：
1. 回测包含「凭什么信你」的核心叙事章节，且顺序正确
2. 回测结论从 cassette + eval_report 实算，不写死 —— 改证据后报告自动反映
3. 每个回测案例都锚定到真实存在的证据文件（路径不假）
4. 无 U+FFFD 乱码
"""

from __future__ import annotations

from scripts.gen_case_backtest import (
    CASSETTE,
    EVAL_REPORT,
    collect_cases,
    load_cassette,
    load_eval,
    render,
)


def _render_default() -> str:
    it = load_cassette()
    ev = load_eval()
    return render(collect_cases(it, ev), len(it))


def test_backtest_has_core_narrative_structure() -> None:
    """回测必须包含核心章节标题，且顺序正确（按 Markdown 标题匹配，避免正文子串歧义）。"""
    md = _render_default()
    sections = [
        "## 这份回测是什么",
        "## 回测总览",
        "## 逐条对账",
        "## 如果有预测没兑现",
        "## 回测和客户的关系",
    ]
    pos = -1
    for s in sections:
        new_pos = md.find(s)
        assert new_pos > pos, f"章节「{s}」缺失或顺序错误"
        pos = new_pos


def test_backtest_results_come_from_real_evidence() -> None:
    """回测条数、兑现数、交互数必须与证据实算一致（不写死）。"""
    it = load_cassette()
    ev = load_eval()
    cases = collect_cases(it, ev)
    md = render(cases, len(it))

    passed_n = sum(1 for c in cases if c.passed)
    assert f"{passed_n}/{len(cases)} 兑现" in md
    assert f"{len(it)} 条" in md

    # 每条案例的标题都要落到报告里
    for c in cases:
        assert c.title in md


def test_backtest_case_evidence_files_exist() -> None:
    """每个案例引用的证据文件必须真实存在（防止锚定到臆造路径）。"""
    assert CASSETTE.exists(), f"cassette 不存在：{CASSETTE}"
    assert EVAL_REPORT.exists(), f"eval_report 不存在：{EVAL_REPORT}"

    it = load_cassette()
    ev = load_eval()
    for c in collect_cases(it, ev):
        ref = c.evidence.split("（")[0]
        assert ("cassette" in ref) or ("eval_report" in ref), (
            f"{c.id}: 证据路径不指向已知事实文件：{ref}"
        )


def test_backtest_cases_are_falsifiable_predictions() -> None:
    """每条案例都必须写明「当初预测了什么」—— 可证伪是回测的前提。"""
    it = load_cassette()
    ev = load_eval()
    for c in collect_cases(it, ev):
        assert c.prediction.strip(), f"{c.id}: 缺预测内容"
        assert c.evidence.strip(), f"{c.id}: 缺证据来源"
        assert c.detail.strip(), f"{c.id}: 缺实算明细"


def test_backtest_no_garbled_chars() -> None:
    """回测不得含 U+FFFD 替换字符。"""
    md = _render_default()
    assert "�" not in md, "回测含乱码字符"
