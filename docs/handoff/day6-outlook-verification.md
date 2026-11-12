# Day 6 Outlook 真实主动读取验收记录

> 本记录只记录非敏感状态和结果，不记录密码、client secret、access/refresh token、authorization code、MCP bearer token、邮件正文或附件内容。

## 1. 当前策略

Outlook 采用 Microsoft Graph 只读主动读取，不是 webhook 或后台实时 watcher：

```text
Microsoft 官方授权
→ ChannelAccount 账号映射
→ 用户主动读取 Inbox/Junk
→ outlook_mcp_graph mapping
→ Message 幂等入库
→ 授权范围内收件箱查询
```

## 2. 2026-11-04 真实入站证据

用户提供的 Outlook 页面显示已通过项目主动读取入口处理专用测试邮件，页面结果为：

```text
确认总数 = 10
新增     = 8
重复     = 2
```

页面同时显示 Outlook 状态为 `verified_inbound`。该结果与当前后端主动读取响应合同一致：读取结果经过 `outlook_mcp_graph` mapping，并通过统一 Message 幂等入库返回新增/重复统计。截图不记录邮件正文、token 或 bearer credential。

## 3. 代码状态收口

已补充成功读取后的状态规则：

- Outlook 主动读取返回至少一条有效规范化消息；
- 消息新建或命中唯一键幂等记录；
- 当前账号状态为 `connected_pending_inbound`；
- 同一事务成功提交后，状态更新为 `verified_inbound`；
- 读取失败、账号映射失败、认证失败或数据库失败不更新状态。

定向测试结果：

```text
25 passed, 1 warning
backend compileall: passed
git diff --check: passed
```

## 4. Outlook 当前状态

```text
verified_inbound
```

页面中的主动读取结果已提供 Day6 主入站链路的非敏感证据。以下项目仍需单独记录或继续观察：真实目标 PostgreSQL revision/约束核验、授权用户收件箱显示的独立证据、provider 撤销/限流/失败恢复，以及后续主动读取的稳定幂等结果。

当前页面结果已将账号状态收口为 `verified_inbound`。以下清单作为 Day6 证据的持续核对项保存；如任一项未能从真实运行记录确认，应在环境记录中标为待验收，而不是用页面文案替代：

- 返回成功；
- `provider=outlook_mcp_graph`；
- `direction=inbound`；
- external message ID 存在；
- Message 写入目标数据库；
- 收件箱可见；
- 第二次读取不重复入库。

## 5. 最新收口口径（2026-11-04）

本记录前文保留了早期 `connected_pending_inbound` 和“截图不足”的过程记录；以本节和总览记录为当前结论。用户提供的最新页面显示 Outlook 主动读取完成（确认 10 条、新增 8 条、重复 2 条），且账号状态为 `verified_inbound`。因此 Outlook 的真实主动读取主链路可标记为完成。

仍不扩展为以下未单独取证能力：后台长期 watcher、附件下载、限流/撤销恢复和生产环境长期监控。系统账号退出登录只撤销本项目 session，不等同于 Microsoft 官方授权撤销。

## 6. 2026-11-05 补充：邮件详情深链修复

早期入库的 10 条消息 `provider_web_link` 全部为空，导致「去渠道处理」只能回落到写死的
`https://outlook.office.com/mail/inbox`；该账号是个人 Microsoft 账号
（`wafutechnology@outlook.com`，Graph id 为 16 位 hex），工作邮箱域名会要求重新登录 Microsoft，
表现为“每条消息都要重新授权”。

修复后：Graph 的 `webLink` 会在首次点击时现场补取并落库，兜底主机按账号类型选择
（个人 → `outlook.live.com`，工作 → `outlook.office.com`），主动读取时还会限量补齐历史行的链接。
线上复核：`channel_account_id=3` 的 10 条消息 `provider_web_link` 全部非空，
`/api/messages/{id}/provider-action` 返回真实 `ItemID` 详情地址。

完整排查链路见 `day6-provider-deeplink.md`。
