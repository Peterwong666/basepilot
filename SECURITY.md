# 安全政策

## 报告安全问题

请通过 **GitHub Security Advisory** 私密报告：
本仓库页面 → Security → Advisories → Report a vulnerability。

**不要**开公开 issue 报告安全漏洞。

## 重要提醒

- **绝不要**在 issue / PR / discussion 中粘贴 `app_secret`、`tenant_access_token`
  或 `.env` 内容。这些信息一旦发出即视为泄漏，请立即到飞书开放平台重置。
- app_id / app_token / table_id / record_id 不是密钥，但会暴露租户身份，
  公开贴日志前请打码（本项目 cassette 的脱敏规则也是这么处理的）。
- 如果怀疑凭证已泄漏：先在飞书开放平台**重置 app_secret**，再排查泄漏途径。

## 本项目自身的安全设计

- 删除工具默认 dry-run，须显式确认才真删
- cassette 录制即脱敏，仓库有「凭证零入库」机器门禁
- 详见 README「安全设计」一节
