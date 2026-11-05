# Day 7 首页运营收件箱验收记录

> 本记录区分代码、隔离测试、构建、Docker/目标环境和真实 provider 证据。未读取 `.env`、token、QR、auth state；本轮未重复执行真实 provider 验收，未发送消息、未运行 migration、未修改目标数据库。Gmail、Outlook、WhatsApp 的真实入站主链路和 `verified_inbound` 状态沿用 Day 6 记录及用户提供的目标环境证据。

## 已实现并验证

- 首页运营收件箱：列表、筛选、稳定排序、分页、详情、询盘时间线。
- 后端授权先于渠道/账号/ingestion/handling/业务状态过滤、排序和分页；列表与详情使用同一对象 scope。
- staff、sales、admin、跨账号、revoked、blocked、ID 猜测边界；sales 对没有正式 Message-Inquiry 关联的消息安全返回空集。
- `Message.status` 以 `ingestion_status` 返回，`Message.handling_status` 单独返回；询盘 `status` 与 `handling_status` 单独返回。
- 人工 `processed`/`ignored`：授权先行、同状态幂等、终态反向切换 409、`for_update`、事件事务和 commit rollback。
- transfer：状态、`InternalNotification`、`InquiryEvent` 同事务，重复转交不重复事件/通知。
- internal-analysis、internal-ai/query、notification detail 统一 revoked 授权边界。
- 正文运行时安全纯文本：HTML/危险元素/危险 URL/控制字符/异常 MIME 安全降级；详情 20,000 字符、摘要 240 字符；前端无 `v-html`/`innerHTML`。
- 附件只返回 `id`、文件名、媒体类型、大小，不返回 `storage_reference`、credential 或 token。
- 首页只保留收件箱和人工处理；“我的”只保留本人渠道连接、授权、重新授权/关联、断开和状态；OAuth/QR/fake fixture 不在首页。
- loading、空结果、401/403、错误重试、提交中、防重复点击、成功刷新和筛选后选中项恢复。

## 实际本地验收

后端：

```text
source /root/enterprise-agent/.venv/bin/activate
cd /root/enterprise-agent/backend
pytest -q
170 passed, 2 warnings in 42.89s
```

前端：

```text
source /root/enterprise-agent/.venv/bin/activate
cd /root/enterprise-agent/frontend
npm run test:unit
npm run build
9 passed
vite build passed
```

WhatsApp bridge：

```text
cd /root/enterprise-agent/whatsapp-bridge
npm test
TypeScript build passed
10 passed
```

`git diff --check` 已通过。warning 为既有 Starlette/httpx 和 Alembic `path_separator` 弃用提示。

## Docker 镜像构建（2026-11-05）

本轮使用当前工作区源码独立构建三份验收镜像，未启动容器：

```text
docker build -f backend/Dockerfile -t enterprise-agent-backend-day7-check backend
→ passed

docker build -f frontend/Dockerfile -t enterprise-agent-frontend-day7-check frontend
→ passed；构建日志提示 npm audit 有 1 个 moderate vulnerability，未自动升级依赖

docker build -f whatsapp-bridge/Dockerfile -t enterprise-agent-whatsapp-bridge-day7-check whatsapp-bridge
→ passed
```

这证明 Dockerfile 和当前源码可构建，不证明 Compose 服务已启动、健康检查通过、镜像已部署或目标环境已切换。

## 4.1 目标环境 Compose/PostgreSQL 核验（用户提供，2026-11-05）

用户在目标主机执行了当前工作区镜像构建和 Compose 启动；本轮未重复执行真实 provider 验收，未执行 migration、未发送消息。

镜像构建：

```text
backend: passed
frontend: passed
whatsapp-bridge: passed
```

Compose 运行状态：

```text
backend: Up，127.0.0.1:8000->8000/tcp
frontend: Up，127.0.0.1:8080->80/tcp
whatsapp-bridge: Up，8090/tcp
 db: Up 27 hours (healthy)
whatsapp-inbox-permissions: Exited（一次性权限初始化服务）
```

Compose 启动提示存在历史 orphan container：`enterprise-agent-api-1`。本轮没有使用 `--remove-orphans` 清理，避免未经确认删除运行资源；该 orphan 状态仍需环境管理员单独处理。

Backend 健康检查：

```text
GET http://127.0.0.1:8000/health
HTTP 200
{"status":"ok"}
```

PostgreSQL ready 检查：

```text
/var/run/postgresql:5432 - accepting connections
```

Alembic 只读核验：

```text
current: 0011_message_provider_web_link (head)
heads:  0011_message_provider_web_link (head)
```

目标 PostgreSQL 只读字段核验成功，确认存在：

- users；
- channel_accounts 的外部账号、credential reference/ciphertext 和 Gmail Watch 字段；
- inquiries 的人工 handling_status；
- inquiry_events；
- internal_notifications；
- messages 的 provider/status/handling_status、customer_contact/customer_nickname、provider_web_link；
- 未读取正文、credential ciphertext 或其他敏感数据。

第一次字段查询因 shell 引号错误返回 SQL syntax error；随后使用修正命令成功完成同一只读字段核验。第一次失败不作为环境失败证据。

这一结果证明：目标 Compose 服务已使用当前源码构建并启动，目标数据库当前 revision/head 与工作区 0011 head 一致，且 Day7 所需业务字段已存在。它不证明浏览器联调、真实 provider 补充验收或持久化正文清洗已完成。

## 未完成项与后续验收

- **Day 7 环境验收待补**：浏览器实际登录、首页 API 联调和页面交互尚未提供本轮证据；
- **Day 6 后续专项验收**：真实 provider 的 Gmail redelivery/Watch/history/OIDC/附件，Outlook/WhatsApp 撤销恢复、重放、附件和长期运行仍待补；这不否定三渠道真实入站主链路已完成的验收结论；
- **后续安全策略事项**：当前正文采用 API 运行时清洗，未新增持久化展示列，也未回填或覆盖历史 `raw_message/raw_content`。数据库持久化正文清洗不是本轮 Day 7 的硬性阻塞项，是否实施需另行确定数据保留策略；
- **最终业务验收**：未执行真实出站发送，留待后续出站/项目最终验收。

准确结论：Day7 首页代码闭环、授权、正文运行时安全展示、人工动作和页面职责分离已通过隔离回归；三份镜像构建、Compose 服务启动、backend health 和目标 PostgreSQL `0011/schema` 已由用户提供证据核验；三渠道真实入站主链路已按 Day 6 记录和用户提供的目标环境证据完成验收。当前浏览器实际联调仍是 Day 7 环境验收待补；真实 provider 补充项属于后续专项验收，数据库持久化正文清洗属于后续安全策略事项，不能表述为 Day7 生产整体验收全部通过。

`backups/`、`.env`、本地工具目录和测试 fixture 不属于本功能验收证据或提交内容。
