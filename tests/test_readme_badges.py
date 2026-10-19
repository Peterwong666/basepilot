"""README 徽章门禁 —— 防止公开门面出现 404 /失效图标（全离线）。

**为什么需要**：徽章挂在 README 第一屏，是项目的「门面」。图片一旦 404，
招聘方第一眼看到的就是 `404 badge not found` 三个红块 —— 比没有徽章更伤。
而徽章失效**不会让任何测试失败**，只能靠肉眼发现。

本项目真实踩过：Python 与 License 徽章用了 shields.io 的非标准路径
（`img.shields.io/python-...` 与 `img.shields.io/license-...`），
GitHub 的图片代理（camo）不跟随其301 重定向，于是显示 404。

锁五个行为：
1. 所有静态徽章必须走标准 `/badge/` 路径（非标准短路径会被 camo 判失败）
2. 徽章 URL 必须含 `/badge/` 且格式合法
3. 徽章 alt 文本非空（alt 坏掉屏幕阅读器读不出来）
4. 本地文件链接（如 `](LICENSE)`）指向的文件必须真实存在
5. endpoint 徽章（tests 数 / eval 指标）指向的仓库内 JSON 必须真实存在

例外：`https://img.shields.io/endpoint?url=...` 动态徽章内容由
`scripts/gen_badges.py` 从权威来源实算生成（pytest 收集数 / eval 报告），
不走 `/badge/` 静态路径、也没有图片扩展名，规则 1/2 对它豁免，
改由规则 5 防止指向不存在的 JSON（否则 shields.io 抓 404）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

#: 匹配 README 里的图片徽章：![alt](url)
_BADGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")

#: 允许出现的图片托管域名
_IMAGE_HOSTS = {
    "img.shields.io",
    "github.com",
    "raw.githubusercontent.com",
}

#: shields.io endpoint 动态徽章前缀 —— 内容指向仓库内 JSON，豁免 /badge/ 与扩展名检查
_ENDPOINT_PREFIX = "https://img.shields.io/endpoint?url="

#: endpoint 徽章只允许指向本仓库 main 分支的 raw 文件（合入后 shields.io 才能抓到）
_ENDPOINT_TARGET_PREFIX = "https://raw.githubusercontent.com/Peterwong666/basepilot/main/"


def _badges() -> list[tuple[int, str, str, str]]:
    """返回 [(行号, alt, url, 整行)]。"""
    out: list[tuple[int, str, str, str]] = []
    for i, line in enumerate(README.read_text(encoding="utf-8").splitlines(), 1):
        for m in _BADGE_RE.finditer(line):
            # 本地图片（截图）不是徽章，跳过
            url = m.group("url")
            if url.startswith("docs/"):
                continue
            out.append((i, m.group("alt"), url, line))
    return out


def test_badges_use_standard_shields_path() -> None:
    """shields.io 徽章必须用标准 `/badge/<label>-<message>-<color>` 路径。

    非标准写法（`img.shields.io/python-...`、`img.shields.io/license-...`）
    依赖 301 重定向到 `/badge/`，而 GitHub 图片代理不保证跟随 → 显示 404。
    """
    offenders: list[str] = []
    for line_no, alt, url, _ in _badges():
        if "shields.io" not in url or url.startswith(_ENDPOINT_PREFIX):
            continue
        if "/badge/" not in url:
            offenders.append(f"第 {line_no} 行 [{alt}]: {url}")
    assert not offenders, (
        "徽章使用了非标准 shields.io 路径（会显示 404 badge not found）：\n"
        + "\n".join(offenders)
        + "\n修法：统一用 img.shields.io/badge/<label>-<message>-<color>.svg"
    )


def test_badge_urls_are_wellformed() -> None:
    """徽章 URL 必须完整（https + 合法域名 + .svg 结尾）。"""
    bad: list[str] = []
    for line_no, alt, url, _ in _badges():
        if not url.startswith("https://"):
            bad.append(f"第 {line_no} 行 [{alt}]: 非 https -> {url}")
            continue
        host = url.split("//", 1)[1].split("/", 1)[0]
        if host not in _IMAGE_HOSTS:
            bad.append(f"第 {line_no} 行 [{alt}]: 未知图床 {host}")
            continue
        if url.startswith(_ENDPOINT_PREFIX):
            continue
        if not url.endswith((".svg", ".png", ".jpg", ".jpeg", ".gif")):
            bad.append(f"第 {line_no} 行 [{alt}]: 图片缺扩展名 -> {url}")
    assert not bad, "徽章 URL 不合法：\n" + "\n".join(bad)


def test_badge_alt_text_is_present() -> None:
    """徽章 alt 文本不能为空（屏幕阅读器依赖它）。"""
    empty = [f"第 {n} 行 url={u}" for n, alt, u, _ in _badges() if not alt.strip()]
    assert not empty, "徽章缺 alt 文本：\n" + "\n".join(empty)


def test_local_link_targets_exist() -> None:
    """README 里的本地链接（`](LICENSE)` 这类）指向的文件必须存在。"""
    missing: list[str] = []
    text = README.read_text(encoding="utf-8")
    # 只查非 http 的链接目标（http 由 docs-check 与实际访问负责）
    for m in re.finditer(r"\[[^\]]*\]\(([^)h][^)]*)\)", text):
        target = m.group(1).split("#")[0].strip()
        if not target or target.startswith(("http", "mailto:", "/")):
            continue
        if not (ROOT / target).exists():
            missing.append(target)
    assert not missing, "README 里的本地链接指向不存在的文件：" + ", ".join(sorted(set(missing)))


def test_readme_has_no_leftover_short_badge_paths() -> None:
    """防复发：显式禁止两种已知会 404 的非标准写法。"""
    text = README.read_text(encoding="utf-8")
    for bad in (
        "img.shields.io/python-",
        "img.shields.io/license-",
        "img.shields.io/badge/python-3.11+",
    ):
        assert bad not in text, f"README 仍含非标准/未编码徽章路径：{bad}"


def test_endpoint_badges_point_to_committed_json() -> None:
    """endpoint 徽章指向的仓库内 JSON 必须真实存在且已提交。

    shields.io 按 endpoint URL 去抓 raw JSON，文件缺失首屏就是
    `404 badge not found`。文件由 `make badges`（scripts/gen_badges.py）
    实算生成，内容零漂移由 `make docs-check` 里的 `--check` 门禁负责。
    """
    bad: list[str] = []
    for line_no, alt, url, _ in _badges():
        if not url.startswith(_ENDPOINT_PREFIX):
            continue
        target = url[len(_ENDPOINT_PREFIX) :]
        if not target.startswith(_ENDPOINT_TARGET_PREFIX):
            bad.append(f"第 {line_no} 行 [{alt}]: endpoint 未指向本仓库 main 分支 -> {target}")
            continue
        local = ROOT / target[len(_ENDPOINT_TARGET_PREFIX) :]
        if not local.exists():
            bad.append(f"第 {line_no} 行 [{alt}]: 本地缺文件 {local.relative_to(ROOT)}")
    assert not bad, "endpoint 徽章指向的 JSON 校验失败：\n" + "\n".join(bad)
