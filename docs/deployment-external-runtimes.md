# 外部渠道运行时与 Compose 部署边界

> 本文记录当前 `enterprise-agent` 容器与外部渠道运行时的部署边界。它不证明任何真实账号或 provider 已接通。

## 1. 当前 Compose 服务

```text
frontend  → Vue 构建产物 + Nginx
backend   → FastAPI + SQLAlchemy/Alembic + Gmail/统一 ingress 边界
 db       → PostgreSQL 16
```

backend 只通过 Compose 网络访问 `db`；frontend Nginx 代理 `/api/` 和 `/auth/` 到 backend。生产 migration 由管理员审阅后手动执行，不在容器启动命令中自动执行。

## 2. 当前三渠道运行时边界

| 渠道 | 方案 | 当前项目责任 |
|---|---|---|
| WhatsApp | 项目自有独立 WhatsApp Web + Baileys adapter | backend 负责账号授权、adapter 控制边界、QR 状态、账号映射、入站幂等；adapter 负责 Baileys 连接、加密 auth state、重连和 provider 事件 |
| Gmail | 项目直接 Google OAuth + Gmail API + Watch/Pub/Sub | backend 负责 OAuth、凭据保护、Watch/History/Message API、Pub/Sub 校验、入站幂等 |
| Outlook | 外部 Outlook MCP + Microsoft Graph/Entra 个人委派 OAuth | backend 负责 MCP 调用边界、用户授权范围和主动读取；MCP 负责 Graph/Entra 授权 |

## 3. Docker 拓扑

当前已经部署并验证的 Compose 服务是：

```text
frontend
backend
 db
```

WhatsApp adapter 是待实现的独立 Node 服务；实现完成后才加入 Compose，不能把一个未确认的空镜像或启动命令写入生产部署。Outlook MCP 作为外部服务，不在当前 Compose 中凭空添加镜像。Gmail 不需要外部 OpenClaw/gog 容器，由 backend/后续 worker 直接使用 Google API。

目标拓扑：

```text
frontend
backend ───── db
   │
   ├── whatsapp-adapter（实现后加入）
   └── Gmail Google API/Pub/Sub

Outlook MCP（外部服务）
```

## 4. Backend 配置边界

`.env.example` 只提供非秘密占位符：

```text
WHATSAPP_ADAPTER_URL
WHATSAPP_ADAPTER_TOKEN
WHATSAPP_AUTH_STATE_KEY
WHATSAPP_CONNECT_TIMEOUT_SECONDS
WHATSAPP_SEND_TIMEOUT_SECONDS

GMAIL_ENABLED
GMAIL_CLIENT_ID
GMAIL_CLIENT_SECRET
GMAIL_REDIRECT_URI
GMAIL_PUBSUB_PROJECT
GMAIL_PUBSUB_TOPIC
GMAIL_PUBSUB_SUBSCRIPTION
GMAIL_PUBSUB_PUSH_TOKEN
GMAIL_SCOPES
GMAIL_TIMEOUT_SECONDS
GMAIL_RECONCILE_INTERVAL_SECONDS

OUTLOOK_ENABLED
OUTLOOK_MCP_URL
OUTLOOK_MCP_SERVER_NAME
OUTLOOK_MCP_TOKEN
OUTLOOK_MCP_TIMEOUT_SECONDS
```

真实 OAuth token、refresh token、Google secret、WhatsApp auth state、QR、Entra secret/certificate 不提交仓库，不进入前端或普通业务 API。

## 5. 构建和更新顺序

从仓库根目录执行：

```bash
docker compose --env-file .env config --quiet
docker compose --env-file .env build backend frontend
docker compose --env-file .env up -d --force-recreate db backend frontend
```

以上命令不自动执行 migration。migration 必须先审阅，再由管理员手动执行并核验 revision。

## 6. 真实渠道边界

以下只证明项目内部边界，不证明真实渠道已接通：

- provider 目录返回正确方案；
- fake/provider-neutral 入站测试通过；
- adapter/MCP/Google API ingress 的隔离测试通过；
- Compose 构建成功；
- API 返回 200。

真实渠道通过必须分别有：

```text
外部运行时/Google API 已配置
→ 账号所有者完成授权或扫码
→ external_account_id 已映射
→ 连接状态可观察
→ 真实测试消息入站
→ 来源认证通过
→ Message/Inquiry 正确入库
→ 重复事件幂等
→ 附件和失败恢复通过
```
