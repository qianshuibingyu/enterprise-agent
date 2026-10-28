# Day 4 运营工作台、客户链路与内部只读分析验证记录

> 本记录只保存已发生的代码、测试、构建和环境验证证据。隔离 SQLite/TestClient、fake/provider-neutral、静态 migration 检查和生产 API 冒烟不能互相替代，也不能替代真实 provider 或目标 PostgreSQL 验收。本文不记录密码、token、session cookie、QR、auth state、完整连接串或客户敏感原始内容。

## 1. 状态规则与本轮结论

状态含义：

- **已实现**：代码已写入当前工作区，不等于测试或目标环境通过。
- **隔离测试通过**：用户在本地隔离环境执行并得到通过结果。
- **目标 PostgreSQL 已核验**：用户实际查询/应用目标库后有本轮证据。
- **真实 provider 已验收**：具备资格的真实账号完成授权和真实入站等规定验收。
- **待验收/未完成**：缺少相应证据，或当前实现/测试仍有缺口。

当前 Day 4 准确结论：

- 收件箱、询盘链路、转交、InquiryEvent、确定性只读分析和人工处理状态已有代码实现；
- 当前最新业务授权测试结果为 **23 passed, 1 failed, 1 warning**，失败来自分析响应中零值状态键的断言不一致，因此最新人工状态增量不能标为全通过；
- 此前用户提供的 **72 tests collected、72 passed、2 warnings** 发生在本轮 `handling_status` 增量之前，不能覆盖当前版本；
- 前端人工状态增量已写入，但该增量后的前端单元测试和生产构建尚无新输出；
- 目标 PostgreSQL 当前 `0006`/`0007` migration/schema 没有本轮在线应用证据；
- Gmail、Outlook、WhatsApp 真实授权和真实入站均未验收；
- 当前不进行真实出站发送。

## 2. 收件箱、询盘和授权查询

### 2.1 当前代码

相关实现：

- `backend/app/authorization.py`
- `backend/app/business_routes.py`
- `backend/app/models/business.py`
- `backend/tests/test_business_authorization.py`

当前接口：

```text
GET /api/channel-accounts
GET /api/messages
GET /api/messages/{message_id}
GET /api/inquiries
GET /api/inquiries/{inquiry_id}
```

授权范围：

- 运营/普通用户通过本人 `ChannelAccount` 所有权和 `ChannelGrant` 查询渠道账号；
- 运营只能读取本人授权渠道范围内的消息和询盘；
- sales 只能读取 `assigned_sales_user_id == 当前用户.id` 的询盘；
- sales 的消息查询当前返回空集，因为 `Message` 尚无 `Inquiry`/conversation 外键，不能从账号级询盘分配推导该账号全部消息可见；
- 未认证、跨账号、跨用户和猜测不存在/无权 ID 统一拒绝；
- 附件响应只返回文件名、媒体类型和大小，不返回 `storage_reference`。

### 2.2 当前响应边界

`Message` 同时返回：

- provider 入站 `status`，以 `ingestion_status` 暴露；
- 人工 `handling_status`；
- 渠道账号、provider、外部消息 ID、方向、时间、原始内容和附件 metadata。

`Inquiry` 同时返回：

- 业务 `status`：`new`/`assigned`；
- 人工 `handling_status`：`pending`/`processed`/`ignored`；
- 负责人、原始内容、来源渠道、时间、附件 metadata 和事件时间线。

`Message` 与 `Inquiry` 的正式外键/conversation 关系仍未实现，继续作为实现前验证项。

## 3. 人工状态动作、转交和事件

### 3.1 询盘人工动作

接口：

```text
POST /api/inquiries/{inquiry_id}/action
```

允许动作：

```text
processed
ignored
```

当前代码行为：

- 对象授权先于写入；
- sales 被拒绝；
- 同状态重复动作直接返回当前对象，不重复事件；
- 状态变更和 `InquiryEvent` 在同一事务中提交；
- commit 失败执行 rollback；
- 事件类型为 `inquiry_processed` 或 `inquiry_ignored`；
- 不改变 `Inquiry.status` 的 `new`/`assigned` 语义。

### 3.2 消息人工动作

接口：

```text
POST /api/messages/{message_id}/action
```

允许动作：

```text
processed
ignored
```

当前代码行为：

- 对象授权先于写入；
- sales 被拒绝；
- 同状态重复动作幂等；
- 更新 `Message.handling_status`；
- 不改变 provider 入站 `Message.status`；
- commit 失败 rollback；
- 当前没有独立 Message 事件历史模型，不能把消息动作伪装成 `InquiryEvent`。

此前发现的消息动作返回值未赋给局部变量的 `NameError` 已在当前代码修正为使用 `message = get_scoped_message(...)`。

### 3.3 手动转交

接口：

```text
POST /api/inquiries/{inquiry_id}/transfer
```

当前代码行为：

- CSRF/Origin 保护；
- sales 不能发起；
- 目标必须是 active `sales` 用户；
- 询盘读取使用 `for_update=True` 语义；
- 相同目标重复提交幂等；
- 不同目标改派拒绝；
- 询盘状态、`InternalNotification` 和 `InquiryEvent` 同一事务；
- `db.add()` 或 `commit()` 失败均 rollback。

### 3.4 已实现的模型/迁移

当前 ORM 包含：

- `Inquiry.handling_status`；
- `Message.handling_status`；
- `InquiryEvent`；
- `Inquiry.events` 关系。

当前 migration 链代码为：

```text
0001_auth_sessions
→ 0002_business_authorization
→ 0003_messages
→ 0004_inquiry_events
→ 0005_channel_external_account
→ 0006_manual_handling_status
→ 0007_message_handling_status
```

`0006`/`0007` 的代码已写入，但没有目标 PostgreSQL 在线应用证据。

## 4. 确定性内部只读分析

接口：

```text
POST /api/internal-analysis
```

`operation=read` 当前返回：

- 授权范围内 `received` 消息计数；
- 询盘按 `Inquiry.status` 分组；
- 询盘按 `handling_status` 分组；
- 当前 sales 的本人转交事项；
- 当前阶段和最近可用事件；
- 当前授权渠道状态；
- `blocked`、`error`、`revoked`、`not_connected` 异常标记；
- `read_only: true`；
- fixture/test-only 边界说明。

`create`、`update`、`delete`、`assign`、`send` 只返回页面路径和操作指引，不修改数据库。

没有接入 LLM，没有新增客户画像、评分、自动标签、报表或跨部门汇总。

### 4.1 当前已知失败

用户实际执行业务测试时，以下断言失败：

```text
实际: {'processed': 1}
预期: {'pending': 0, 'processed': 1}
```

失败测试：

```text
test_inquiry_handling_action_can_be_processed_and_analysis_counts_it
```

因此当前实现/测试对“缺失计数键是否补零”的响应契约尚未统一。该失败必须在后续代码或测试合同明确后重新验证；当前不能标为通过。

## 5. 前端客户链路和 API

相关文件：

- `frontend/src/App.vue`
- `frontend/src/api/inbox.ts`
- `frontend/src/api/channels.ts`
- `frontend/src/channelCenter.ts`

当前页面已实现代码范围：

- 询盘列表、消息列表和客户链路详情；
- `Inquiry.status` 阶段/状态；
- 负责人、来源渠道、原始内容和附件 metadata；
- 创建/更新时间和 `InquiryEvent` timeline；
- `handling_status` 展示；
- 询盘 `processed`/`ignored` 按钮；
- 消息 `processed`/`ignored` 按钮；
- CSRF 获取和 API 动作调用；
- 动作提交期间防重复点击；
- 成功后重新加载；
- API 错误、401/403、空数据和重试；
- 明显的 `TEST_ONLY / fixture` 标记；
- fake 渠道连接中心。

当前前端 API client 已包含：

```text
updateInquiryHandling()
updateMessageHandling()
getInternalAnalysis()
getCsrf()
transferInquiry()
```

业务类型字段当前不存在，页面明确显示未提供；没有引入 Vue Flow、客户画像、评分、报表、token、QR 或 auth state。

本轮人工状态增量后的前端单元测试和 `npm run build` 没有新的用户输出，因此保持待验证。

## 6. 隔离/fake 测试证据

### 6.1 用户已提供的历史证据

此前用户实际执行：

```text
python -m pytest --collect-only -q
```

结果：

```text
72 tests collected in 2.14s
```

此前用户实际执行全部后端测试：

```text
72 passed, 2 warnings in 23.88s
```

此前用户实际执行前端单元测试：

```text
6 passed
```

此前用户实际执行前端构建成功。

这些结果发生在本轮 `handling_status`、`0006`、`0007` 增量之前，不能覆盖当前工作区的最新状态。

### 6.2 当前最新业务测试证据

用户在 `/root/enterprise-agent/backend` 执行：

```text
python -m pytest -q tests/test_business_authorization.py
```

实际结果：

```text
23 passed, 1 failed, 1 warning
```

失败原因仅为分析响应中缺少 `pending: 0` 键的断言差异；该结果说明当前业务测试整体尚未通过。

### 6.3 当前 fake/fixture 覆盖范围

当前 fixture/隔离代码覆盖：

- 运营和 sales 授权隔离；
- 正常和 blocked 渠道状态；
- 未认证和 ID 枚举；
- 消息/询盘附件 metadata 脱敏；
- 询盘转交幂等；
- InquiryEvent 时间线；
- 询盘人工状态幂等；
- 消息人工状态幂等；
- commit 失败 rollback；
- 内部只读分析；
- fake/provider-neutral 消息入库和 Gmail 测试。

但当前最新完整回归尚未重新提供，不能把上述范围写成当前版本全部通过。

## 7. 目标 PostgreSQL migration/schema

### 7.1 当前代码证据

当前 revision 链代码 head 为：

```text
0007_message_handling_status
```

静态 migration 测试代码已更新为检查 `0001`–`0007` 链和 `0006`/`0007` 字段/约束。

### 7.2 在线目标库证据

本轮没有新的目标 PostgreSQL：

- `alembic current`；
- `alembic heads`；
- `alembic_version` 查询；
- `inquiries.handling_status` 查询；
- `messages.handling_status` 查询；
- CHECK/index/foreign key 查询；
- `0006`/`0007` `upgrade` 结果。

因此：

> **目标 PostgreSQL migration/schema 当前为待验收，不能写成已应用。**

SQLite/TestClient 和静态 migration 测试不证明目标 PostgreSQL 已存在这些字段和约束。PostgreSQL 行级锁、并发转交和真实事务行为也未验收。

## 8. 真实 Gmail/Outlook/WhatsApp 授权与入站

### Gmail

当前代码/provider-neutral 方案：

```text
gmail_api_pubsub
Google OAuth
Gmail API
Pub/Sub webhook
History/Message API
```

真实 Gmail OAuth、Pub/Sub、History/Message 拉取、附件和真实入站没有验收证据。

### Outlook

当前 provider descriptor：

```text
outlook_mcp_graph
```

授权边界：

```text
outlook_mcp_entra
```

真实 Outlook MCP、Microsoft Graph/Entra 委派授权、邮箱映射、主动读取和附件没有验收证据。

旧 `outlook_imap` 仅保留 legacy provider key 映射，不能写成当前真实接入方案。

### WhatsApp

当前 provider descriptor：

```text
whatsapp_web_baileys
```

真实 Baileys adapter、账号所有者 QR、加密 auth state、重连/断开、媒体入站没有验收证据。

所有 fake/provider-neutral 结果都不能写成真实渠道已连接或真实入站通过。

## 9. 已知生产环境证据与限制

用户此前提供过以下实际环境结果：

- `GET http://127.0.0.1:8000/health` 返回 `200` 和 `{"status":"ok"}`；
- 外部 HTTPS 页面后来返回 Vue 构建页面；
- 未登录 `GET https://qianshuibingyu.xyz/api/channels` 返回 `401`；
- `GET /auth/csrf` 在 `AUTH_ORIGIN` 修正并重建 backend 后返回 `200`；
- frontend 镜像构建成功并启动；
- backend、db、frontend 容器曾显示启动，其中 db 显示 healthy。

这些是当时用户提供的环境证据，不代表当前最新 `handling_status` bundle 已重新部署，也不证明目标 PostgreSQL 或真实 provider 通过。

此前 Compose 曾报告旧 orphan container：

```text
enterprise-agent-api-1
```

当前未收到其清理或最终状态证据。

## 10. 阻塞和未覆盖边界

当前阻塞/未覆盖：

1. 最新业务授权测试仍有 1 个失败；
2. 最新全量 backend 测试尚未重新执行；
3. 最新前端单元测试和生产构建尚未重新执行；
4. `0006`/`0007` 尚未在目标 PostgreSQL 在线应用核验；
5. SQLite 无法证明 PostgreSQL 行级锁和跨进程并发；
6. Message 与 Inquiry/conversation 关联尚未确认/实现；
7. 业务类型和售后/静默阶段没有当前字段；
8. Message 没有独立持久化事件历史模型；
9. 真实 Gmail/Outlook/WhatsApp 授权和入站未验收；
10. 真实附件、调度、恢复和最终出站未验收；
11. 生产最新 frontend bundle 是否部署尚无本轮输出；
12. 备份恢复、HTTPS 长期运行和重启恢复未在本轮验证。

## 11. 当前分层结论

| 范围 | 当前状态 |
|---|---|
| 收件箱授权查询 | 已实现；有历史隔离测试证据 |
| 询盘/消息详情 | 已实现；附件 metadata 脱敏 |
| InquiryEvent timeline | 已实现；当前代码包含创建/转交/人工状态事件 |
| 询盘人工状态 | 已实现代码；最新业务测试受分析键断言失败影响 |
| 消息人工状态 | 已实现代码；当前版本全量测试尚未重新提供 |
| 转交幂等与 rollback | 已实现代码；有隔离测试代码和历史测试证据 |
| 内部只读分析 | 已实现代码；最新响应键契约仍需统一并重新验证 |
| 前端 API/UI | 已实现代码；最新构建尚未重新验证 |
| 隔离/fake 测试 | 当前最新业务测试为 23 passed、1 failed |
| 目标 PostgreSQL | 待 `0001`–`0007` 在线 migration/schema 验收 |
| Gmail | provider-neutral/fake；真实授权和入站待验收 |
| Outlook | provider-neutral/MCP；真实授权和入站待验收 |
| WhatsApp | adapter contract/fake；真实授权和入站待验收 |
| 真实出站 | 未执行，保留到最终项目验收 |

**Day 4 当前不能标记为整体完成。** 当前准确表述为：内部代码增量大部分已实现，最新隔离回归尚有一个已知失败，目标 PostgreSQL 新 migration 和真实三渠道仍待用户后置验收。
