# Day 3 数据库基础、渠道连接与消息入站验证记录

> 本记录按代码、隔离测试、目标 PostgreSQL 和真实 provider 分层。用户负责执行目标数据库和真实账号操作；本文件不记录凭据、token、QR、auth state 或客户敏感内容。

## 1. 当前代码增量

当前工作区已实现：

- 首期对象授权：运营按本人授权渠道账号读取，sales 只读本人转交询盘，内部分析只读；
- provider-neutral 渠道目录和连接状态；
- fake/test-only 连接中心状态流转和凭据边界；
- `ChannelAccount`、`ChannelGrant`、`Message`、`MessageAttachment` 等 ORM；
- `0001`–`0005` migration 文件；
- provider mapping 和统一消息入库；
- 数据库唯一键范围为渠道账号、provider、外部消息 ID；
- 附件 metadata 保存和脱敏返回；
- Gmail history 入站 seam；
- provider 暂时失败、限流、授权失效、来源失败、消息合同错误和数据库错误分类；
- 重复消息、批次 rollback、cursor 失败边界和 revoked 账号回归。

## 2. 用户提供的本地测试证据

用户后续执行的后端全量回归结果：

```text
105 passed, 2 warnings in 47.82s
```

该结果覆盖当前工作区后端测试，包括认证、授权、渠道、消息入库、Gmail seam、Day 4 业务动作和 Day 5 失败/跨功能回归。warning 为 Starlette/httpx 弃用提示及 Alembic `path_separator` 弃用提示。

这证明本地隔离测试范围内的代码行为，不等同于目标 PostgreSQL 并发或真实 provider 验收。

## 3. 用户提供的目标环境 revision 证据

用户在目标环境执行：

```text
docker compose run --rm backend python -m alembic current
```

结果：

```text
0005_channel_external_account (head)
```

用户执行 `alembic heads` 结果同为：

```text
0005_channel_external_account (head)
```

用户执行 `alembic history` 和容器内 migration 文件检查，确认当前运行 backend 镜像识别并包含 `0001`–`0005`，未包含 `0006`、`0007`。

因此当前可确认：

- 目标环境当前 revision/head 为 `0005_channel_external_account`；
- 当前运行容器内没有 `0006`/`0007`；
- 不能把旧文档提到的 `0006`/`0007` 写成当前必须应用的 migration；
- 尚未有本轮字段、约束、索引和跨连接并发专项查询证据。

## 4. 真实 provider 状态

以下仍无真实验收证据：

- Gmail Google OAuth、Pub/Sub、History/Message API、真实附件和 cursor 恢复；
- Outlook MCP/Graph/Entra 委派读取和附件；
- WhatsApp Web + Baileys adapter、QR 绑定、auth state、重连和媒体入站；
- 真实 provider 限流、授权撤销和网络恢复；
- 真实出站发送。

fake/provider-neutral seam 不代表真实渠道已连接或真实入站成功。

## 5. Day 3 状态

**Day 3 代码增量和本地隔离回归已完成；目标 PostgreSQL 的 schema/并发专项验收和真实 provider 按账号验收仍待用户完成。**

当前不需要、也不应凭旧文档创建或应用不存在的 `0006`/`0007` migration。若未来确认 ORM 与目标 schema 不一致，应另行审阅并授权最小 migration。
