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

> Day 8 handoff 记录了授权安全正文查看、三渠道回源代码、安全失败回退、前端正文交互、中文概要代码、真实 LLM 连通性及内存资料清洗/切片等结果；当时用户提供 backend 192 passed、frontend 8 passed/build passed 和目标库 0012 的证据，仅适用于该记录时点。后续源码增量见 §11.5，当前工作区测试/构建与 0014–0017 目标 schema 未在本轮验证。资料库、持久化 chunk、embedding、pgvector、检索和 RAG 尚未形成实现。

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

## 11. Day 8–Day 9 当前代码事实与交接清单

本节是 Day 9 起点的只读核对摘要。它区分代码结构、仓库测试源码、交接文档记载的目标环境证据和待确认业务规则；不把计划或测试源码本身表述为本轮执行结果。

### 11.1 当前代码事实

| 范围 | 当前事实 | 证据边界 |
|---|---|---|
| Inquiry | 有客户联系方式/身份状态、原始消息、来源账号、业务状态 `new/assigned`、人工处理状态 `pending/processed/ignored`、可空 `business_type`（`inquiry/after_sales`）、销售负责人、`last_activity_at`；关联附件、通知、事件及消息关联。 | `backend/app/models/business.py`；business_type 来自 `0014`，消息关系来自 `0013`。类型字段存在不代表分类政策完整或静默状态机完成。 |
| InquiryEvent | 保存询盘事件类型、操作者、变更前后状态、目标用户、可选关联 Message 和发生时间；源码事件类型包括创建、转交、处理、忽略、恢复、消息关联和人工关联。 | `backend/app/models/business.py`。没有独立静默期限字段；恢复事件不等同于已实现完整售后静默策略。 |
| Message | 有账号/provider/外部消息 ID、方向、接入状态、人工处理状态、发生时间、内容、客户/规范化身份、provider 链接、官网表单标记、`test_only`、归链状态和时间戳；关联附件、一对一 overview 及可选 InquiryMessage。 | `backend/app/models/business.py`；官网表单标记由 `0015` 加入，关联由 `0013` 加入。模型定义不代表附件正文存储已实现。 |
| MessageOverview | 与 Message 一对一；状态为 `pending/ready/failed`，保存概要文本、失败码、重试次数、provider/model/prompt 元数据、`test_only` 和生成/更新时间。 | `backend/app/models/overview.py`。概要状态不是询盘或售后状态。 |
| 人工处理与归档箱 | Message 和 Inquiry 的人工处理状态为 `pending/processed/ignored`。Message 的 `POST /api/messages/{id}/archive/restore` 仅把 `processed/ignored` 改回 `pending`。前端归档箱根据处理状态筛选。 | `backend/app/business_routes.py`、`frontend/src/App.vue`。没有独立 archive 字段/实体/生命周期；这不是售后静默/恢复状态机。 |
| 转交 | Inquiry 转交会更新负责人/业务状态，并写内部通知和 `inquiry_transferred` 事件；当前业务服务要求指定业务类型。 | `backend/app/business_service.py`、`backend/app/business_routes.py`。与消息关系/后续消息可见性分别按关联和授权规则处理，完整通知收件箱仍未实现。 |
| 只读分析 | `POST /api/internal-analysis` 的 `operation=read` 在授权范围内汇总 Inquiry 生命周期/处理状态、Message 归链/身份状态、候选人工判断、可见事件和渠道阻塞；非 read 操作返回指引而不执行写操作。 | `backend/app/business_routes.py`、`backend/app/authorization.py`、`frontend/src/api/inbox.ts`、`frontend/src/App.vue`。属于确定性只读汇总，不代表完整 BI/LLM 对话或售后静默状态机。 |
| Day 8 正文/Provider | 已实现授权安全正文查看及 Gmail、Outlook、WhatsApp 回源代码与安全回退。 | 本记录第 2–3 节：Gmail/Outlook 有用户提供的目标环境浏览器成功证据；WhatsApp 有代码/隔离测试证据，但没有目标浏览器成功证据。 |

### 11.2 模型 / API / 前端 / 迁移缺口矩阵

| 层 | 当前已具备 | Day 9 缺口 |
|---|---|---|
| 模型 | Inquiry（含可空 `business_type`/`last_activity_at`/身份字段）、InquiryEvent、InquiryMessage、Message（含 link/identity/website-form 字段）、MessageOverview、通知、OperationLog、人工处理状态。 | 售后静默专属状态/期限/新消息策略；独立归档实体；完整审计 lifecycle。 |
| API | Inquiry/Message 列表详情、人工处理、Inquiry 转交/处理/恢复、概要读/重试、消息候选归链与人工关联、内容回源、授权范围只读分析及操作记录读取。 | 正式类型判定政策/修订、售后静默期限及期间新消息策略、提醒/实际归档清理调度；Message restore 仍为处理状态恢复，不等同完整售后恢复状态机。 |
| 授权 | 账号授权范围、Inquiry 分配范围；关联候选/写入分别校验 inquiry、message 来源账号及关联消息 scope，详情按可见关联消息裁剪。 | 管理员完整全域权限矩阵、部门/经理 RBAC 与所有生产账号配置/浏览器行为仍待完整验证。 |
| 前端 | 收件箱/处理箱、客户链路/逐条关联消息、待判断候选人工关联、概要/原文、状态动作、转交、授权范围只读分析及操作记录面板。 | 完整询盘/售后分类政策交互、静默/提醒工作流、全角色浏览器联调；当前工作区前端测试/build 未在本轮执行。 |
| 迁移 | 当前工作区迁移链为 `0001`–`0017`：含 `0012_message_overviews`、`0013_inquiry_messages`、`0014_inquiry_business_type`、`0015_website_form_messages`、`0016_operation_logs`、`0017_message_feed_indexes`。 | 迁移源码存在不等于目标 PostgreSQL 已应用；0014–0017 的目标环境 revision/schema 本轮未核验。迁移测试源码也不替代在线数据库验证。 |
| 测试 | 当前有业务授权、Inquiry—Message links/routes、身份规范化/人工确认、内容安全、渠道回源、概要、迁移等测试源码。 | 测试源码存在不代表通过；当前工作区未运行回归。本记录第 7 节 Day 8 数字仅为用户当时提供的历史输出，不能覆盖后续代码。 |

### 11.3 Day 9 业务规则确认清单

开始实现 Day 9 状态/归链行为前，需确认并形成可测试的业务合同：

- [ ] **询盘/售后分类**：判定来源、判断依据、自动/人工边界、修改权限及纠错流程。
- [ ] **业务状态集合**：询盘和售后各自的状态、合法迁移、完成/关闭定义，以及是否共享状态。
- [ ] **消息归链规则**：Inquiry 与 Message 的基数、匹配依据、人工纠错方式、重复/冲突处理和未能匹配时的待处理策略。
- [ ] **售后静默期**：时长、起算事件/时间、是否按业务类型或渠道区分、延长规则。
- [ ] **静默期间新消息**：延长静默、重新激活、追加链路、生成待办或其他策略；需要明确去重与优先级。
- [ ] **恢复条件与授权**：自动/人工恢复条件、可操作角色、是否需要原因及审计要求。
- [ ] **处理终态关系**：`processed`/`ignored` 与归档、售后静默、业务关闭之间的定义；关闭后新消息是否重开。
- [ ] **转交后的可见性**：原负责人、当前负责人和运营角色对 Inquiry 及后续关联 Message 的读取/操作权限。
- [ ] **提醒/调度**：是否需要静默到期或超时提醒；接收人、频率、抑制、失败重试、取消和进程/部署恢复要求。
- [ ] **只读工作台范围**：查询对象、过滤条件、聚合指标、链路历史、test-only 数据处理口径及权限边界。
- [ ] **数据治理**：审计保留、客户隐私、删除/纠错语义，以及历史 Inquiry/Message 的分类和关联回填规则。

### 11.4 不可直接实现的风险

| 未确认项 | 直接实现的风险 |
|---|---|
| 分类规则/状态集合 | 把售后误判为询盘、过早关闭业务，或造成后续状态迁移不兼容。 |
| 消息归链与授权 | 错误合并不同客户/会话；关联错误可能扩大可见范围，造成跨用户数据泄露。 |
| 静默时长/期间新消息策略 | 漏掉客户新消息、过早重开、重复提醒或长期隐藏待办。 |
| 恢复条件/权限 | 无权用户解除静默，或业务无法及时恢复；自动与人工操作可能互相覆盖。 |
| `processed`/`ignored` 语义 | 把人工处理误当售后完成/静默，或阻止后续消息重开。 |
| 转交后可见性 | 源码已有 Inquiry—Message 关联并按消息来源账号 scope 裁剪；仍须以最新测试和角色浏览器验收确认，不应只凭 Inquiry 负责人推断所有关联消息均可见。 |
| 归档含义 | 把现有 restore 按钮误用为正式归档流程，遗漏状态生命周期、审计和恢复策略。 |
| 提醒调度 | 将 overview 进程内后台任务当可靠调度器，可能在重启后丢任务、重复提醒或无法取消。 |
| 分析口径 | 在业务分类、静默和 test-only 口径未定义时呈现误导性指标，或越过授权边界。 |
| 历史数据迁移 | 缺少分类/关联回填和回滚策略会造成错误归链、不可逆数据变更或部署不兼容。 |

**交接结论：**可继续进行规则确认、状态/关系建模和测试设计；确认前不应把 Day 9 标为完成，也不应将 `processed/ignored`、归档按钮、转交记录或 handoff 计划表称为售后状态机。Day 8 目标数据库、测试和 provider 证据仍按本记录前文的证据来源和边界表述；本节不构成新的目标环境验证。

### 11.5 归链与只读工作台实现状态（历史增量；本次文档同步时未执行验证）

工作区已有 Inquiry—Message 关联、身份规范化和确定性只读工作台实现；以下描述记录该增量代码合同，不代表后续所有改动或当前工作区的测试、构建、部署及目标环境验证已通过。

- `InquiryMessage` 关联表以 `(inquiry_id, message_id)` 为主键，另有 `message_id` 唯一约束和 Inquiry 内 position 唯一约束；关联行不存正文、概要或凭据。
- 确定性只读分析聚合 Inquiry 状态/处理状态/lifecycle、Message link_state/contact identity state、授权内未关联/待人工判断列表、最近可见事件和渠道阻塞；写意图仅返回页面指引，响应标记 `mutation_performed=false`、`write_operations_performed=0`。
- Admin 没有隐式全域穿透；只读查询和列表沿用账号 grant/Inquiry assignment 过滤。Blocked 账号按现有授权 scope 保持可见并标阻塞；revoked 消息排除。未关联列表不输出联系方式、正文或概要。
- 入站候选按规范化邮箱精确相等跨 Gmail/Outlook 匹配；WhatsApp 只认合法个人 `@s.whatsapp.net` 手机号，不与邮箱合并。身份不支持时不归链。
- 一个唯一候选可续接；多候选保持 Message 未关联并写 `manual_review`；无候选建新 Inquiry；重放未关联消息会重新评估，不改写已存正文。
- `messages.link_state` 的计划状态为 `pending`、`linked`、`unmatched`、`manual_review`、`not_linkable`。候选查询是只读的；运营从候选入口显式选择后才写关联，并在 Inquiry 时间线记录 `inquiry_message_linked`。
- 候选查询按当前用户授权过滤；写关联时必须分别授权目标 Inquiry、源 Message 及目标 Inquiry 中已有的全部来源账号。跨账号 Gmail/Outlook 同邮箱仅在操作者具备两端权限时允许；任何用户不能通过候选响应探测无权 Inquiry。
- Inquiry 详情按关联顺序逐条返回各自 provider、external message ID、正文安全视图、附件 metadata 和各自 overview；不聚合或覆盖 Message 原始数据。
- 测试源码覆盖唯一/多候选、错误身份、跨账号、越权、重复链接、事件/事务回滚及删除 Inquiry 时保留独立 Message/Overview；只读工作台测试源码比较请求前后业务表快照并覆盖 roles/scope/operation guidance。**这些测试本轮未运行；前端测试/build 也未运行。**
- 截至该增量，migration `0013_inquiry_messages.py` 曾记为源码草案；这不是当前工作区 head。当前代码迁移链继续包含 `0014_inquiry_business_type`、`0015_website_form_messages`、`0016_operation_logs` 和 `0017_message_feed_indexes`，head 为 `0017_message_feed_indexes`。本轮未核验目标 PostgreSQL 是否应用 0014–0017；须由用户提供最新在线 revision/schema 输出，不能沿用 0013 的历史目标库证据推定后续已应用。

**归链规则已确认并纳入当前实现草案：**邮箱匹配保存 raw 与 normalized 两值；normalized 邮箱仅 trim、取 display name 中地址部分、casefold，不折叠 `+tag`、点号或供应商别名。WhatsApp 手机号码使用 `phonenumbers` 规范化为 E.164；没有明确国际码或号码无效时保留人工核验，不猜国家码。WhatsApp 只按个人手机号身份匹配，LID/群组/未知 JID 不自动合并邮箱/手机号。

转发邮件优先使用 provider 可靠原始发件人头。Gmail 当前读取 `X-Original-From` / `Resent-From`，Outlook 当前读取 Graph `originalSender`；provider 明确标记转发但没有可信 original sender 时标 `identity_uncertain`，消息留在待人工判断，不自动归链。raw 联系人仍保留实际 sender，original sender 单独保存；本轮未实现修改 provider 扩展权限或读取真实 provider。

**人工关联合同：**运营/管理员必须同时有权访问目标 Inquiry 和 Message 来源账号；sales 不能跨授权范围人工关联。成功关联记 `manual_link` 事件，含 actor、Inquiry、message_id、原/新处理状态和时间；关联不改变 Inquiry 处理状态，不恢复静默、不发送客户消息。普通关联 API 拒绝身份不确定/转发记录；别名映射或身份确认专用流程尚未实现，不能用现有关联按钮绕过。

**授权可见性：**继续按关联消息逐条执行当前 Message scope；被撤权消息及其正文、概要、附件、联系方式、渠道和时间细节不序列化。Inquiry 仅在当前用户至少有一条可见关联消息时可见；候选查询只返回当前可见 Inquiry。关联撤权不删除 Inquiry 或仍有效的关联边。

**当前限制/验收边界：**migration 0013 已扩展 normalized/raw sender/identity state、`Message.link_state` 及 InquiryEvent `message_id` 外键；旧记录默认 needs_manual_review 且不回填，不据历史 raw 字符串推断身份。新增 `phonenumbers` 依赖已纳入代码，但运行环境安装/部署状态需以用户环境为准。候选冲突使用现有 Inbox 留待人工选择，尚无独立待办模型；别名映射、身份确认动作、通知队列未实现。目标 PostgreSQL 专项约束核验已由用户于 2026-11-10 提供 SQL 输出并确认 revision/schema/主要约束；浏览器角色/工作台联调和联调账号/渠道授权配置仍待补。

**Day 9 自动化验证记录（用户于 2026-11-09 提供的命令输出；后续代码改动后需重跑）：**

```text
后端定向：pytest -q tests/test_business_authorization.py tests/test_inquiry_message_links.py tests/test_inquiry_link_routes.py tests/test_contact_identity.py tests/test_migrations.py
75 passed, 2 warnings in 39.24s

后端全量：pytest -q
214 passed, 2 warnings in 45.85s

前端单测：npm run test:unit
8 passed, 0 failed

前端构建：npm run build
vite build 成功（18 modules transformed）
```

该输出是用户提供的实际执行结果，不是本轮助手执行。记录的 warning 为 Starlette/httpx `TestClient` 弃用提示，以及 Alembic `path_separator` 配置弃用提示。用户同时确认目标数据库当时 revision 已到 `0013_inquiry_messages`；此为历史时点事实，不证明当前库已应用 0014–0017，也不能代替后续目标库在线核验。

**Day 9 相关源码增量（关联、身份、只读工作台及后续字段/索引）已进入当前工作区；历史自动化回归早于后续改动，当前工作区版本回归待重跑。目标 PostgreSQL 的历史专项核验截至 0013；0014–0017 和当前 schema 未核验。浏览器角色/工作台联调待补。不得写成 Day 9 或整体全部验收完成。**

目标 PostgreSQL 核验记录（用户于 2026-11-10 提供）：`alembic_version=0013_inquiry_messages`；`inquiries`、`inquiry_events`、`inquiry_messages`、`message_overviews`、`messages` 表均存在；身份列、`link_state`、`inquiry_events.message_id` 和关联表约束/外键与 0013 设计相符。该核验是用户在目标服务器执行的只读 SQL 输出，不代表本助手连接或执行 migration；数据级重复/孤儿行、级联删除实测和浏览器权限行为仍待验收。

用户于 2026-11-09 提供过后端定向 75 passed、后端全量 214 passed、前端 8 passed、build 成功；这些结果早于之后的身份规范化、撤权部分视图和只读工作台改动，不能作为当前工作区回归通过证据。当前工作区需由用户重跑后端定向/全量、前端测试/build。联调账号及渠道授权映射尚未配置；待配置后需完成运营、sales、admin、跨账号、revoked/blocked、空范围、manual_review、只读不变更的浏览器角色联调。

**工作台只读边界/业务口径：**指标与列表均先使用当前用户 scoped Inquiry/Message/ChannelAccount 查询；sales pending message count 是其已分配 Inquiry 下当前可见的关联 Message 行数，不能和 Inquiry 数混为一谈。`pending_contact_count` 只按 identity_state=certain 的 normalized 联系人分组；未确认身份不计入联系人组但可进入人工核验列表。`unlinked_messages` 限于可见、入站、pending、未关联且 link_state=unmatched 的最近 100 条；manual_review 和 identity_uncertain 独立列出最多 100 条。最近事件只从 `_visible_inquiry_events` 取当前可见事件；blocked account 可见并标异常，revoked account 消息不进入结果。Read 响应标记未执行写操作；create/update/delete/assign/send 返回 guidance。测试源码断言 read/guidance 前后业务表快照相同，但本轮未运行测试，不能表述为已通过。

提醒调度、真实 provider/出站和备份恢复仍按各自范围待验收，不由以上代码状态推定完成。
