"""限流与容量常量。

**所有数值均来自飞书开放平台官方接口文档，来源逐条标注在下方。**
任何一个数字都不是拍脑袋定的，改动时必须同步更新 `docs/adr/003-serialization.md`
与 README 中的「与官方文档的分歧」章节。

⚠️ 已知分歧：`BATCH_DELETE_MAX`。官方 batch_delete 接口页正文写「单次最多删除 500 条」，
   而错误码表1254104 的描述里写的是 1000。这里取**保守值 500**，
   因为超限会导致整批失败，而保守值只多一次请求。见 ADR-003。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 接口频率限制（官方接口页「接口频率限制」字段）
# ---------------------------------------------------------------------------

#:批量写类接口（batch_create / batch_update / batch_delete）—— 官方标注「50 次/秒」
BATCH_WRITE_QPS: int = 50

#: 查询记录（search）—— 官方标注「20 次/秒」
SEARCH_QPS: int = 20

#: 元信息列举（field.list / view.list / app-table.list）—— 官方标注「20 次/秒」
LIST_QPS: int = 20

# ---------------------------------------------------------------------------
# 容量限制
# ---------------------------------------------------------------------------

#: batch_create 单次最多记录数 —— 官方「单次调用最多新增 1,000 条记录」
BATCH_CREATE_MAX: int = 1000

#: batch_update 单次最多记录数 —— 官方「单次调用最多更新 1,000 条记录」
BATCH_UPDATE_MAX: int = 1000

#: batch_delete 单次最多记录数 —— 官方正文「最多删除 500 条」/ 错误码 1254104 写 1000
#: **取保守值**，理由见模块 docstring 与 ADR-003
BATCH_DELETE_MAX: int = 500

#: search 接口 page_size 上限 —— 官方「page_size 最大值为 500」
SEARCH_MAX_PAGE_SIZE: int = 500

#: field.list / view.list 的 page_size 上限 —— 官方「最大值: 100」
LIST_MAX_PAGE_SIZE: int = 100

#: search 的 field_names 长度上限 —— 官方「长度范围 0～200」
FIELD_NAMES_MAX: int = 200

#: filter 表达式长度上限 —— 错误码 1254107 FilterLengthExceedLimit
FILTER_MAX_LEN: int = 2000

#: sort 表达式长度上限 —— 错误码 1254108 SortLengthExceedLimit
SORT_MAX_LEN: int = 1000

#: 单个数据表记录数上限 —— 错误码 1254103 RecordExceedLimit
RECORD_LIMIT_PER_TABLE: int = 20000

#: 单个多维表格数据表数量上限 —— 错误码 1254100 TableExceedLimit
TABLE_LIMIT_PER_BASE: int = 100

#: search 自动翻页的最大页数保护，防止一次调用打爆配额
SEARCH_MAX_PAGES: int = 20

# ---------------------------------------------------------------------------
# 并发与写冲突
# ---------------------------------------------------------------------------

#: 同一数据表两次写请求之间的最小间隔（秒）
#:
#: 来源：错误码 1254291 Write conflict 的排查建议原文
#:「若操作量较大，建议在接口与接口之间增加 0.5 或 1 秒的延迟」。
#: 取下限 0.5；客户现场若仍冲突，可通过环境变量调到 1.0。
WRITE_MIN_INTERVAL: float = 0.5

# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------

#: tenant_access_token 有效期 —— 官方返回 expire=7200（秒）
TOKEN_TTL_SECONDS: int = 7200

#: token 提前刷新阈值（秒）
#:
#: 官方文档明确：「剩余有效期小于 30 分钟时返回新 token，
#: 大于等于 30 分钟时返回原有 token」。所以刷新窗口必须落在这个区间内，
#: 否则会拿到同一个 token，白白浪费一次调用且拿不到新凭证。
TOKEN_REFRESH_THRESHOLD: int = 1800

# ---------------------------------------------------------------------------
# 重试策略
# ---------------------------------------------------------------------------

#: 通用退避重试次数
RETRY_MAX_ATTEMPTS: int = 3

#: 「副本复制中」(1254036) 的长退避序列（秒）—— 复制是异步操作，需要等
LONG_BACKOFF_SCHEDULE: tuple[float, ...] = (3.0, 6.0, 12.0)

#: 通用退避基数（秒），实际退避为 BASE * 2^n + jitter
BACKOFF_BASE: float = 0.5

#: 通用 HTTP 状态码重试集合（配合退避）
RETRYABLE_HTTP_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# ---------------------------------------------------------------------------
# 接口基址
# ---------------------------------------------------------------------------

#: 飞书开放平台 API 基址
OPEN_API_BASE: str = "https://open.feishu.cn/open-apis"

#: 鉴权（tenant_access_token）端点
AUTH_TOKEN_PATH: str = "/auth/v3/tenant_access_token/internal"  # noqa: S105 -这是 URL 路径，不是密钥

#: 多维表格记录路径前缀
BITABLE_RECORDS_PATH: str = "/bitable/v1/apps/{app_token}/tables/{table_id}/records"

#: 数据表字段列举路径
BITABLE_FIELDS_PATH: str = "/bitable/v1/apps/{app_token}/tables/{table_id}/fields"

#: 数据表列举路径
BITABLE_TABLES_PATH: str = "/bitable/v1/apps/{app_token}/tables"

#: 附件素材上传路径（两阶段写入的第一步）
DRIVE_UPLOAD_PATH: str = "/drive/v1/medias/upload_all"

#: 附件上传时的父类型与父节点参数（官方《素材概述》）
ATTACHMENT_PARENT_TYPE: str = "bitable_file"