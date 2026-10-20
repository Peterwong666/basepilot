---
name: Bug 报告
about: 报告一个可复现的问题
title: "[Bug] "
labels: bug
---

## 问题描述

<!-- 一句话说清发生了什么 -->

## 复现步骤

1.
2.
3.

## 期望行为 / 实际行为

<!-- 期望得到什么，实际得到什么（含完整报错文本或飞书错误码，如 1254064） -->

## doctor 输出

<!-- 粘贴 `basepilot-mcp doctor` 的完整 JSON 输出（它不含任何凭证，可安全粘贴） -->

```json

```

## 环境信息

- OS：
- Python 版本：
- basepilot 版本（`basepilot-mcp --version`）：
- 接入方式（Claude Code / Cursor / 其他）：

## 安全自查（提交前必读）

- [ ] 我已确认本 issue **不含** app_secret、tenant_access_token、.env 内容
- [ ] 日志中的 app_token / table_id / record_id 已打码（它们暴露租户身份）
