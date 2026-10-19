"""发布前敏感信息门禁 —— 公开仓库前的硬性检查（全离线）。

**为什么需要**：cassette 里存的是**真实租户的交互记录**。第一次发布前排查发现：
`app_secret` 和 `tenant_access_token` 已脱敏，但 `app_id` / `app_token` /
`table_id` / `record_id` **全部以真值躺在文件里** —— 其中 path 字段 10/10 条命中。
这些虽不是密钥，但会暴露「这是哪个企业租户的哪张表」，配合业务数据可还原现场。

所以加机器门禁，而不是靠发布前再人工 grep 一遍（人总会忘）。
本文件锁三件事：
1. cassette 与仓库内文件不含任何真实租户标识符
2. 脱敏规则有区分度：结构差异保留、租户差异抹除（否则断言能力被削弱）
3. 常见凭证形态（app_id / 长随机串 / .env 内容）零命中
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASSETTE_DIR = ROOT / "tests" / "cassettes"

#: 不该出现在仓库里的真实标识符形态（匹配脱敏后的文件应为 0 命中）
#:
#: 注意排除纯占位符（连续 x）：`.env.example` 与场景包里会放
#: `tblxxxxxxxxxxxx` 这类示例形态，那是给人看的模板，不是租户标识。
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcli_(?!x+_)[A-Za-z0-9]{16,}\b", "飞书 app_id"),
    (r"(?<=/apps/)(?!__REDACTED)[A-Za-z0-9]{20,}(?=/)", "多维表格 app_token（路径段）"),
    (r"\btbl(?!x{6,})[A-Za-z0-9]{12,}\b", "table_id"),
    (r"\brec(?!x{6,})[A-Za-z0-9]{12,}\b", "record_id"),
)

#: 这些目录不参与扫描（第三方/缓存，内容不由本项目控制）
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache",
              ".ruff_cache", ".pytest_cache"}

#: 本文件自身不扫描 —— 它是**规则定义处**，里面必然写着命中形态的示例
#: （如 `tbl` + 12 位以上的示例串）。规则文件不是数据文件。
_SELF = Path(__file__).resolve()


def _tracked_files() -> list[Path]:
    """扫**将要进入仓库**的所有文件：已追踪 + 未追踪未忽略。

    **为什么不只扫 `git ls-files`**：只扫已追踪文件时，新增的未追踪文件
    （写完还没 `git add`）会完全绕过门禁 —— 而那正是最可能带密钥的阶段。
    所以补上 `--others --exclude-standard`（未追踪且未被 .gitignore 忽略）。
    已 gitignore 的（.env /缓存）本来就不可能出现在公开仓库里，不扫。
    """
    import subprocess

    out = subprocess.run(
        ["/usr/bin/git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    files = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    return [ROOT / f for f in files]


def test_no_real_tenant_identifiers_in_repo() -> None:
    """仓库内任何文件都不得含真实租户标识符。

    **失败信息只报位置与类型，不报匹配到的实际值** ——
    否则 CI 日志、测试输出、乃至截图里就会出现真实的 app_token，
    门禁本身反而成了泄露渠道（这个坑踩过：assert 里直接插值了匹配串）。
    """
    hits: list[str] = []
    for path in _tracked_files():
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == _SELF:
            continue  # 规则定义处自身跳过
        if not path.exists() or path.suffix in {".png", ".jpg", ".pdf", ".whl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 二进制文件，凭证不会以文本形式存在于其中
        for pattern, label in _FORBIDDEN_PATTERNS:
            n = len(re.findall(pattern, text))
            if n:
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}: 检出 {label} × {n}（值不回显，避免日志泄露）")

    assert not hits, (
        "仓库内检出疑似真实租户标识符（值已隐去）：\n"
        + "\n".join(hits[:20])
        + "\n处理：把真实值改为占位符或移到 .env（见 .env.example）"
    )


def test_cassette_identifiers_all_redacted() -> None:
    """cassette 的 path 段必须全部是占位符形态。"""
    if not CASSETTE_DIR.exists():
        return
    for path in sorted(CASSETTE_DIR.glob("*.jsonl")):
        text = path.read_text(encoding="utf-8")
        assert "cli_" not in text, f"{path.name} 仍含 app_id"
        assert not re.search(r"/apps/(?!__REDACTED)[A-Za-z0-9]{20,}/", text), (
            f"{path.name} 的 app_token 未脱敏"
        )
        assert not re.search(r"\btbl(?!x{6,})[A-Za-z0-9]{12,}\b", text), (
            f"{path.name} 仍含真实 table_id"
        )
        assert not re.search(r"\brec(?!x{6,})[A-Za-z0-9]{12,}\b", text), (
            f"{path.name} 仍含真实 record_id"
        )


def test_redaction_keeps_structure_discrimination() -> None:
    """脱敏必须抹掉租户差异但保留结构差异。

    这是脱敏正确性的判据：若抹掉了结构差异（如把 table_id 和 record_id
    都替换成同一个串），重放时 path 断言就失去了校验能力 —— 那是
    「为了脱敏而牺牲了测试强度」，属于隐性退化，必须测出来。
    """
    from basepilot.cassette import (
        REDACTED_APP_TOKEN,
        REDACTED_TABLE_ID,
        redact_identifiers,
    )

    a = "/open-apis/bitable/v1/apps/__REDACTED_APP_TOKEN__/tables/__REDACTED_TABLE_ID__/fields"
    b = "/open-apis/bitable/v1/apps/ZZZZZZZZZZZZZZZZZZZZZZZZ/tables/tblXXXXXXXXXXXX/fields"
    c = "/open-apis/bitable/v1/apps/__REDACTED_APP_TOKEN__/tables/__REDACTED_TABLE_ID__/records"

    # 不同租户的同构路径 → 脱敏后必须一致（租户维度被抹平）
    assert redact_identifiers(a) == redact_identifiers(b), (
        "不同租户的同构路径脱敏后应一致，否则说明租户标识未被完全替换"
    )
    # 结构不同的路径 → 脱敏后必须仍不同（结构维度被保留）
    assert redact_identifiers(a) != redact_identifiers(c), (
        "结构不同的路径脱敏后不应相同 —— 断言能力被削弱了"
    )
    # 占位符确实落到路径里
    assert REDACTED_APP_TOKEN in redact_identifiers(a)
    assert REDACTED_TABLE_ID in redact_identifiers(a)


def test_no_env_file_or_secret_committed() -> None:
    """真实 .env 不得入库；.env.example 只应是占位符。"""
    tracked = {p.relative_to(ROOT).as_posix() for p in _tracked_files()}

    for leaked in tracked:
        assert leaked != ".env", "真实 .env 被提交（应仅 gitignore）"
        assert not leaked.endswith("/.env"), f"目录内 .env 被提交：{leaked}"

    example = ROOT / ".env.example"
    if example.exists():
        text = example.read_text(encoding="utf-8")
        # 允许的只是明显的占位写法
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                assert len(value) < 24 or "your" in value.lower() or "xxx" in value.lower(), (
                    f".env.example 疑似填了真实值：{line}"
                )


def test_no_local_absolute_paths_in_docs() -> None:
    """文档与源码不得出现本机绝对路径（泄露用户名/目录结构，且换机器就失效）。"""
    suspicious = re.compile(r"/Users/[A-Za-z0-9_.-]+/")
    hits: list[str] = []
    for rel in ("README.md", "docs", "scripts", "src", "tests"):
        base = ROOT / rel
        paths = [base] if base.is_file() else sorted(base.rglob("*"))
        for p in paths:
            if not p.is_file() or p.suffix not in {".md", ".py", ".yaml", ".yml", ".toml"}:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            n = len(suspicious.findall(text))
            if n:
                hits.append(f"{p.relative_to(ROOT)}: 本机绝对路径 × {n}")

    assert not hits, "检出本机绝对路径：\n" + "\n".join(hits[:20])
