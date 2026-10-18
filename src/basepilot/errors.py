"""飞书错误码分类处置。

这是 BasePilot 里**最像"做过交付"**的一个模块：每个错误码对应一个明确的处置动作，
其中「不可重试」类必须返回**客户现场可执行的指引**，而不是把飞书的原始报错扔回去。

分类：
- `RETRY`      —— 瞬时问题，退避重试即可
- `LONG_BACKOFF` —— 异步操作中（副本复制），需要更长等待
- `REGEN_IDEMPOTENCY` —— 幂等键冲突，需重新生成 client_token
- `FAIL_FAST`  —— 人的问题（权限/ID 写错/字段不存在），重试无用，必须给指引

错误码来源：飞书开放平台各接口页「错误码」小节与官方错误码总表。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import LONG_BACKOFF_SCHEDULE


class Action(str, Enum):  # noqa: UP042 - 需 str 行为才能直接 JSON 序列化
    """处置动作。"""

    RETRY = "retry"
    LONG_BACKOFF = "long_backoff"
    REGEN_IDEMPOTENCY = "regen_idempotency"
    FAIL_FAST = "fail_fast"


@dataclass(frozen=True)
class ErrorRule:
    """单个错误码的处置规则。"""

    code: int
    action: Action
    title: str
    #: 给客户现场看的可执行指引，直接进排障 SOP
    guidance: str
    #: 期望在提示文案里出现的关键词，测试用断言抓手
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def build_message(self) -> str:
        return f"[{self.code}] {self.title}：{self.guidance}"


# ---------------------------------------------------------------------------
# 处置规则表
# ---------------------------------------------------------------------------

RULES: dict[int, ErrorRule] = {
    # ---------------- 可退避重试 ----------------
    1254290: ErrorRule(
        code=1254290,
        action=Action.RETRY,
        title="TooManyRequest（频率超限）",
        guidance=(
            "触发了接口频率限制。BasePilot 已自动退避重试；"
            "若持续出现，请降低并发或调大节流间隔。"
        ),
        keywords=("频率", "退避"),
    ),
    1254291: ErrorRule(
        code=1254291,
        action=Action.RETRY,
        title="Write conflict（写冲突）",
        guidance=(
            "同一数据表并发写或请求过快。官方建议在接口之间增加 0.5-1 秒延迟。"
            "BasePilot 已按单表串行 + 节流处理并自动重试；"
            "若仍冲突，请把 BASEPILOT_WRITE_INTERVAL 调大到 1.0。"
        ),
        keywords=("写冲突", "串行", "延迟"),
    ),
    1254607: ErrorRule(
        code=1254607,
        action=Action.RETRY,
        title="Data not ready（数据未就绪）",
        guidance=(
            "多维表格底层按版本维度串行处理，不支持并发。"
            "BasePilot 会退避后重试，请稍候。"
        ),
        keywords=("就绪", "退避"),
    ),
    1255040: ErrorRule(
        code=1255040,
        action=Action.RETRY,
        title="Request timed out（网关超时）",
        guidance="请求超时，通常是网络或飞书侧瞬时抖动，已自动重试。",
        keywords=("超时",),
    ),
    # ---------------- 需长退避 ----------------
    1254036: ErrorRule(
        code=1254036,
        action=Action.LONG_BACKOFF,
        title="Bitable is copying（多维表格副本复制中）",
        guidance=(
            "多维表格正在复制，复制是异步操作。请等待复制完成后再写入，"
            "BasePilot 会按 3s/6s/12s 退避重试，最多 5 次。"
        ),
        keywords=("复制", "等待"),
    ),
    # ---------------- 幂等键冲突 ----------------
    1255006: ErrorRule(
        code=1255006,
        action=Action.REGEN_IDEMPOTENCY,
        title="client token conflict（幂等键冲突）",
        guidance=(
            "相同 client_token 在同一 base 版本上重复提交。"
            "BasePilot 已重新生成 uuid4 作为幂等键并重试。"
        ),
        keywords=("幂等", "重新生成"),
    ),
    1254037: ErrorRule(
        code=1254037,
        action=Action.FAIL_FAST,
        title="Invalid client token（幂等键格式非法）",
        guidance=(
            "client_token 必须是 uuidv4 格式。"
            "这通常来自调用方手动传参，请改用默认生成的幂等键。"
        ),
        keywords=("uuidv4",),
    ),
    # ---------------- 权限类：必须给现场指引 ----------------
    1254302: ErrorRule(
        code=1254302,
        action=Action.FAIL_FAST,
        title="Permission denied（权限不足）",
        guidance=(
            "解决步骤：① 打开目标多维表格页面；② 点右上角「···」；"
            "③ 选择「更多」→「添加文档应用」；④ 把你的自建应用加为可管理协作者。"
        ),
        keywords=("添加文档应用", "权限"),
    ),
    1254304: ErrorRule(
        code=1254304,
        action=Action.FAIL_FAST,
        title="Permission denied（无多维表格访问权限）",
        guidance=(
            "解决步骤：① 打开目标多维表格页面；② 点右上角「···」；"
            "③ 选择「更多」→「添加文档应用」；④ 把你的自建应用加为可管理协作者。"
        ),
        keywords=("添加文档应用", "权限"),
    ),
    # ---------------- ID 类：指引如何取到正确 ID ----------------
    1254003: ErrorRule(
        code=1254003,
        action=Action.FAIL_FAST,
        title="WrongBaseToken（app_token 错误）",
        guidance=(
            "app_token 不正确。从多维表格 URL 中取："
            "URL 以 feishu.cn/base 开头时，base 后那段即为 app_token；"
            "若以 feishu.cn/wiki 开头，需先调 wiki-v2/space/getNode 拿 obj_token。"
        ),
        keywords=("app_token", "URL"),
    ),
    1254040: ErrorRule(
        code=1254040,
        action=Action.FAIL_FAST,
        title="BaseTokenNotFound（多维表格不存在）",
        guidance=(
            "app_token 指向的多维表格不存在或当前应用无权访问。"
            "请确认链接是否有效，以及是否已把该多维表格授权给应用。"
        ),
        keywords=("app_token", "授权"),
    ),
    1254004: ErrorRule(
        code=1254004,
        action=Action.FAIL_FAST,
        title="WrongTableId（table_id 错误）",
        guidance=(
            "table_id 不正确。可从多维表格 URL 直接取，"
            "或调用「列出数据表」接口重新获取。"
        ),
        keywords=("table_id", "列出数据表"),
    ),
    1254041: ErrorRule(
        code=1254041,
        action=Action.FAIL_FAST,
        title="TableIdNotFound（数据表不存在）",
        guidance="table_id 指向的数据表不存在，请调用「列出数据表」接口核对。",
        keywords=("table_id", "核对"),
    ),
    # ---------------- 字段类 ----------------
    1254045: ErrorRule(
        code=1254045,
        action=Action.FAIL_FAST,
        title="FieldNameNotFound（字段名不存在）",
        guidance=(
            "字段名必须与多维表格中**完全一致** —— "
            "界面上看到的名字可能含不可见空格或换行。"
            "建议先运行 bitable_inspect_schema 拿到准确字段名。"
        ),
        keywords=("完全一致", "字段名"),
    ),
    1254043: ErrorRule(
        code=1254043,
        action=Action.FAIL_FAST,
        title="RecordIdNotFound（记录不存在）",
        guidance="record_id 不存在。请先用 search_records 查询确认记录已被删除或从未存在。",
        keywords=("record_id", "查询"),
    ),
    1254014: ErrorRule(
        code=1254014,
        action=Action.FAIL_FAST,
        title="FieldNameDuplicated（字段名重复）",
        guidance="同一张表内字段名不能重复。请修改字段名或先删除已有字段。",
        keywords=("重复",),
    ),
    # ---------------- 字段类型转换类（正常情况下不应到这里） ----------------
    1254062: ErrorRule(
        code=1254062,
        action=Action.FAIL_FAST,
        title="SingleSelectFieldConvFail（单选字段格式错误）",
        guidance=(
            "单选字段要求传**字符串**，例如 \"选项A\"，"
            "而不是数组 [\"选项A\"]。这是最常见的错误。"
        ),
        keywords=("字符串", "数组"),
    ),
    1254063: ErrorRule(
        code=1254063,
        action=Action.FAIL_FAST,
        title="MultiSelectFieldConvFail（多选字段格式错误）",
        guidance="多选字段要求传字符串数组，例如 [\"选项A\", \"选项B\"]。",
        keywords=("数组",),
    ),
    1254064: ErrorRule(
        code=1254064,
        action=Action.FAIL_FAST,
        title="DatetimeFieldConvFail（日期字段格式错误）",
        guidance=(
            "日期字段要求传 **13 位毫秒时间戳**"
            "（例如 1674206443000），不是秒、也不是日期字符串。"
        ),
        keywords=("毫秒", "时间戳"),
    ),
    1254065: ErrorRule(
        code=1254065,
        action=Action.FAIL_FAST,
        title="CheckboxFieldConvFail（复选框格式错误）",
        guidance="复选框字段要求传布尔值 true / false。",
        keywords=("布尔",),
    ),
    1254066: ErrorRule(
        code=1254066,
        action=Action.FAIL_FAST,
        title="UserFieldConvFail（人员字段格式错误）",
        guidance=(
            "人员字段要求传数组对象 [{\"id\": \"ou_xxx\"}]，"
            "且**只支持 id 参数**。传字符串或 name 都会失败。"
            "传 null 可清空该字段。"
        ),
        keywords=("id", "数组"),
    ),
    1254068: ErrorRule(
        code=1254068,
        action=Action.FAIL_FAST,
        title="URLFieldConvFail（超链接字段格式错误）",
        guidance="超链接字段要求传 {\"link\": \"...\", \"text\": \"...\"} 对象。",
        keywords=("link", "text"),
    ),
    1254069: ErrorRule(
        code=1254069,
        action=Action.FAIL_FAST,
        title="AttachmentFieldConvFail（附件字段格式错误）",
        guidance=(
            "附件字段不能直接传本地路径或外部 URL。"
            "必须先调drive/v1/medias/upload_all 上传拿到 file_token，"
            "再传 [{\"file_token\": \"...\"}]。"
        ),
        keywords=("file_token", "上传"),
    ),
    1254303: ErrorRule(
        code=1254303,
        action=Action.FAIL_FAST,
        title="AttachPermNotAllow（附件权限不足）",
        guidance=(
            "上传附件的接口要求应用对该多维表格有管理权限。"
            "请确认已通过「添加文档应用」完成授权。"
        ),
        keywords=("权限", "授权"),
    ),
    1254074: ErrorRule(
        code=1254074,
        action=Action.FAIL_FAST,
        title="关联字段参数无效",
        guidance=(
            "关联字段（SingleLink / DuplexLink）要求传**字符串数组**"
            "（record_id 的数组），例如 [\"recXXX\", \"recYYY\"]。"
        ),
        keywords=("字符串数组", "record_id"),
    ),
    # ---------------- 不可写字段 ----------------
    1254015: ErrorRule(
        code=1254015,
        action=Action.FAIL_FAST,
        title="FieldTypeValueNotMatch（字段类型不匹配）",
        guidance="该字段不接受这种类型的值，请先运行 bitable_inspect_schema 确认字段类型。",
        keywords=("字段类型",),
    ),
    1254012: ErrorRule(
        code=1254012,
        action=Action.FAIL_FAST,
        title="NotSupportFieldOrView（不支持的字段或视图）",
        guidance=(
            "公式、查找引用、创建时间、修改时间、自动编号、按钮等系统字段"
            "**不能通过 API 写入**。请改为写入其数据源字段。"
        ),
        keywords=("公式", "系统字段"),
    ),
    # ---------------- 容量超限 ----------------
    1254103: ErrorRule(
        code=1254103,
        action=Action.FAIL_FAST,
        title="RecordExceedLimit（记录数超限）",
        guidance="单表记录数已达上限 20000 条，请考虑拆分数据表或归档历史数据。",
        keywords=("上限", "20000"),
    ),
    1254100: ErrorRule(
        code=1254100,
        action=Action.FAIL_FAST,
        title="TableExceedLimit（数据表数量超限）",
        guidance="单表内数据表数量已达上限 100 张，请合并同类台账。",
        keywords=("上限", "100"),
    ),
    1254107: ErrorRule(
        code=1254107,
        action=Action.FAIL_FAST,
        title="FilterLengthExceedLimit（过滤表达式超长）",
        guidance="filter 表达式超过 2000 字符，请简化过滤条件。",
        keywords=("2000", "简化"),
    ),
    1254108: ErrorRule(
        code=1254108,
        action=Action.FAIL_FAST,
        title="SortLengthExceedLimit（排序表达式超长）",
        guidance="sort 表达式超过 1000 字符，请减少排序字段。",
        keywords=("1000", "排序"),
    ),
    1254608: ErrorRule(
        code=1254608,
        action=Action.REGEN_IDEMPOTENCY,
        title="请求重复",
        guidance="相同幂等键重复提交，BasePilot 已更换 client_token 后重试。",
        keywords=("重复", "更换"),
    ),
}


class FeishuAPIError(Exception):
    """飞书 API 返回的业务错误。"""

    def __init__(self, code: int, msg: str = "") -> None:
        self.code = code
        self.raw_msg = msg
        self.rule = RULES.get(code)
        super().__init__(self.message())

    @property
    def action(self) -> Action:
        """处置动作；未登记的错误码按需重试处理（保守但不放弃）。"""
        return self.rule.action if self.rule else Action.RETRY

    def message(self) -> str:
        """面向人的错误信息 —— 已知码给指引，未知码给原始信息。"""
        if self.rule:
            return self.rule.build_message()
        return f"[{self.code}] 飞书接口返回错误：{self.raw_msg or '（无错误描述）'}"

    def should_retry(self) -> bool:
        return self.action in (Action.RETRY, Action.LONG_BACKOFF, Action.REGEN_IDEMPOTENCY)

    def needs_new_idempotency_key(self) -> bool:
        return self.action is Action.REGEN_IDEMPOTENCY

    def backoff_schedule(self) -> tuple[float, ...]:
        """返回该错误码适用的退避序列（秒）。"""
        if self.action is Action.LONG_BACKOFF:
            return LONG_BACKOFF_SCHEDULE
        return ()

    def new_idempotency_key(self) -> str:
        """重新生成 uuidv4 幂等键。"""
        return str(uuid.uuid4())


def lookup(code: int) -> ErrorRule | None:
    """按错误码查处置规则，供排障 SOP 文档生成与测试使用。"""
    return RULES.get(code)


def coverage() -> dict[str, Any]:
    """返回规则表覆盖率统计，供评测报告引用。"""
    by_action: dict[str, int] = {}
    for rule in RULES.values():
        by_action[rule.action.value] = by_action.get(rule.action.value, 0) + 1
    return {
        "total_rules": len(RULES),
        "by_action": by_action,
        "all_rules_have_guidance": all(bool(r.guidance) for r in RULES.values()),
        "all_rules_have_keywords": all(bool(r.keywords) for r in RULES.values()),
    }