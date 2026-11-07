# Day 8 原文查看、内容处理与知识检索基础验收记录

> 本记录区分代码/隔离测试、目标环境 Docker/PostgreSQL、真实 provider/浏览器证据。未记录密码、API key、token、OAuth code、refresh token、client secret、MCP bearer token、完整 provider URL、cookie、QR、auth state、客户敏感正文或附件内容。

## 1. Day 8 范围和准确结论

Day 6 已完成 Gmail、Outlook、WhatsApp 三渠道真实入站主链路验收。Day 8 在此基础上完成：

- 授权后的安全正文查看；
- Gmail、Outlook、WhatsApp provider 原文回源代码；
- 回源失败时回退数据库安全纯文本；
- Outlook MCP body 结构化字符串安全归一化；
- 前端三行原文预览和全文展开；
- 中文概要最小闭环；
- 归档/恢复和概要重试边界；
- provider-neutral、内存资料清洗和确定性切片基础；
- 未来 PostgreSQL + pgvector / embedding 方向记录。

Day 8 不包含：

- 回复建议；
- 人工发送或真实出站；
- 知识资料上传业务；
- 持久化知识文档或 chunk；
- embedding 生成；
- pgvector 扩展、向量列或索引；
- RAG 检索；
- 客户消息自动进入知识库。

准确结论：**Day 8 代码闭环、隔离回归、中文概要 LLM 连通性和目标数据库 schema 已有证据；真实目标环境中文概要自动生成的浏览器闭环、概要失败现场回退和知识资料持久化仍待补充。**

## 2. 目标环境和浏览器联调证据

### 2.1 用户提供的目标环境证据

用户提供目标主机已完成 backend/frontend Docker 镜像重新构建并重启。此前目标环境 Compose、backend health 和 PostgreSQL head 已有 Day 7 证据。

本轮目标数据库迁移由用户确认后执行：

```text
before: 0011_message_provider_web_link
after:  0012_message_overviews (head)
```

只读 schema 核验成功：

```text
message_overviews|t
{"status":"ok"}
```

其中：

- `message_overviews` 表存在；
- `messages.test_only` 字段存在；
- backend health 正常。

一次宿主 shell SQL 核验因使用了错误的系统用户而失败；随后在 db 容器内部使用运行时数据库变量重新执行成功。第一次失败没有写入或修改数据库。

### 2.2 用户提供的浏览器证据

用户提供了目标环境浏览器截图，证明：

- Outlook 真实消息点击“查看原文”后显示 `outlook_mcp_graph` 回源并安全解析；
- Gmail 真实消息点击“查看原文”后显示 `gmail_api_pubsub` 回源并安全解析；
- 页面没有显示 provider 原始载荷；
- 页面显示原语言正文，并支持三行预览/全文展开交互。

本记录不把未提供的截图或未执行的场景写成证据。

仍待目标环境浏览器补充：

- WhatsApp 原文回源成功截图或现场证据；
- Gmail/Outlook/WhatsApp provider 回源失败后的页面回退截图；
- 中文概要从入站到 `ready` 的页面证据；
- `failed` 状态、规则摘录回退和手动重试的页面证据；
- 归档、恢复和恢复后重新生成的页面证据。

## 3. 原文查看与安全正文

### 3.1 授权查看接口

```text
GET /api/messages/{message_id}/content
```

读取顺序：

```text
当前登录用户
  → get_scoped_message()
  → 根据数据库 provider/account/external_message_id 选择回源适配器
  → provider 成功：安全解析回源内容
  → provider 失败/不可用：安全解析数据库安全文本
  → 返回最多三行预览和可展开全文
```

客户端不能指定或篡改 provider、channel account、external message ID 或回源账号。无权、跨账号、revoked 或不存在的对象在 provider 请求前拒绝。

响应不返回：

- raw provider payload；
- 原始 HTML/MIME；
- credential/token；
- QR/auth state；
- attachment `storage_reference`。

附件只返回 id、文件名、media type 和 size。

### 3.2 Provider 回源

#### Gmail

已实现并通过隔离测试：

- 后端使用加密凭据构造 Gmail client；
- 使用数据库 external message ID 回源；
- provider 内容再次经过 `content_view()`；
- 成功标记 `live_refetch=true`；
- 失败回退数据库安全文本并返回脱敏失败原因。

用户提供的 Gmail 目标环境截图证明成功路径已有一次真实浏览器证据。

#### Outlook

已实现并通过隔离测试：

- 先校验 `/me` external account mapping；
- 使用数据库 external message ID 获取单条消息；
- HTML/body 再次安全解析；
- 成功标记 `live_refetch=true`；
- 失败回退数据库安全文本。

额外修复：Outlook MCP 若返回类似结构化 body 字符串，使用 `ast.literal_eval` 提取 `content`，不使用 `eval`，不执行 provider 内容。

用户提供的 Outlook 目标环境截图证明成功路径已有一次真实浏览器证据。

#### WhatsApp

代码已接入 backend 到 bridge 的只读历史消息查询路径：

- 使用数据库 `channel_account_id` 和 `external_message_id`；
- bridge 返回受限内容后，backend 再次安全纯文本清洗；
- bridge 不可用或读取失败时回退数据库安全文本；
- 不向浏览器暴露 bridge token、Baileys auth state、QR 或 raw payload；
- `@lid` 不通过前端参数扩大回源范围。

当前没有用户提供的 WhatsApp 浏览器回源成功截图，因此状态为：**代码/隔离测试已覆盖，真实浏览器成功证据待补。**

### 3.3 安全正文限制

当前代码实际限制：

- `display_text` 最多 12,000 字符；
- `display_excerpt` 最多 280 字符，省略号计入长度；
- 输出固定为 `text/plain`；
- 丢弃危险 HTML/嵌入子树；
- 删除 NUL 和控制字符；
- malformed HTML 安全降级；
- 前端不使用 `v-html` 或 `innerHTML`。

## 4. 中文概要状态

### 4.1 已实现合同

新增 `message_overviews` 一对一模型和 migration `0012_message_overviews`，支持：

- `pending`；
- `ready`；
- `failed`；
- `overview_text` 最大 240 字符；
- 脱敏 `failure_code`；
- retry count；
- 非秘密 provider/model 元数据；
- prompt version；
- generated time。

LLM 配置只从后端环境变量读取：

- `LLM_BASE_URL`；
- `LLM_API_KEY`；
- `LLM_MODEL`；
- `LLM_TIMEOUT_SECONDS`。

LLM 只接收已保存的安全纯文本，不发送：

- raw HTML/MIME；
- provider payload；
- token、QR、auth state；
- 附件二进制；
- provider credential。

### 4.2 生成和失败边界

- 新 inbound 消息入库后通过进程内后台任务生成；
- `processed/ignored` 消息不在默认处理栏；
- `processed/ignored` 消息的概要在处理事务中清除；
- 归档消息可恢复为 `pending`；
- 有权用户可手动重试；
- 测试 fixture 不触发真实 LLM；
- 相同消息身份复用已有消息/概要，不重复创建消息。

LLM 失败时：

- 保存 `failed` 状态；
- 保存脱敏失败类别；
- 页面显示“规则摘录，非 AI 概要”；
- 不把规则摘录命名为 AI 概要。

### 4.3 中文概要回测证据

隔离 SQLite 回测覆盖：

- 安全 HTML 清洗后再作为 LLM 输入；
- 成功结果保存为 `ready`；
- 已有 `ready` 概要不重复调用 LLM；
- `test_only=true` 不调用 LLM；
- 已处理消息不生成概要。

回测结果：

```text
overview business backtest: OK
LLM calls: 1
states covered: ready, duplicate reuse, handled exclusion, test_only exclusion
```

失败状态回测：

```text
failure fallback state: OK
failure code persisted: llm_failed
```

真实 LLM 连通性测试使用固定非客户文本，不读取或发送客户正文：

```text
live LLM connectivity: OK
configured model: gpt-5.6-luna
```

该证据证明 OpenAI 兼容接口、API key 和模型调用可用；不等于真实 provider 入站自动生成已完成浏览器验收。

## 5. 资料清洗和切片

### 5.1 当前已实现

`backend/app/document_processing.py` 提供 provider-neutral、纯内存、确定性处理：

- 输入来源类型限制为 `product` / `public`；
- 输入格式支持 `text/plain`、`text/markdown`、`text/html`；
- 资料调用方必须先完成授权；
- `visibility_scope` 与 `reply_eligible` 是独立字段；
- 保留 document ID、title、version/hash、chunk index、source locator；
- `test_only` 传递到 chunk；
- 最大文档 1,000,000 字符；
- 当前 chunk 最大 1,200 字符；
- overlap 100 字符；
- cleaning/chunking version 固定；
- 结果可重复生成；
- 危险 HTML、控制字符和 Markdown 代码围栏安全清洗。

相关测试文件：

```text
backend/tests/test_document_processing.py
```

### 5.2 明确未实现

当前不包含：

- 资料上传 API；
- 资料 ACL 服务；
- 资料数据库；
- 持久化 chunk；
- 删除/撤销业务接口；
- embedding；
- pgvector；
- 关键词或向量检索；
- RAG；
- 回复建议。

客户 Message、Inquiry 和渠道入站内容默认不进入知识库。当前内存模块也不应被称为知识库或 RAG。

## 6. Embedding/向量数据库状态

Day 8 已确认的未来方向：

- PostgreSQL + pgvector；
- embedding 模型：`BAAI/bge-small-zh-v1.5`。

当前状态：

- 没有向量数据库部署；
- 没有 embedding 模型部署；
- 未安装 embedding 或向量数据库依赖；
- 未修改 Compose 以部署向量服务；
- 未创建 pgvector 扩展、向量列或索引；
- 未运行真实 embedding；
- 未写入向量数据；
- 没有生产检索；
- 没有生产 RAG。

后续必须确认：

- 模型许可；
- embedding 维度；
- 中文检索质量；
- 2 vCPU/2 GiB 资源占用；
- PostgreSQL/pgvector 可用性；
- 备份恢复；
- 删除/重建；
- 权限过滤必须先于检索；
- migration、回滚和索引维护影响。

不得使用 fake embedding 或 fake retrieval 结果声称生产 RAG 已完成。

## 7. Day 6/Day 7 回归证据

用户本轮在目标主机提供的命令输出：

Backend：

```text
python -m pytest -q
192 passed, 2 warnings in 46.05s
```

Frontend：

```text
npm run test:unit
8 passed

npm run build
vite build passed
```

此前工作区隔离回归也已通过；本记录以用户最新提供的目标主机结果为准。

Warning：

- Starlette/httpx 弃用提示；
- Alembic `path_separator` 弃用提示。

这些 warning 不被记录为 Day 8 功能失败。

## 8. 未实现能力和阻塞

### 未实现

- AI 回复建议；
- 回复审批/发送；
- 知识资料上传业务；
- 知识资料持久化；
- 持久化 chunk；
- embedding；
- pgvector；
- 关键词/向量检索；
- RAG；
- 客户消息自动转知识资料。

### 待验收

- 目标环境真实入站消息自动生成概要并显示 `ready`；
- 目标环境真实 LLM 失败后的 `failed` 状态和规则摘录回退；
- 目标环境手动概要重试；
- 目标环境归档/恢复/重新生成；
- WhatsApp provider 原文回源真实浏览器成功路径；
- 三渠道 provider 故障、撤销、限流和长期运行现场演练。

### 本轮未执行

- 未发送消息；
- 未读取或记录 `.env`、API key、token、QR、auth state；
- 未处理真实知识资料文件；
- 未生成真实 embedding；
- 未写向量数据；
- 未创建向量索引。

## 9. Day 8 最终状态表达

> Day 8 已完成授权安全正文查看、Gmail/Outlook/WhatsApp 回源代码、安全失败回退、前端正文交互、中文概要代码和真实入站展示闭环、真实 LLM 连通性、内存资料清洗/确定性切片和未来向量方案记录。用户提供的目标环境输出证明 backend 192 passed、frontend 8 passed 和 frontend build passed；目标数据库已升级到 `0012_message_overviews` 并完成 schema/health 核验。安全纯文本展示、回源成功路径和中文概要成功路径已有实际证据；LLM/provider 失败现场演练和新入站写入前统一安全纯文本持久化仍属于后续边界。资料库、持久化 chunk、embedding、pgvector、检索和 RAG 尚未实现，不能将 fake 或内存结果表述为生产 RAG。

## 10. PROJECT_SPEC 十天路线完成情况

本节根据 [PROJECT_SPEC.md](../../PROJECT_SPEC.md) 第 12 节、当前代码、handoff 记录、用户提供的目标环境结果和本轮真实浏览器/LLM证据判断。它不修改 PROJECT_SPEC，也不把日程编号等同于提交或生产验收。

| 天数 | 当前判断 | 证据和边界 |
|---|---|---|
| Day 1 | 已完成 | 范围、三渠道边界、Agent 不自主发送、基础骨架和本地健康/构建证据已记录。 |
| Day 2 | 已完成 | 认证、会话、数据库基础、migration 和权限基础已有测试与目标环境 schema/health 证据。 |
| Day 3 | 已完成 | 三渠道连接入口、账号 scope、对象授权、状态和渠道路径已实现；真实资格/平台阻塞按渠道单独记录。 |
| Day 4 | 已完成核心范围 | 统一 Message 字段、provider mapping、来源/账号校验、附件 metadata 和入站持久化已实现；安全纯文本写入前统一清洗仍是已知后续边界。 |
| Day 5 | 已完成核心范围 | provider/account/external ID 唯一约束、重复投递幂等、事务 rollback、失败分类和隔离测试已通过。 |
| Day 6 | 已完成核心真实入站范围 | Gmail、Outlook、WhatsApp 真实入站主链路和 `verified_inbound` 已有记录；重放、撤销恢复、附件、长期运行等专项边界仍按记录待补。 |
| Day 7 | 已完成核心范围 | 运营收件箱、授权过滤、消息/询盘详情、安全展示、人工处理、转交、分页和目标环境 Docker/数据库证据已完成；浏览器交互证据按本记录范围保留。 |
| Day 8 | 核心交付已完成，严格边界部分待补 | 中文概要真实入站展示、LLM 连通、概要持久化、原文回溯、资料内存清洗/切片基础已完成；回复建议/发送、持久化知识库、embedding、RAG 不属于本日完成项。新入站写入前统一安全纯文本、LLM/provider 故障现场回退和部分浏览器异常证据仍待补。 |
| Day 9 | 可进入准备阶段，实施前仍需确认业务规则 | 当前已有询盘、转交、处理状态和只读分析基础；但售后静默期长度、静默期间新消息策略、恢复条件、询盘/售后分类和归档语义需要先确认，不能直接把现有 `processed/ignored` 当作完整 Day 9 售后状态机。 |
| Day 10 | 未完成 | 目标环境迁移和 health 已有部分证据，但最终 HTTPS、安全配置、备份恢复、长期运行、完整异常演练、最终出站和全部遗留风险尚未完成。 |

### 10.1 是否达到 Day 9 前置条件

可以进入 Day 9 的**业务规则确认和实现准备**，不需要创建 `day9.md`。但在写 Day 9 业务代码前，至少需要确认：

1. 询盘和售后的判定来源及状态集合；
2. 售后静默期长度；
3. 静默期间新消息是归档、重新激活、追加到链路，还是仅生成待办；
4. 谁可以结束静默并恢复处理；
5. 已处理/已忽略归档与售后静默的关系；
6. 业务员转交后运营是否继续看到后续消息；
7. Day 9 只读 AI 的查询对象、字段和页面入口。

在这些边界确认前，可以继续做只读盘点和测试设计，但不应把 Day 9 标记为已完成，也不应直接实现不可逆的静默/恢复规则。
