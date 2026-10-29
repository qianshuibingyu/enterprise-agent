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
- 早期 `23 passed, 1 failed, 1 warning` 是历史分析响应合同差异，已由固定状态键合同修复；
- 用户后续已执行跨功能定向回归并得到 `66 passed, 1 warning`，后端全量回归并得到 `105 passed, 2 warnings`，随后再次得到 `105 passed, 2 warnings`；
- 这些后端结果覆盖当前工作区 Day 4/Day 5 业务授权、转交、人工状态、只读分析和入站回归；
- 当前目标环境核对到 `0005_channel_external_account (head)`，运行 backend 容器内 migration 文件为 `0001`–`0005`；不能把旧文档提到的 `0006`/`0007`写成当前待应用项；
- 目标 PostgreSQL 字段/约束/跨进程并发专项仍待核验；
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

### 4.1 分析响应合同（Day 5 收口）

历史 Day 4 测试曾记录以下差异：

```text
实际: {'processed': 1}
预期: {'pending': 0, 'processed': 1}
```

本轮依据当前已确认业务状态和现有前端调用方，将 `POST /api/internal-analysis` 的只读分析响应统一为固定键合同：

- `inquiries_by_status` 固定返回 `new`、`assigned`；
- `inquiries_by_handling_status` 固定返回 `pending`、`processed`、`ignored`；
- 当前授权范围内不存在的状态返回数值 `0`；
- 不增加售后、静默、部门或其他未确认状态；
- 聚合仍先经过现有对象授权查询，不改变授权范围；
- `read_only` 分支不修改数据库；
- 非 `read` 操作继续只返回页面路径和操作指导。

本轮已更新后端合同、业务授权测试、前端 API 类型及分析卡片。历史差异已通过本地隔离回归重新验证，不代表目标 PostgreSQL 或真实 provider 已验收。

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

本轮人工状态和 Day 5 前端增量后的最新前端单元测试/构建结果仍未由用户提供，因此前端最新 bundle 保持待验证；此前历史构建结果不能覆盖当前工作区。

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

### 6.2 Day 5 分析合同回归证据

本轮在 `/root/enterprise-agent/backend` 使用仓库隔离环境执行：

```text
../.venv/bin/pytest -q tests/test_business_authorization.py
```

实际结果：

```text
25 passed, 1 warning in 23.98s
```

本轮覆盖了固定状态键、单一状态补零、空授权范围全零、sales 授权范围、未授权对象拒绝、只读不变更和非 `read` 操作 guidance。warning 为 Starlette 关于当前 `httpx` 组合的弃用提示，不是业务测试失败。

该结果仅证明隔离 SQLite/TestClient 行为；不证明目标 PostgreSQL migration/schema、并发锁行为或真实 provider 已验收。

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

用户后续已执行跨功能定向回归 `66 passed, 1 warning`，并执行后端全量回归 `105 passed, 2 warnings`；随后再次执行全量回归，结果为 `105 passed, 2 warnings`。这些结果覆盖当前工作区后端 Day 4/Day 5 业务和入站回归，但不证明目标 PostgreSQL 或真实 provider。

## 7. 目标 PostgreSQL migration/schema

### 7.1 当前代码证据

当前工作区 ORM/测试包含人工处理状态字段和相关行为；但用户核对的运行 backend 容器内 migration 文件只有 `0001`–`0005`。

用户执行目标环境只读 revision 查询，结果为：

```text
current: 0005_channel_external_account (head)
heads:   0005_channel_external_account (head)
```

因此当前准确结论是：

- 目标环境 revision/head 已核对为 `0005`；
- 当前运行容器内没有 `0006`/`0007`；
- 不能把 `0006`/`0007`写成当前待应用 migration；
- 当前没有人工状态字段、CHECK/index/foreign key 和跨进程并发专项查询证据；
- 本地 SQLite/TestClient 和静态 migration 测试不证明目标 PostgreSQL schema。

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

1. 最新前端单元测试和生产构建尚未由用户重新提供；
2. 当前运行 backend 容器和目标数据库为 `0005`，与工作区人工状态 ORM/测试增量的部署一致性尚未核对；
3. 当前没有目标 PostgreSQL 人工状态字段、CHECK/index/foreign key 和跨进程并发专项查询；
4. SQLite 无法证明 PostgreSQL 行级锁和跨进程并发；
5. Message 与 Inquiry/conversation 关联尚未确认/实现；
6. 业务类型和售后/静默阶段没有当前字段；
7. Message 没有独立持久化事件历史模型；
8. 真实 Gmail/Outlook/WhatsApp 授权和入站未验收；
9. 真实附件、调度、恢复和最终出站未验收；
10. 生产最新 frontend bundle 是否部署尚无本轮输出；
11. 备份恢复、HTTPS 长期运行和重启恢复未在本轮验证。

## 11. 当前分层结论

| 范围 | 当前状态 |
|---|---|
| 收件箱授权查询 | 已实现；有历史隔离测试证据 |
| 询盘/消息详情 | 已实现；附件 metadata 脱敏 |
| InquiryEvent timeline | 已实现；当前代码包含创建/转交/人工状态事件 |
| 询盘人工状态 | 已实现代码；本地后端回归通过；运行容器/目标 schema 一致性待核对 |
| 消息人工状态 | 已实现代码；本地后端回归通过；运行容器/目标 schema 一致性待核对 |
| 转交幂等与 rollback | 已实现代码；定向和全量后端回归通过 |
| 内部只读分析 | 固定状态键合同已实现并通过后端回归 |
| 前端 API/UI | 已实现代码；当前工作区最新前端测试/构建待用户执行 |
| 隔离/fake 测试 | 定向 `66 passed, 1 warning`；全量 `105 passed, 2 warnings` |
| 目标 PostgreSQL | 当前 revision/head 为 `0005`；人工状态 schema/并发专项待核验 |
| Gmail | provider-neutral/fake；真实授权和入站待验收 |
| Outlook | provider-neutral/MCP；真实授权和入站待验收 |
| WhatsApp | adapter contract/fake；真实授权和入站待验收 |
| 真实出站 | 未执行，保留到最终项目验收 |

**Day 4 当前不能标记为整体完成。** 当前准确表述为：内部代码增量大部分已实现，最新隔离回归尚有一个已知失败，目标 PostgreSQL 新 migration 和真实三渠道仍待用户后置验收。
