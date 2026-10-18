"""从 errors.py 生成排障 SOP 文档。

**为什么必须自动生成**：如果 troubleshooting 文档手写，它会和 `errors.py` 里的
32 条规则逐渐脱节 —— 加了新错误码忘了更文档，客户现场按文档操作却解决不了问题。
这是交付事故的典型来源。

所以本脚本是 `docs/delivery/troubleshooting.md` 的唯一来源，
CI 里用 `doc_code_drift` 指标（应恒为 0）校验文档与代码一致。

用法：
    python scripts/gen_troubleshooting.py          # 生成文档
    python scripts/gen_troubleshooting.py --check  # 只校验不写入，漂移则退出码 1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basepilot.config import (  # noqa: E402
    BACKOFF_BASE,
    BATCH_CREATE_MAX,
    BATCH_DELETE_MAX,
    BATCH_UPDATE_MAX,
    FIELD_NAMES_MAX,
    FILTER_MAX_LEN,
    LIST_MAX_PAGE_SIZE,
    RECORD_LIMIT_PER_TABLE,
    SEARCH_MAX_PAGE_SIZE,
    SORT_MAX_LEN,
    TABLE_LIMIT_PER_BASE,
    TOKEN_REFRESH_THRESHOLD,
    TOKEN_TTL_SECONDS,
    WRITE_MIN_INTERVAL,
)
from basepilot.errors import RULES, Action  # noqa: E402

OUT = ROOT / "docs/delivery/troubleshooting.md"

ACTION_LABEL = {
    Action.RETRY: "自动退避重试",
    Action.LONG_BACKOFF: "长退避重试",
    Action.REGEN_IDEMPOTENCY: "重新生成幂等键后重试",
    Action.FAIL_FAST: "不重试，按指引处理",
}

# 每个处置类别挑一条最有代表性的作为开场案例
SHOWCASE: dict[Action, int] = {
    Action.RETRY: 1254291,
    Action.LONG_BACKOFF: 1254036,
    Action.REGEN_IDEMPOTENCY: 1255006,
    Action.FAIL_FAST: 1254302,
}


def build() -> str:
    by_action: dict[Action, list[int]] = {}
    for code, rule in RULES.items():
        by_action.setdefault(rule.action, []).append(code)

    lines: list[str] = []
    lines.append("# 飞书多维表格错误码 → 现场动作对照表")
    lines.append("")
    lines.append(
        ">⚠️ **本文档由 `scripts/gen_troubleshooting.py` 从 "
        "`src/basepilot/errors.py` 自动生成，请勿手工编辑。**"
    )
    lines.append("> 改了错误码规则就跑 `make docs`；CI 会校验文档与代码零漂移。")
    lines.append("")
    lines.append(
        f"覆盖 **{len(RULES)} 条**官方错误码，每条含「客户端现场可执行的动作」。"
        "客户现场最贵的不是写代码，是「不知道下一步该干什么」——这张表就是为此存在。"
    )
    lines.append("")

    # 开场：四类处置的速查
    lines.append("## 一分钟速查")
    lines.append("")
    lines.append("| 处置 | 条数 | 含义 | 代表错误码 |")
    lines.append("|---|---|---|---|")
    for action in (
        Action.RETRY,
        Action.LONG_BACKOFF,
        Action.REGEN_IDEMPOTENCY,
        Action.FAIL_FAST,
    ):
        codes = sorted(by_action.get(action, []))
        if not codes:
            continue
        showcase = SHOWCASE[action]
        lines.append(
            f"| {ACTION_LABEL[action]} | {len(codes)} | "
            f"{action.value} | `{showcase}` {RULES[showcase].title} |"
        )
    lines.append("")
    lines.append("**判断顺序**：先看处置类型，再翻下面对照表找到具体错误码。")
    lines.append("")

    # 开场案例：最常见的写冲突
    lines.append("## 最常踩的坑：写冲突 1254291")
    lines.append("")
    lines.append(
        "官方原文说明：**同一数据表并发调用读写接口或请求过快会出现冲突**；"
        "多维表格底层按版本维度串行处理，**不支持并发**。官方建议："
        "「若操作量较大，建议在接口与接口之间增加 **0.5 或 1 秒**的延迟」。"
    )
    lines.append("")
    lines.append(
        f"BasePilot 的处理：`per-table_id` 串行队列 + `{WRITE_MIN_INTERVAL}s` 节流，"
        "不同数据表之间仍可并行。"
    )
    lines.append("")
    lines.append("若客户现场仍冲突，把 `BASEPILOT_WRITE_INTERVAL` 调大到 `1.0`。")
    lines.append("")

    # 分组列出全部规则
    for action in (Action.FAIL_FAST, Action.RETRY, Action.LONG_BACKOFF, Action.REGEN_IDEMPOTENCY):
        codes = sorted(by_action.get(action, []))
        if not codes:
            continue
        lines.append(f"## {ACTION_LABEL[action]}（{len(codes)} 条）")
        lines.append("")
        for code in codes:
            rule = RULES[code]
            lines.append(f"### `{code}` {rule.title}")
            lines.append("")
            lines.append(f"**现场动作**：{rule.guidance}")
            lines.append("")
            if rule.keywords:
                lines.append(f"- 检索关键词：{' / '.join(rule.keywords)}")
            lines.append("")

    # 容量与配置速查
    lines.append("## 容量与配置速查")
    lines.append("")
    lines.append("| 项 | 值 | 来源 |")
    lines.append("|---|---|---|")
    lines.append(f"| batch_create 单次上限 | {BATCH_CREATE_MAX} 条 | 官方接口页 |")
    lines.append(f"| batch_update 单次上限 | {BATCH_UPDATE_MAX} 条 | 官方接口页 |")
    lines.append(
        f"| batch_delete 单次上限 | **{BATCH_DELETE_MAX} 条** | "
        "正文 500 / 错误码表 1000，**取保守值** |"
    )
    lines.append(f"| search 单次上限 | {SEARCH_MAX_PAGE_SIZE} 行 | 官方接口页 |")
    lines.append(f"| field.list / view.list 分页上限 | {LIST_MAX_PAGE_SIZE} | 官方接口页 |")
    lines.append(f"| field_names 长度上限 | {FIELD_NAMES_MAX} | 官方接口页 |")
    lines.append(f"| filter 表达式上限 | {FILTER_MAX_LEN} 字符 | 错误码 1254107 |")
    lines.append(f"| sort 表达式上限 | {SORT_MAX_LEN} 字符 | 错误码 1254108 |")
    lines.append(f"| 单表记录数上限 | {RECORD_LIMIT_PER_TABLE} | 错误码 1254103 |")
    lines.append(f"| 单表内数据表数上限 | {TABLE_LIMIT_PER_BASE} | 错误码 1254100 |")
    lines.append(f"| 写间隔 | {WRITE_MIN_INTERVAL}s（可配到 1.0） | 错误码 1254291 排查建议 |")
    lines.append(f"| token 有效期 | {TOKEN_TTL_SECONDS}s | 官方 `expire` |")
    lines.append(
        f"| token 刷新阈值 | {TOKEN_REFRESH_THRESHOLD}s（30min） | "
        "官方：剩余 <30min 才换发新 token |"
    )
    lines.append(f"| 退避基数 | {BACKOFF_BASE}s（指数退避 + jitter） | 本项目策略 |")
    lines.append("")

    # 现场排查顺序
    lines.append("## 现场排查顺序（403 最常见）")
    lines.append("")
    lines.append("遇到「调用成功但没数据」或「权限相关报错」，按此顺序查：")
    lines.append("")
    lines.append("1. **应用有没有发布？** 自建应用改完权限必须由管理员审核发布版本，")
    lines.append("   否则 API 返回权限错误（403）。这是最常见的'代码没错但跑不通'。")
    lines.append("2. **多维表格授权了吗？** 打开目标表 → 右上角「···」→")
    lines.append("   「更多」→「添加文档应用」→ 加入你的自建应用。")
    lines.append("3. **权限粒度够吗？** 读写需要 `bitable:app`，只读是 `bitable:app:readonly`。")
    lines.append("   按最小权限申请，跑通再加。")
    lines.append("4. **开了高级权限？** 开了之后调用可能**成功但返回空**。")
    lines.append("   确认调用身份有可管理权限。")
    lines.append("5. **表在复制中？** 错误码 `1254036`，异步操作，等待完成。")
    lines.append("")
    lines.append("跑 `bitable_doctor` 可以一次性拿到以上全部检查结果。")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    content = build()
    if "--check" in sys.argv:
        if not OUT.exists():
            print(f"❌ {OUT.relative_to(ROOT)} 不存在")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current != content:
            print("❌ 文档与 errors.py 已漂移")
            print("   修复：make troubleshooting")
            return 1
        print(f"✅ 文档与 errors.py 一致（{len(RULES)} 条规则）")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"✅ 已生成 {OUT.relative_to(ROOT)}（{len(RULES)} 条错误码）")
    return 0


if __name__ == "__main__":
    sys.exit(main())