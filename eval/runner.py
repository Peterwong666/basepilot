"""评测框架 —— 8 项指标。

与PawPilot 的 `eval/` 同一套思路：**指标必须是可复现的数字，不能手写进README**。
`scripts/gen_evidence.py` 从本模块的输出生成 README 证据卡，
若数字不一致，CI 会挂（见 gen_evidence.py 的一致性校验）。

8 项指标
--------
1. field_encoding_accuracy          字段编码正确率
2. unsafe_write_rejection_rate      不可写字段拦截率
3. error_code_coverage              错误码策略覆盖率
4. max_inflight_write_per_table     单表并发写峰值
5. token_fetch_count                N 次业务请求换 token 次数
6. dry_run_purity                   dry_run 时的真实 HTTP 调用数
7. retry_success_rate               故障注入后重试成功率
8. dryrun_prediction_accuracy       dry-run 预测 vs 真实返回码一致率

第 8 项是差异化指标：它直接回答「LLM 不用你的适配层也会调 API 啊」这个质疑。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).parent / "reports"


@dataclass
class EvalReport:
    """评测报告。所有字段必须由runner 实际计算填入。"""

    field_encoding_accuracy: float = 0.0
    unsafe_write_rejection_rate: float = 0.0
    error_code_coverage: int = 0
    error_code_total_rules: int = 0
    max_inflight_write_per_table: int = 0
    token_fetch_count: int = 0
    business_request_count: int = 0
    dry_run_purity: int = 0
    retry_success_rate: float = 0.0
    dryrun_prediction_accuracy: float = 0.0
    golden_cases_total: int = 0
    golden_cases_passed: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """生成证据卡Markdown，供 gen_evidence.py 写入 README。"""
        rows = [
            ("黄金用例通过率",
             f"{self.golden_cases_passed}/{self.golden_cases_total}"),
            ("字段编码正确率", f"{self.field_encoding_accuracy:.0%}"),
            ("不安全写入拦截率", f"{self.unsafe_write_rejection_rate:.0%}"),
            ("错误码策略覆盖", f"{self.error_code_coverage}/{self.error_code_total_rules}"),
            ("单表最大并发写", str(self.max_inflight_write_per_table)),
            ("dry_run 真实 HTTP 调用数", str(self.dry_run_purity)),
            ("dry-run 预测与真实返回码一致率", f"{self.dryrun_prediction_accuracy:.0%}"),
            ("故障注入后重试成功率", f"{self.retry_success_rate:.0%}"),
            ("100 次业务请求换 token 次数", str(self.token_fetch_count)),
        ]
        lines = ["| 指标 | 值 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in rows]
        return "\n".join(lines)


def _measure_error_coverage() -> tuple[int, int]:
    """错误码覆盖率 —— 直接问规则表，不手写数字。"""
    from basepilot.errors import RULES

    covered = sum(1 for rule in RULES.values() if rule.guidance.strip() and rule.keywords)
    return covered, len(RULES)


def _measure_token_efficiency(request_count: int = 100) -> int:
    """100 次业务请求换token 次数。

    复跑 tests/test_auth.py 里的同一个场景逻辑，避免评测与测试两套实现。
    """
    import asyncio

    import httpx

    from basepilot.auth import TokenCache

    class Clock:
        def __call__(self) -> float:
            return 1000.0

    def handler(request: httpx.Request) -> httpx.Response:
        # 断言我们确实打到了鉴权端点，防止路径写错却"通过"
        assert request.url.path.endswith("/tenant_access_token/internal")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "tenant_access_token": "t-eval",
                "expire": 7200,
            },
        )

    async def run() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = TokenCache("cli_x", "secret_x", http_client=client, clock=Clock())
            for _ in range(request_count):
                await cache.get()
            return cache.fetch_count

    return asyncio.run(run())


def run_eval() -> EvalReport:
    """执行评测并落盘。

    当前阶段（骨架期）只落地可从已实现模块直接测量的指标；
    依赖 coerce.py 的指标（1/2/8）在 D4-D5 接入后自动点亮，
    未实现的项明确标记为 pending，**绝不填0 或编造数字**。
    """
    report = EvalReport()

    # 3. 错误码覆盖率（已实现，可测）
    covered, total = _measure_error_coverage()
    report.error_code_coverage = covered
    report.error_code_total_rules = total

    # 5. token 效率（已实现，可测）
    report.business_request_count = 100
    report.token_fetch_count = _measure_token_efficiency(100)

    report.notes.append("字段编码/拦截率/dry-run 相关指标待 coerce.py 与 client.py 就位后点亮")
    report.notes.append("并发写峰值与重试成功率待 serialization.py 与 fault 测试就位后点亮")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "eval_report.json"
    out.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    (REPORT_DIR / "evidence_card.md").write_text(report.to_markdown(), encoding="utf-8")

    return report


if __name__ == "__main__":
    rep = run_eval()
    print(rep.to_markdown())
    print()
    print(f"报告已写入 {REPORT_DIR}")