"""把真实命令输出渲染成终端风格截图（PNG）。

**为什么要有这个脚本**：README 里贴截图是为了让人「看图就懂功能」，
但截图必须**来自真实运行输出** —— 手绘的界面图等于伪造证据，
一旦命令行为变了图就过期，且没人能发现。所以这里的每一张图都对应
一次真实的 `make` / 脚本调用，内容由实参注入，不在绘图代码里编造。

**中英文混排**：等宽字体（Menlo）不含中文字形，混排时会缺字。
解法是逐字符判断宽度 —— ASCII 用 Menlo，其余用 Songti，两者
都按等宽步进绘制，保证列对齐不被中文撑歪。

用法：
    python scripts/make_screenshots.py
    # 产物：docs/images/*.png
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "images"

#: 等宽 ASCII 字体（macOS 自带，无需安装）
FONT_ASCII = "/System/Library/Fonts/Menlo.ttc"
#: 中文字体（Menlo 无中文字形，按字符回退到它）
#: Songti.ttc 是**字体集合**，必须用 font_index 指定简体字形 ——
#: 默认 index=0 是「Songti SC Black」，会渲染成方块/异常字形。
#: index=4 = STSong Regular，这是简体正文字形。
FONT_CJK = "/System/Library/Fonts/Supplemental/Songti.ttc"
FONT_CJK_INDEX = 4

#: 符号字体 —— Songti 里没有 ✓/✗/⚠ 的字形（渲染成豆腐块）。
FONT_SYMBOL = "/System/Library/Fonts/Apple Symbols.ttf"

#: 配色（对齐 macOS 终端深色主题）
BG = (30, 32, 40)
FG = (216, 222, 233)
TITLEBAR = (46, 49, 58)
TITLE_FG = (150, 156, 168)
DIM = (122, 132, 148)
GREEN = (126, 211, 135)
YELLOW = (229, 192, 123)
BLUE = (122, 162, 247)
MAGENTA = (198, 146, 233)
CYAN = (86, 182, 194)

#: 项目自己的解释器 —— 必须显式指定，不能用裸 `python`。
#:
#: **踩过的坑**：裸 `python` 在某些环境下解析到全局解释器（无 PyYAML），
#: 于是 `scenarios_loader` 静默降级到 `_fallback_scenarios()`，
#: 只有 4 条内置场景 —— 诊断输出变成「建议投入 3 个环节 / 694 小时」，
#: 与真实的 13 个 / 1624 小时不符。截图一旦用错解释器，
#: **发布出去的 README 就是假数据**。所以这里硬编码 venv 路径。
#: 显示时用 `.venv/bin/python` 全路径，与实际执行的一致，不美化。
PY = "./.venv/bin/python"

#: 排版参数
FS = 15
CHAR_W = 9
CHAR_W_TITLE = 8
LINE_H = 22
PAD = 22
TITLE_H = 34
CMD_H = 26
MAX_W = 1120

#: 语法着色规则（顺序决定优先级：先匹配先生效）
#: **渲染前把 emoji 换成等价的 ASCII 标记**。
#:
#: 踩过的坑：`✅`/`❌` 是彩色 emoji 字体（Apple Symbols 里虽有字形，
#: 但 Pillow 按单色渲染出来仍是豆腐块）。终端风格的图更该用 ASCII ——
#: 读者认得出来，且任何字体都渲染得出来。
_EMOJI_SUBST = {
    "✅": "[OK]", "❌": "[X]", "⚠️": "!", "⚠": "!",
    "🎉": "", "🚀": "", "⭐": "",
}

#: 走符号字体的字符集合（Songti 无字形，回退 Apple Symbols）
_SYMBOL_CHARS = set("✓✗✘★☆◆■□▲△●○→←↑↓⇒")


def _subst_emoji(text: str) -> str:
    for src, dst in _EMOJI_SUBST.items():
        text = text.replace(src, dst)
    return text


#: 语法着色规则（顺序决定优先级：先匹配先生效）
#: 匹配在emoji 替换**之后**进行，所以这里用的是替换后的 [OK]/[X]。
_HIGHLIGHT_RULES: tuple[tuple[re.Pattern[str], tuple[int, int, int]], ...] = (
    (re.compile(r"\[OK\]|通过|passed|全绿|正确率|成功率|幂等|一致|OK\b"), GREEN),
    (re.compile(r"!\s|失败|error|错误|劝退|不建议|MISMATCH|超期"), YELLOW),
    (re.compile(r"\d+%|\d+\s*(?:tests|条|个|次|小时|h\b)"), CYAN),
    (re.compile(r"`[^`]+`"), MAGENTA),
    (re.compile(r"\[X\]|✗|Traceback|Exception", re.IGNORECASE), (240, 113, 120)),
)


@dataclass(frozen=True)
class Shot:
    """一张截图。"""

    name: str
    title: str
    cmd: str
    #: 输出最多保留多少行（截图不宜过长）
    max_lines: int = 26
    #: 只保留 (起始正则, 结束正则) 之间的内容 —— 用于聚焦最有信息量的段落。
    #: 结束正则传 None 表示取到末尾。保持 None 表示整段输出都进截图。
    keep_between: tuple[str, str | None] | None = None


def _font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


def _is_cjk(ch: str) -> bool:
    return ord(ch) > 0x2E80


def _is_symbol(ch: str) -> bool:
    """是否需要Apple Symbols 字形（含 emoji 变体选择符 U+FE0F）。"""
    return ch in _SYMBOL_CHARS or ord(ch) == 0xFE0F


def _pick_font(ch: str, font_a: ImageFont.FreeTypeFont,
               font_c: ImageFont.FreeTypeFont,
               font_s: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    """单字符字体选择：符号 → Apple Symbols，中文 → Songti，其余 → Menlo。"""
    if _is_symbol(ch):
        return font_s
    return font_c if _is_cjk(ch) else font_a


def _shade_line(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """把一行文本切成 (片段, 颜色) 序列，用于语法着色。"""
    color = FG
    for pattern, c in _HIGHLIGHT_RULES:
        if pattern.search(line):
            color = c
            break
    return [(line, color)]


def _draw_text_with_fallback(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font_ascii: ImageFont.FreeTypeFont,
    font_cjk: ImageFont.FreeTypeFont,
    font_symbol: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
    char_w: int,
) -> int:
    """逐字符绘制（ASCII → Menlo，中文 → Songti，符号 → Apple Symbols）。

    必须逐字符切换字体：Menlo 没有中文字形、两者都没有 ✅/⚠ 字形，
    整串渲染会缺字成豆腐块且列对齐被撑歪。
    """
    x, y = xy
    for ch in text:
        draw.text(
            (x, y), ch, font=_pick_font(ch, font_ascii, font_cjk, font_symbol), fill=color
        )
        # 中文按双倍步进保持视觉等宽；符号不额外占位
        x += char_w * (2 if _is_cjk(ch) else 1)
    return x


def render_shot(shot: Shot, output: Path) -> Path:
    """执行真实命令 → 渲染成 PNG。"""
    # 所有 python 命令强制走项目 venv，避免 fallback 场景污染数据
    cmd = (
        shot.cmd.replace("{PY}", PY)
        if "{PY}" in shot.cmd
        else (shot.cmd.replace("python ", f"{PY} ", 1) if "python " in shot.cmd else shot.cmd)
    )
    # shell=True 是安全的：命令来自本文件内的 SHOTS 白名单常量，
    # 不接受任何外部输入（S602 在此为误报）
    proc = subprocess.run(  # noqa: S602
        cmd, cwd=ROOT, shell=True, capture_output=True, text=True, check=False
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    _verify_not_degraded(raw)
    # 本机绝对路径不进截图（既泄露目录结构，换机器也对不上）
    raw = raw.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
    # emoji → ASCII 替换必须在语法着色之前（着色规则匹配的是替换后的文本）
    raw = _subst_emoji(raw)
    lines = raw.splitlines()

    # 可选：从输出中只取某段（如「象限汇总表」），让截图聚焦在信息量最大的部分
    # end_pattern 为 None 表示「从 start 一直取到末尾」
    if shot.keep_between:
        start_pat, end_pat = shot.keep_between
        picked, on = [], False
        for ln in lines:
            if re.search(start_pat, ln):
                on = True
            if on and end_pat and re.search(end_pat, ln):
                break
            if on:
                picked.append(ln)
        if picked:
            lines = picked

    # 超宽的行按字符预算裁剪（终端不会换行，超出部分本来看不见）。
    # 宽度预算按「等宽字符数」算：中文按 2 计，与绘制步进一致。
    budget = int((MAX_W - 2 * PAD) / CHAR_W)

    def _width_units(s: str) -> int:
        return sum(2 if _is_cjk(c) else 1 for c in s)

    clipped: list[str] = []
    for ln in lines:
        if _width_units(ln) > budget:
            out_ch = 0
            buf = []
            for ch in ln:
                w = 2 if _is_cjk(ch) else 1
                if out_ch + w > budget - 1:
                    buf.append(" …")
                    break
                buf.append(ch)
                out_ch += w
            ln = "".join(buf)
        clipped.append(ln)
    lines = clipped

    # 超出上限时裁中间，保头尾（头是结论、尾是报错）
    if len(lines) > shot.max_lines:
        head = shot.max_lines // 2
        tail = shot.max_lines - head - 1
        lines = [
            *lines[:head],
            f"  …（中间省略 {len(lines) - head - tail} 行）",
            *lines[-tail:],
        ]

    # 画布宽度取「标题 / 命令 / 正文」三者最宽者，避免标题被裁掉
    max_units = max(
        _width_units(ln) for ln in lines
    )
    title_units = _width_units(shot.title) + 12  # 12 ≈ 三个圆点占位
    cmd_units = _width_units(cmd) + 3  # 3 ≈ "$ " 前缀
    width = min(MAX_W, 2 * PAD + max(max_units, title_units, cmd_units) * CHAR_W + 8)

    font_a = _font(FONT_ASCII, FS)
    font_c = _font(FONT_CJK, FS, FONT_CJK_INDEX)
    font_s = _font(FONT_SYMBOL, FS)
    font_title = _font(FONT_ASCII, 13)
    font_cmd = _font(FONT_ASCII, 13)

    height = PAD + TITLE_H + CMD_H + LINE_H * max(len(lines), 1) + PAD

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # 标题栏 + 三个圆点
    draw.rectangle([0, 0, width, TITLE_H], fill=TITLEBAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([16 + i * 20, 11, 27 + i * 20, 22], fill=c)
    _draw_text_with_fallback(
        draw, (88, 9), shot.title, font_title, font_c, font_s, TITLE_FG, CHAR_W_TITLE
    )

    # 命令行
    y = TITLE_H
    draw.rectangle([0, y, width, y + CMD_H], fill=(38, 40, 48))
    draw.text((PAD, y + 6), "$", font=font_cmd, fill=GREEN)
    draw.text((PAD + 14, y + 6), cmd, font=font_cmd, fill=FG)
    y += CMD_H

    # 输出
    for line in lines:
        for frag, color in _shade_line(line):
            _draw_text_with_fallback(
                draw, (PAD, y + 2), frag, font_a, font_c, font_s, color, CHAR_W
            )
        y += LINE_H

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG", optimize=True)
    return output


def _verify_not_degraded(raw: str) -> None:
    """校验截图输出用的是完整场景包，而非 fallback 降级结果。

    **为什么必须校验**：fallback 只有 4 条内置场景，诊断数字会变成
    「3 个环节 / 694 小时」，而真实是 13 个 / 1624 小时。这种图
    贴进 README 就是发布假数据，且没有任何机制会报错 —— 除了这一条。
    """
    if "业务环节" not in raw:
        return  # 非诊断类截图，不校验
    m = re.search(r"评估 \*\*(\d+) 个业务环节\*\*", raw)
    if not m:
        raise AssertionError("诊断输出格式异常，无法校验场景数 —— 拒绝出图")
    n = int(m.group(1))
    if n < 10:
        raise AssertionError(
            f"诊断只评估了 {n} 个环节，疑似 fallback 降级（真实为 15 个）"
            " —— 拒绝出图，防止把假数据发布到 README"
        )


#: 要生成哪些截图 —— 每张都对应一次真实命令
SHOTS: tuple[Shot, ...] = (
    Shot(
        name="01-diagnose",
        title="业务诊断：15 个环节逐条打分，排出投入优先级",
        cmd="python scripts/diagnose.py",
        max_lines=22,
    ),
    Shot(
        name="02-quadrant",
        title="四象限分布：7 个不需要 AI，2 个明确劝退",
        cmd="python scripts/diagnose.py",
        max_lines=24,
        keep_between=(r"^## 汇总", None),
    ),
    Shot(
        name="03-eval",
        title="评测：9 项指标全部实算，无一手写",
        cmd="make eval",
        max_lines=22,
    ),
    Shot(
        name="04-cassette",
        title="cassette 重放：真实租户交互在 CI 可复现（已脱敏）",
        # 用 -v 而不是 -q：`-q` 只打进度点，看不到「N passed」结论，
        # 截图就没有信息量了
        cmd="{PY} -m pytest tests/test_cassette_replay.py -v",
        max_lines=10,
    ),
    Shot(
        name="05-handbook",
        title="交付手册合集页：五份报告即代码文档的入口",
        cmd="python scripts/gen_delivery_handbook.py",
        max_lines=10,
    ),
    Shot(
        name="06-troubleshooting",
        title="排障 SOP：34 条错误码 → 客户现场动作（由代码生成，零漂移）",
        cmd="python scripts/gen_troubleshooting.py",
        max_lines=8,
    ),
    Shot(
        name="07-verify",
        title="离线全量门禁：lint + 类型 + 测试 + 评测 + 文档校验",
        cmd="make verify",
        max_lines=16,
    ),
    Shot(
        name="08-coerce",
        title="入口宽容出口严格：LLM 常见的四种错误输入被自动纠正",
        cmd="python scripts/demo_coerce.py",
        max_lines=22,
    ),
)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for shot in SHOTS:
        out = OUT_DIR / f"{shot.name}.png"
        try:
            render_shot(shot, out)
            size_kb = out.stat().st_size // 1024
            print(f"✅ {out.relative_to(ROOT)}  ({size_kb} KB)")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {shot.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
