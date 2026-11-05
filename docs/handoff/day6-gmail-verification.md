# Day 6 Gmail 真实入站验收记录

> 验收日期：2026-10-31。本文只记录非敏感状态和结果，不记录 OAuth client secret、refresh/access token、Fernet key、Pub/Sub push token、authorization code、邮件正文、附件内容或完整带认证参数的 URL。

## 1. 验收范围与安全边界

本次只验收 Gmail，不涉及 Outlook 或 WhatsApp。过程中：

- 未读取或记录 `.env` 中的秘密值；
- 未记录 token、secret、OAuth code 或 auth state；
- 未发送真实客户消息；
- 使用专用测试邮件完成入站验证；
- 未执行未授权的迁移；生产 migration 由用户在备份后执行；
- Pub/Sub 日志中的认证 query 参数已脱敏；暴露过的旧 push token 已轮换。

## 2. 代码与部署状态

已完成并部署：

- Gmail OAuth state 与 `ChannelAccount` 绑定，不信任 callback URL 中的账号 ID；
- Google UserInfo stable subject 账号映射；
- refresh token 服务端 Fernet 加密保存；
- Gmail Watch 创建，并保存 `historyId` 与 expiration；
- Gmail API 按 `ChannelAccount` 读取加密凭据，不使用全局 refresh token；
- Pub/Sub payload 支持标准、URL-safe、无 padding Base64，以及数字/字符串 `historyId`；
- Watch 成功后才持久化账号凭据，Watch 失败不会留下新的半连接状态；
- 前端“我的 / 接入账号 / Gmail”入口仅调用后端，不保存 provider 凭据；
- fake fixture 继续保留并标记为 `test_only`。

生产部署后检查结果：

- backend 容器运行正常；
- PostgreSQL 容器为 `healthy`；
- `/health` 返回 HTTP 200 和 `{"status":"ok"}`；
- Alembic 当前版本为 `0008_gmail_account_runtime (head)`。

## 3. 离线测试证据

Gmail 定向后端测试（含 OAuth、Watch、Pub/Sub、入库、幂等和失败路径）：

```text
25 passed, 1 warning
```

warning 为当前 Starlette/httpx 组合的弃用提示。

前端测试：

```text
6 passed
```

前端 production build 成功，Python compileall 和 `git diff --check` 通过。

## 4. 真实 Gmail 账号状态

非敏感数据库状态（`ChannelAccount.id=1`）：

```text
status                    = connected_pending_inbound
external_account_id      = present
credential_reference     = present
gmail_credential_ciphertext= present (只确认存在，未读取内容)
gmail_watch_history_id   = present
gmail_watch_expiration    = present
```

该状态证明 OAuth、账号映射、凭据保存和 Gmail Watch 创建已完成；尚不自动宣称完整验收完成。

## 5. 真实入站证据

用户使用专用测试邮件发送后，backend 收到 Gmail Pub/Sub callback：

```text
3 callback requests observed
3 requests returned HTTP 202 Accepted
0 new 400 payload errors after parser deployment
```

数据库中出现一条真实 Gmail 入站消息（未读取正文）：

```text
channel_account_id  = 1
provider            = gmail_api_pubsub
direction           = inbound
status              = received
external_message_id = present
```

观察到多次 Pub/Sub callback 但数据库仅有一条对应 Message，符合当前 `(channel_account_id, provider, external_message_id)` 唯一约束和幂等入库行为。该观察不替代后续专门的重复投递回归，但证明本次实际投递没有产生重复 Message。

## 6. 当前验收结论

### 已证明

- Google OAuth 真实授权成功；
- 账号映射到 Gmail `ChannelAccount.id=1`；
- Gmail Watch 创建成功；
- Pub/Sub 从公网 callback 到 backend；
- Gmail History/Message 读取链路完成；
- normalized provider mapping 为 `gmail_api_pubsub`；
- Message 真实写入目标 PostgreSQL；
- 本次多次 callback 未产生重复 Message。

### 尚未单独证明

- 前端授权范围内收件箱页面显示该测试消息；
- 非授权用户无法读取该消息；
- 重新投递同一外部事件的专门重复测试；
- Watch 续订、expiration 恢复和 history cursor 过期 reconciliation；
- Pub/Sub OIDC/JWT 来源验证（当前仍使用已轮换的 shared push token）；
- 真实附件下载与附件 metadata；
- 真实 provider 限流、撤销和长时间运行监控。

## 7. Day6 状态

真实入站链路已通过真实测试邮件、Pub/Sub 202、Message 入库、cursor 推进和重复投递观察。状态收口代码已完成并通过离线回归：首次成功持久化真实 Gmail Message 后，`connected_pending_inbound` 自动转为 `verified_inbound`；`verified_inbound` 账号继续允许后续 Pub/Sub 读取。

状态收口代码已部署到生产 backend；backend 健康检查返回 `{"status":"ok"}`。最终测试邮件成功持久化后，线上账号已自动从 `connected_pending_inbound` 转为 `verified_inbound`。

最终非敏感状态：

```text
channel_account_id = 1
status             = verified_inbound
gmail_watch_cursor = advanced
message_count      = 4
latest_message     = received
```

## 8. 幂等与权限证据

离线/TestClient 重放和授权范围测试已执行：

```text
46 passed, 1 warning
```

已覆盖：

- 同一通知重复投递只创建一条 Message；
- 重放不重复创建 Inquiry、InquiryEvent、InternalNotification；
- 持久化 history cursor 按顺序推进；
- 跨账号和无 grant 读取被拒绝；
- 被撤销账号不能继续作为正常业务读取对象。

尚未记录为真实生产证据：

- Google Cloud Pub/Sub 控制台触发的同一消息 redelivery；现场控制台显示订阅没有保留消息或可用快照，因此无法执行恢复/重放。

已完成真实环境无权用户 API 验证：

- 系统用户 `user`，角色 `staff`；
- 数据库确认该用户没有 Gmail `ChannelGrant`；
- 登录 HTTP 200；
- `/api/channel-accounts` 返回 HTTP 403；
- `/api/messages` 返回 HTTP 403；
- 响应只记录状态，不记录邮件正文或认证材料。

## 9. 后续行动

1. 在授权用户界面确认测试消息可见；
2. 在 Google Cloud Pub/Sub subscription 中对已投递测试消息执行受控 redelivery，确认 Message 数量不增加；
3. 部署并验证 Watch 续订、OIDC/JWT、history reconciliation、撤销和限流监控。

## 10. 最新 Day6 收口状态（2026-11-04）

本记录前文保留了早期过程状态；以本节和总览记录为当前结论。基于本记录中的真实 Pub/Sub、目标 PostgreSQL、授权范围拒绝、外部账号映射和线上状态证据，Gmail 当前可记为：

```text
status = verified_inbound
```

仍未单独完成的项目保持为后续补充证据，不影响已记录的主入站链路：Pub/Sub OIDC/JWT、Watch 续订/过期恢复、history reconciliation、真实附件、provider 限流/撤销和专门的 Pub/Sub redelivery。不得把这些未验证项写成已通过。
