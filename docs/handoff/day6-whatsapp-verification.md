# Day 6 WhatsApp 真实入站验收记录

> 本记录只记录非敏感状态和代码/测试证据。不记录 QR、Baileys auth state、session 文件、adapter token、手机号、消息正文、附件内容或完整认证 URL。

## 1. 验收范围与策略

本次只记录 WhatsApp，不改变 Gmail 或 Outlook 的验收结论。

当前确认的实现策略是：

- Chat SDK community Baileys adapter；
- 项目自有 bridge 运行 WebSocket-based Baileys runtime；
- 账号所有者通过 WhatsApp Linked Devices 完成短时 QR 关联；
- bridge 通过内部控制接口提供 pair/status/disconnect；
- bridge 将 Chat SDK `onNewMessage` 事件规范化后发送到 backend inbound callback；
- backend 校验 adapter token、channel account、external account mapping 和 revoked 状态；
- 通过统一 `Message` 入库服务完成 provider mapping 和幂等写入；
- 不使用 Meta Cloud API；不自动发送消息；不将 QR/auth state 持久化到前端或业务数据库。

## 2. 文档与部署实现

已核对 Chat SDK Baileys 文档：

- adapter package：`chat-adapter-baileys`；
- 依赖 `baileys`、`chat`、`@chat-adapter/state-memory`；
- `connect()` 通过 WebSocket 接收消息；
- `handleWebhook()` 不是可用的入站 transport，文档说明其返回 501；
- 多账号要求每个账号独立 auth state 和唯一 adapter name；
- WhatsApp 没有 REST history API，实时事件需要自行持久化。

仓库已增加：

- [whatsapp-bridge/package.json](../../whatsapp-bridge/package.json)
- [whatsapp-bridge/src/index.ts](../../whatsapp-bridge/src/index.ts)
- [whatsapp-bridge/Dockerfile](../../whatsapp-bridge/Dockerfile)
- [whatsapp-bridge/README.md](../../whatsapp-bridge/README.md)
- [compose.yaml](../../compose.yaml) 中的 `whatsapp-bridge` service 和 `whatsapp_auth` named volume
- [backend/app/whatsapp_ingress.py](../../backend/app/whatsapp_ingress.py) 专用 inbound callback

bridge 不发布 host 端口，仅在 Compose 内部网络暴露控制端口。Baileys auth state 只放在 bridge 的独立 volume 中。

## 3. 代码调用链

```text
WhatsApp Linked Devices QR
→ Chat SDK/Baileys connect() WebSocket
→ bridge onNewMessage
→ POST /api/integrations/whatsapp/accounts/{account_id}/inbound
→ X-WhatsApp-Adapter-Token 校验
→ ChannelAccount channel_type/account_id/external_account_id 校验
→ revoked 状态拒绝
→ provider = whatsapp_web_baileys
→ common Message idempotent ingest
→ 授权范围内消息查询
```

统一入库入口为 [message_ingestion.py](../../backend/app/message_ingestion.py)。消息幂等身份为账号、provider、外部消息 ID。

## 4. 用户报告的真实运行状态

用户报告：

```text
WhatsApp 已关联；当前等待真实入站消息验收。
```

据此记录为：

```text
authorization / pairing = reported complete
connection             = connected_pending_inbound
real inbound           = not yet observed
mapping                = code path present; real event not observed
Message persistence     = offline/test evidence only for WhatsApp
real duplicate replay  = not performed
```

该用户报告证明控制面关联已完成，但不证明 WebSocket 消息 handler、真实 external message ID、backend callback、目标数据库写入和收件箱显示均已通过。

## 5. 离线测试证据

WhatsApp backend 定向测试覆盖：

- adapter HTTP pairing contract；
- inbound adapter token 错误；
- 正确 token 入站；
- external account 映射；
- revoked 账号拒绝；
- provider mapping；
- 重复 external message ID 幂等；
- Message 写入路径。

这些是 fixture/TestClient/provider-contract 证据，标记为 `test_only`，不能替代真实 WhatsApp 消息验收。

前端 unit test 和 production build 已通过；bridge 运行时的真实 Docker build、扫码后的真实消息接收和生产数据库写入尚未在本记录中声称通过。

## 6. 当前未完成的真实证据

尚未观察到一条来自其他 WhatsApp 身份的真实入站消息，因此以下项目仍未验证：

1. Baileys WebSocket 实际收到 `messages.upsert`；
2. Chat SDK `onNewMessage` 实际触发；
3. bridge 能取得稳定 `external_account_id`；
4. bridge 能取得真实 `external_message_id`；
5. backend inbound callback 实际返回 Accepted；
6. `whatsapp_web_baileys` Message 实际写入目标 PostgreSQL；
7. 授权用户收件箱显示真实消息；
8. 同一真实事件重放不产生第二条 Message；
9. 断开后新事件拒绝且历史消息保留。

## 7. 2026-11-02 验收执行记录

用户提供的页面状态截图显示：

```text
WhatsApp = connected_pending_inbound
Gmail    = verified_inbound
Outlook  = connected_pending_inbound
```

本轮未发送或模拟 WhatsApp 消息，未读取 QR/auth state，未连接账号执行操作；截图只作为用户提供的非敏感状态证据。它证明 WhatsApp 已完成关联/连接控制面，但不证明真实入站。

自动化验收命令与结果：

```text
backend provider tests: 37 passed, 1 warning
backend compileall: passed
git diff --check: passed
docker compose config -q: passed
frontend unit tests: 6 passed
frontend production build: passed
bridge TypeScript build: skipped; whatsapp-bridge/node_modules absent
```

provider tests 覆盖 Gmail、Outlook contract、WhatsApp adapter HTTP、WhatsApp inbound token/mapping/revoked/幂等路径。fixture/TestClient 结果均为 `test_only`，不替代真实 WhatsApp 消息。

## 8. 2026-11-04 真实入站证据与状态收口

用户提供的收件箱截图显示一条真实 WhatsApp 消息已进入授权范围：

```text
channel_type = whatsapp
status       = received
内容标识     = 用户截图中的 hi（正文不复制到本文）
```

该证据表明真实消息已经经过 WhatsApp/Baileys → bridge → backend inbound → 账号映射 → `whatsapp_web_baileys` → Message 入库 → 收件箱显示。截图不包含 provider 全字段、external message ID 或数据库计数，因此这些字段不在本文中臆测。

随后已将成功入库后的状态收口逻辑补齐：

- Outlook 主动读取成功并完成 Message 幂等处理：`connected_pending_inbound → verified_inbound`；
- WhatsApp 合法 adapter 事件完成 token、账号映射并进入幂等入库：`connected_pending_inbound → verified_inbound`；
- 重复事件不回退状态；认证、映射、provider 或数据库失败不更新状态。

变更后的定向测试结果：

```text
25 passed, 1 warning
backend compileall: passed
git diff --check: passed
```

此前页面没有自动更新的原因是：Gmail callback 已有显式状态收口，但 Outlook 和 WhatsApp 原先只保存消息并返回结果，没有在成功入库事务中更新 `ChannelAccount.status`。因此消息已经收到，状态仍停留在 `connected_pending_inbound`。该代码缺口现已修复。

## 9. 当前 Day6 状态

基于用户提供的真实 WhatsApp 收件箱证据，WhatsApp 可记录为：

```text
real inbound = observed
status       = verified_inbound (状态收口代码已补齐；需刷新页面确认线上状态)
```

若线上刷新后仍显示 `connected_pending_inbound`，说明运行中的 backend 尚未部署本次状态收口代码；应部署/重启 backend 后再次刷新，不能把旧页面状态当作新代码结果。

仍未单独完成的证据：

- 同一真实事件的生产重放幂等；
- 断开后新事件拒绝且历史消息保留；
- bridge 当前版本的现场 TypeScript build（此前因本地缺少 `node_modules` 未执行）。

## 10. 最小后续验收

在不使用真实客户内容的前提下，由另一 WhatsApp 身份发送一条专用测试消息，然后核对：

- bridge 日志只记录非敏感事件状态；
- backend inbound callback 被调用并接受；
- `channel_account_id` 和 `external_account_id` 正确；
- `provider=whatsapp_web_baileys`；
- `direction=inbound`；
- external message ID 存在；
- 目标数据库只有一条对应 Message；
- 授权用户可在收件箱查询；
- 重放同一 external message ID 不新增 Message；
- disconnect/revoked 后新入站被拒绝，历史消息不删除。

只有上述真实证据完成后，才可将状态更新为 `verified_inbound`。

## 11. 最新 Day6 收口状态（2026-11-04）

基于用户提供的真实收件箱消息证据和线上页面状态，WhatsApp 主入站链路可记录为：

```text
status       = verified_inbound
real inbound = observed
```

该结论只覆盖已观察到的真实入站主链路，不扩展为以下尚未单独取证项目：真实事件生产重放幂等、disconnect/revoked 后新事件拒绝与历史保留、重新关联恢复，以及 bridge 当前版本的现场构建结果。由于当前没有另一 WhatsApp 个人账号，跨身份测试保持待执行；不得用 fixture 或手工 normalized 请求代替该证据。

## 12. 当前收口口径（2026-11-04）

本记录前文保留了尚未观察真实入站时的过程记录；以第 8、9、11 节和总览记录为当前结论。当前真实收件箱消息、账号映射、backend inbound callback、`whatsapp_web_baileys` mapping、Message 入库和页面显示已构成 WhatsApp 真实入站主链路证据，账号状态可标记为 `verified_inbound`。

系统账号退出登录只撤销本项目用户 session，不等同于 WhatsApp 关联设备断开。真实 provider 断开/重连、生产重放幂等和跨身份测试仍保留为补充环境核验项；没有第二个 WhatsApp 个人账号时，必须明确记录该测试阻塞。
