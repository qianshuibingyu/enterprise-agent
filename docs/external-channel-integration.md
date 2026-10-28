# 外部渠道接入方案

> 本文是当前 `enterprise-agent` 的渠道接入决策与实现参考。原始材料来自 `E:/Desktop/VibeCoding/ownerblog/blog_src`，其中的 Django/DRF 目录和代码路径仅作为历史参考，不直接适用于当前 FastAPI + SQLAlchemy + Alembic 项目。
>
> **当前渠道策略已由用户确认（2026-10-28）：**
>
> - WhatsApp：不走 OAuth；由项目自有独立 WhatsApp Web + Baileys adapter 提供短时 QR、关联设备扫码、加密 auth state、连接/重连和入站事件。
> - Gmail：由本项目直接完成 Google OAuth，使用 Gmail API、Gmail Watch、Google Pub/Sub、History API 和 Message API；不使用 OpenClaw 或 `gog/gogcli` 作为 Gmail 默认接入层。
> - Outlook：当前仓库不内置 Outlook watcher；通过外部 Outlook MCP Server 使用 Microsoft Graph 和 Entra OAuth 个人委派授权，按用户主动读取，不做后台长期无人值守。Microsoft Teams 插件不等同于 Outlook 邮箱接入。
>
> 该策略描述目标集成边界，不代表 OpenClaw、gog/gogcli、Outlook MCP Server、平台账号或真实渠道已经配置、授权或验收。外部工具的官方文档路径由用户保管，不把本机路径或凭据写入仓库。

## 1. 当前源码基线

OwnerBlog 当前是 Django + Django REST Framework + SQLite + Chroma 项目，已有：

- `backend/config/urls.py`：Django API 根路由；
- `backend/config/settings.py`：集中环境变量配置；
- `backend/accounts/`：Session/Cookie 登录；
- `backend/articles/`：文章、审核、发布、下架和删除；
- `backend/articles/services.py`：`transaction.atomic()`、`transaction.on_commit()` 和审核通知；
- `backend/notifications/models.py`：数据库站内通知；
- `backend/knowledge/`：同步 RAG、Embedding、Chroma 和问答 API。

当前没有：

- WhatsApp、Gmail、Outlook、Teams 的真实接入；
- 通用 Webhook；
- 外部凭证加密存储；
- 入站事件幂等表；
- 外部消息发送和投递记录；
- Celery、RQ 或其他持久化任务队列；
- 外部邮件、聊天或推送通知。

因此，在真实账号和端到端验收完成前，不能把任何渠道描述为“已接通”。

## 2. 推荐扩展边界

建议在 OwnerBlog 后端新增独立 Django App：

```text
backend/integrations/
├─ apps.py
├─ urls.py
├─ models.py
├─ admin.py
├─ permissions.py
├─ providers/
│  ├─ base.py
│  ├─ gmail.py
│  ├─ outlook_imap.py
│  ├─ whatsapp.py
│  └─ teams.py
├─ services/
│  ├─ ingest.py
│  ├─ routing.py
│  ├─ dispatch.py
│  ├─ credentials.py
│  └─ security.py
├─ management/commands/
│  ├─ poll_outlook.py
│  └─ reconcile_gmail.py
├─ migrations/
└─ tests/
```

在 `backend/config/settings.py` 注册 `integrations`，在 `backend/config/urls.py` 增加：

```python
path("api/integrations/", include("integrations.urls")),
```

统一数据流：

```text
外部平台
  -> Provider Adapter
  -> InboundEvent
  -> 验签、账号匹配、权限校验、幂等去重
  -> IntegrationEvent / 处理任务
  -> 站内通知、文章导入或知识库任务
  -> 人工确认后的外部发送
```

Provider 只负责外部协议和数据转换，不直接修改 `Article.status`、`Article.index_status`、Chroma 或用户权限。

## 3. 统一领域模型

### ChannelAccount

```text
id
owner_id
provider
integration_type
display_name
external_account_id
status
capabilities_json
last_checked_at
last_inbound_at
last_error_code
last_error_message
created_at
updated_at
```

`integration_type`：

```text
chat_channel
event_hook
mail_listener
```

### Credential

```text
id
channel_account_id
credential_type
ciphertext_or_secret_ref
key_version
expires_at
last_refreshed_at
revoked_at
created_at
updated_at
```

生产环境优先使用 KMS、Secret Manager 或 Vault。开发环境可以使用后端环境变量提供加密密钥，但不能明文保存 OAuth token、IMAP 密码或 Baileys auth state。

### InboundEvent

```text
id
channel_account_id
provider
external_event_id
external_message_id
dedupe_key
sender
recipients
subject
body_text
body_html
conversation_key
occurred_at
raw_payload_ref
processing_status
processing_error
received_at
processed_at
created_at
```

唯一约束：

```text
(channel_account_id, provider, dedupe_key)
```

推荐去重键：

- WhatsApp：`external_message_id`；
- Gmail：Gmail `message_id`；
- Outlook：`mailbox + uidvalidity + uid`；
- Teams：Provider event ID。

### DeliveryAttempt

用于记录人工确认后的外部发送：

```text
id
channel_account_id
event_id
idempotency_key
provider_message_id
status
error_code
error_message
attempt_count
sent_at
created_at
```

发送流程必须是：

```text
生成草稿 -> 人工查看 -> 用户确认 -> Provider.send() -> 记录结果
```

不得由 AI、Webhook 或入站邮件自动触发外部发送。

## 4. Provider 接口

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    inbound: bool
    outbound: bool
    realtime: bool
    webhook: bool
    polling: bool
    attachments: bool
    requires_public_endpoint: bool


class ChannelProvider(Protocol):
    name: str

    def capabilities(self) -> ProviderCapabilities:
        ...

    def authorize_start(self, account, request):
        ...

    def authorize_callback(self, request):
        ...

    def check_connection(self, account):
        ...

    def receive(self, account):
        ...

    def send(self, account, message):
        ...

    def revoke(self, account):
        ...
```

## 5. 渠道接入方案

### 5.1 WhatsApp：项目自有 WhatsApp Web + Baileys adapter

定位：

```text
chat_channel
provider = whatsapp_web_baileys
```

本项目不走 OAuth，也不采用 Meta WhatsApp Cloud API。项目自有独立 Node/Baileys adapter 负责连接生命周期：

```text
enterprise-agent 前端
    -> backend 创建绑定会话
        -> WhatsApp Baileys adapter 生成短时 QR
            -> 账号所有者手机扫码关联设备
                -> adapter 加密保存 auth state
                    -> 连接/重连/消息事件
                        -> enterprise-agent 统一入站处理
```

QR 只短时提供给当前有权账号所有者，不写入日志、localStorage、Git 或长期 API 响应。adapter 与 backend 使用内部认证和 `external_account_id` 账号映射。

当前真实接入前必须确认：

- Baileys/Node adapter 版本和独立部署方式；
- QR 会话生命周期、auth state 加密和持久化路径；
- adapter status/QR/disconnect/inbound 接口合同；
- 内部服务认证、账号作用域和重放防护；
- WhatsApp Web/Baileys 条款、地区和测试号码适用性；
- 真实入站消息如何映射到 `ChannelAccount`、`Message` 和 `Inquiry`。

### 5.2 Gmail：项目 Google OAuth + Gmail API + Pub/Sub

定位：

```text
event_hook
provider = gmail_api_pubsub
```

项目直接负责 OAuth 和 Gmail API：

```text
enterprise-agent Google OAuth
    -> 服务端安全保存授权引用/凭据
        -> Gmail Watch
            -> Google Pub/Sub
                -> enterprise-agent Pub/Sub webhook
                    -> Gmail History API
                        -> Gmail Message API
                            -> Message/Inquiries
```

Pub/Sub 通知通常只是变化信号，不是完整邮件正文；backend 通过 `historyId` 拉取详情，处理 MIME、附件 metadata、游标、重复通知和恢复。

当前真实接入前必须确认：

- Google Cloud OAuth Client、Gmail API 和 Pub/Sub 已启用；
- redirect URI、scope、state/PKCE/nonce 和 refresh 生命周期；
- Watch 创建、续订、过期和 reconciliation；
- Pub/Sub JWT/push token、topic/subscription 和重放校验；
- Gmail account/message/history 标识；
- 事件如何映射到 `ChannelAccount`、`Message`、附件 metadata 和幂等键。

OAuth token、client secret 和 refresh token 只在 backend 安全边界中处理，不进入前端、日志或普通 API 响应。

### 5.3 Outlook：外部 Outlook MCP Server + Microsoft Graph/Entra OAuth

定位：

```text
mail_listener
provider = outlook_mcp_graph
```

当前仓库不内置 Outlook 邮箱 watcher。目标链路为：

```text
enterprise-agent
    <-> Outlook MCP Server
            -> Microsoft Graph
                -> Entra OAuth
                    -> Outlook mailbox
```

个人邮箱场景通常使用 Entra OAuth 委派权限；后台服务可使用 Entra 应用权限的 client secret、证书或托管身份。具体采用哪种身份模式必须按租户和部署环境确认，不默认使用 Basic Auth，也不把现有 Microsoft Teams 插件视为 Outlook 邮箱接入。

当前真实接入前必须确认：

- Outlook MCP Server 的实现、版本、部署地址和内部认证；
- Microsoft Graph 权限和 Entra 管理员同意；
- 个人委派授权或后台应用身份模式；
- MCP 工具的邮件读取、附件和游标/分页合同；
- 失败、限流、重试和账号撤销状态；
- MCP 返回如何映射到 `ChannelAccount`、`Message`、`Inquiry` 和幂等键。

在 Outlook MCP Server 和 Graph 授权完成前，本项目只保留 provider-neutral seam，不标记 Outlook 真实连接或真实入站通过。

### 5.4 Microsoft Teams

定位：

```text
chat_channel
```

Teams 和 Outlook 邮箱必须分开建模。后续可根据场景选择 Teams Bot、Microsoft Graph subscription 或 Bot Framework。

在消息范围、附件、发送能力和租户管理员授权明确前，仅提供 `planned` 状态，不标记为已接通。

## 6. 与 OwnerBlog 业务连接

当前文章审核通知主要在：

```text
backend/articles/services.py
```

建议逐步统一为领域事件分发：

```text
文章审核事务
    -> 数据库提交成功
        -> 写入 IntegrationEvent
            -> 后台分发
                -> Notification
                -> 可选外部渠道通知
```

不要在 `transaction.atomic()` 内直接请求外部服务，应通过 `transaction.on_commit()` 触发事件记录或任务调度，避免数据库回滚后外部消息已经发送。

外部事件进入 OwnerBlog 后，由路由服务决定是否创建站内通知、文章草稿、知识库导入任务或人工处理任务。Provider 不得直接绕过审核服务修改文章状态。

## 7. 推荐 API

```http
GET /api/integrations
POST /api/integrations/{provider}/check
POST /api/integrations/{provider}/disconnect
POST /api/integrations/gmail/hook/{account_id}
GET  /api/integrations/whatsapp/accounts/{id}/status
POST /api/integrations/whatsapp/accounts/{id}/disconnect
POST /api/integrations/outlook/query
POST /api/integrations/{provider}/drafts
POST /api/integrations/{provider}/drafts/{id}/send
```

Provider-specific authorization boundaries:

- WhatsApp account owners use the project-owned Baileys adapter; QR/auth state never enters ordinary business API responses;
- Gmail authorization, Watch renewal and Gmail API access are owned by this FastAPI backend;
- Outlook authorization is owned by the Outlook MCP Server and Microsoft Graph/Entra.

The adapter and MCP contracts must be confirmed before implementing production routes.

`GET /api/integrations` 只返回渠道类型、账号状态和能力，不返回密钥。

外部发送必须验证：

- 当前用户对账号有权限；
- 消息已人工确认；
- Provider 支持 outbound；
- 幂等键有效；
- 已创建 `DeliveryAttempt`。

## 8. 安全要求

### 凭证安全

禁止将 OAuth token、Entra secret/certificate material、Baileys auth state、WhatsApp QR、session key、Pub/Sub secret、完整邮件正文或敏感附件放入前端、Git、日志或 API 响应。Google OAuth 凭据只在 backend 安全边界中处理；WhatsApp adapter 自行加密保存 auth state；Outlook MCP/Entra 凭据由其外部授权环境管理。

### 权限

每个 `ChannelAccount` 必须关联 OwnerBlog 用户。连接、查看、重连、断开和发送操作都要在后端检查账号所有权，不能依赖前端隐藏按钮。

### 外部授权、Hook 和 MCP

Gmail 的 Google OAuth、Watch 续订、Pub/Sub 接收和 History/Message API 由本项目负责；必须校验 push JWT/token、topic/subscription（若可见）和重放风险。Pub/Sub 到达只是变化信号，不等于完整邮件正文或真实账号验收。

Outlook 的 OAuth 由 Outlook MCP Server 使用 Microsoft Graph/Entra 负责。本项目必须认证到 MCP 服务、按 `ChannelAccount` 做权限和账号映射，并把 MCP 返回当作不可信外部数据处理；不得把 Teams 插件权限外推为 Outlook 邮箱权限。

WhatsApp 不走 OAuth；项目自有 Baileys adapter 负责关联设备、QR、会话和重连。adapter 与 backend 之间必须有服务认证、账号作用域和重放防护；QR 和 auth state 不得进入本项目普通 API 或日志。

### 不可信输入

外部邮件和聊天消息是业务数据，不是系统指令。后续接入 AI 时应限制正文、附件和上下文长度，执行提示词注入防护，不允许外部内容改变系统规则或直接触发外部发送。

## 9. 配置管理

当前项目使用 FastAPI/SQLAlchemy/Compose；不要照搬原始 OwnerBlog Django 的 `backend/config/settings.py` 路径。配置读取应集中在当前项目的后端配置边界，业务函数不应散落 `os.getenv()`。

外部组件配置由各自运行环境负责，当前项目只保存非秘密的连接/状态边界：

```env
# WhatsApp: project-owned Baileys adapter
WHATSAPP_ENABLED=false
WHATSAPP_ADAPTER_URL=
WHATSAPP_ADAPTER_TOKEN=
WHATSAPP_AUTH_STATE_KEY=

# Gmail: project-owned Google OAuth/API/Pub/Sub
GMAIL_ENABLED=false
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REDIRECT_URI=
GMAIL_PUBSUB_PUSH_TOKEN=
GMAIL_PUBSUB_TOPIC=
GMAIL_PUBSUB_SUBSCRIPTION=

# Outlook: external MCP owns Graph/Entra authorization
OUTLOOK_ENABLED=false
OUTLOOK_MCP_URL=
OUTLOOK_MCP_SERVER_NAME=outlook
OUTLOOK_MCP_TIMEOUT_SECONDS=20
```

以上是非秘密占位符；不得提交真实 URL 中的访问密钥、OAuth token、Entra secret、证书材料、Baileys auth state 或客户数据。

## 10. 实施顺序

### Phase 0：外部条件确认

确认：

- WhatsApp Baileys/Node adapter 版本、独立部署、QR/关联设备流程、auth state 安全和 adapter API 合同；
- Gmail Google Cloud OAuth Client、Gmail API、Pub/Sub、redirect URI、Watch 续订、History/Message API 和 webhook 合同；
- Outlook MCP Server 的实现/部署、Microsoft Graph 权限、Entra 委派或应用身份、工具返回和账号作用域；
- 入站消息进入当前 `enterprise-agent` 后的 `ChannelAccount`、`Message`、`Inquiry` 关联和业务用途。

### Phase 1：通用基础层

实现：

```text
integrations App
ChannelAccount
Credential
InboundEvent
IntegrationEvent
DeliveryAttempt
ProviderCapabilities
幂等约束
账号权限校验
状态查询 API
```

### Phase 2：Gmail 入站

实现项目 Google OAuth、Gmail Watch/Pub/Sub、History/Message API、账号映射、事件去重、邮件详情/附件边界和失败状态；OAuth 凭据只在 backend 安全边界中处理。

### Phase 3：Outlook 入站

对接外部 Outlook MCP Server：确认 Graph/Entra 授权、MCP 工具合同、邮箱分页/游标、MIME/附件映射、账号权限、限流和重试。不要将当前 Teams 插件或旧 IMAP 设计写成 Outlook 邮箱已接入。

### Phase 4：WhatsApp

实现项目自有 WhatsApp Baileys adapter：账号所有者在项目连接入口完成短时 QR 关联设备扫码；adapter 安全保存 auth state，backend 实现经过认证的状态/事件边界、账号作用域、标准化入站和幂等处理。不得将 auth state 暴露给前端或普通业务 API。

### Phase 5：Teams

待业务场景、Bot/Graph 方案和租户权限明确后实现。

## 11. 验收清单

### 基础层

- [ ] `integrations` App 已注册并有 migration；
- [ ] `ChannelAccount` 有用户所有权；
- [ ] 凭证没有明文落库；
- [ ] 入站事件具有唯一幂等键；
- [ ] 重复事件不会重复创建业务结果；
- [ ] 外部发送有人工确认和 `DeliveryAttempt`；
- [ ] Provider 不直接修改文章审核状态。

### Gmail（项目 Google OAuth/API/Pub/Sub）

- [ ] Google OAuth Client、Gmail API 和 Pub/Sub 已配置；
- [ ] 项目 OAuth state/redirect URI/scope 和服务端凭据边界已验证；
- [ ] Gmail Watch 创建、自动续订和过期恢复已验证；
- [ ] Pub/Sub webhook 来源认证、账号映射和重放防护已验证；
- [ ] 事件详情/History 或外部工具返回合同已确认；
- [ ] 重复通知不会重复处理；
- [ ] reconciliation/漏事件恢复边界已验证；
- [ ] 邮件正文和附件有大小/敏感数据边界。

### Outlook（外部 MCP + Graph/Entra）

- [ ] Outlook MCP Server 已部署并有内部认证；
- [ ] Microsoft Graph 权限和 Entra 委派/应用身份已确认；
- [ ] MCP 邮件读取、分页/游标和附件合同已确认；
- [ ] 重启或重复查询不会重复创建业务结果；
- [ ] `ChannelAccount` 账号作用域和权限映射已验证；
- [ ] 限流、连接失败和重试可观察。

### WhatsApp（项目自有 Baileys adapter）

- [ ] 独立 Node/Baileys adapter 版本和部署已确认；
- [ ] 账号所有者通过项目入口完成短时 QR 关联设备扫码；
- [ ] adapter auth state 加密保存，未进入前端/普通 API；
- [ ] adapter/backend 内部服务已认证并按账号隔离；
- [ ] 断线和重连状态可观察；
- [ ] 入站标准化和幂等已通过真实账号验收；
- [ ] 人工确认后的真实出站另行最终验收。

## 12. 最终结论

四种服务不应强行实现成同一种 Chat Channel：

```text
Project WhatsApp Baileys adapter       -> chat_channel
Project Gmail OAuth/API + Pub/Sub       -> event_hook
Outlook MCP + Microsoft Graph/Entra     -> mail_listener
Microsoft Teams 插件                  -> Teams，不等同 Outlook 邮箱
```

推荐先实现：

```text
当前 enterprise-agent 基础层
    -> 统一事件模型
    -> ChannelAccount 账号边界
    -> Baileys adapter / Gmail webhook / MCP 认证边界
    -> 幂等入站
    -> Gmail Pub/Sub/History API 入站
```

随后实现项目自有 WhatsApp adapter，再对接 Outlook MCP。Gmail OAuth/API 由本项目负责；各渠道只在账号授权、来源认证、账号映射和幂等入站全部验证后标记为真实接通。

在真实账号、Webhook、OAuth、入站、发送和失败重试全部完成验收前，只能描述为“具备接入基础”，不能描述为“外部渠道已接通”。

> 安全提醒：如果 OwnerBlog 的 `backend/.env` 中模型凭证是真实有效的，应立即轮换，并确认该文件未被 Git 跟踪。不要将真实凭证复制到本文档、前端代码或 `.env.example`。
