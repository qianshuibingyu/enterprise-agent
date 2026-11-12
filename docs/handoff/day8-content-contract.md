# Day 8 原文、内容处理与知识 Chunk 合同

> 本文件记录 Day 8 已确认的最小内容合同和迁移影响。它是设计与验收边界，不表示相关业务已经实现。
>
> 本轮不读取 `.env`、token、QR、auth state 或客户敏感正文；不连接真实 provider，不发送消息，不运行 migration，不创建向量索引，不下载 embedding 模型。

## 1. Day 8 开始前基线与当前结果

本节前半部分记录 Day 8 开始前的基线，不能继续当作当前代码状态。Day 8 交接结果见 [day8-verification.md](day8-verification.md)。

Day 8 开始前，项目已完成 Gmail、Outlook、WhatsApp 三渠道真实入站主链路，但当时尚不能假设以下能力存在：

- LLM 接入和中文概要生成；
- 原文回源查看接口；
- `message_overviews` 表；
- 知识资料表和 chunk 表；
- embedding 生成；
- pgvector 或其他向量检索实现。

Day 8 实际新增/确认：

- 授权的 Gmail/Outlook/WhatsApp 原文回源代码和安全失败回退；
- `message_overviews` 模型及 `0012_message_overviews` migration；
- OpenAI 兼容 LLM 中文概要代码边界、异步状态、失败回退和手动重试；
- provider-neutral、纯内存、确定性资料清洗/切片模块及测试。

当前仍没有：

- 知识资料上传 API、ACL 服务和资料数据库；
- 持久化 chunk、embedding、pgvector、关键词/向量检索或 RAG；
- 回复建议、回复审批、真实出站发送。

## 2. 内容对象分层

Day 8 区分以下对象：

```text
渠道入站内容
  -> 数据库安全纯文本
  -> 中文概要（未来由 LLM 生成）
  -> 页面默认展示中文概要
  -> 用户主动查看原文时，后端按授权回源并返回安全纯文本
```

知识资料是独立链路：

```text
获授权员工上传资料
  -> 资料解析/清洗
  -> 未来切片
  -> 未来 embedding
  -> 未来 pgvector 检索
```

客户消息和询盘默认不进入知识库，也不自动生成知识 chunk。

## 3. 原始载荷合同

### 3.1 定义

原始载荷指渠道适配器接收到的 provider 输入或其结构化表示。它可能包含 HTML、MIME、provider metadata 或其他未适合展示的内容。

Day 8 不新增独立原始载荷表，也不向浏览器返回原始 HTML、MIME 或 provider payload。

### 3.2 当前与目标语义

当前最接近的字段是：

- `Message.raw_content`；
- `Inquiry.raw_message`。

经确认的目标策略是：

- 新入站消息写入数据库前先解析并清洗为安全纯文本；
- `raw_content` / `raw_message` 的 Day 8 合同语义改为“安全纯文本内容”，不再把它们作为 HTML/MIME 原文 API；
- 历史数据不回填、不覆盖；
- 历史数据继续由当前 API 运行时安全清洗；
- 需要查看渠道原文时，后端根据 provider、channel account 和 external message ID 回源；
- 回源失败时继续展示数据库安全纯文本，并明确提示原文回源失败。

这是一项尚未实现的入站处理语义变更。当前代码仍主要在响应时调用 `content_view()`，不能将当前字段直接表述为已经完成入站持久化清洗。

### 3.3 来源标识

消息必须保留以下回源所需标识：

| 字段 | 来源 | 目标持久化 | 说明 |
|---|---|---:|---|
| `channel_account_id` | 入站账号 | 是 | 用于账号 scope 和后端回源账号选择 |
| `provider` | provider adapter | 是 | 用于选择渠道解析/回源适配器 |
| `external_message_id` | provider | 是 | 用于定位 provider 消息 |
| `provider_web_link` | provider 或后端回填 | 可选 | 只作为网页处理入口，不替代 provider ID |
| `test_only` | 运行环境/fixture | 目标需统一 | 标记真实数据或测试数据 |

浏览器不保存或接收长期 provider token、refresh token、client secret、QR 或 auth state。回源必须由后端在授权检查之后执行。

## 4. 原文合同

### 4.1 定义

“原文”在 Day 8 中表示从渠道取得、经过后端解析并以安全纯文本形式展示的客户原始消息内容，不表示把原始 HTML、MIME 或 provider payload 直接交给浏览器。

### 4.2 展示方式

正常工作台展示：

- 中文概要；
- 原文不默认全部展开。

用户点击“查看原文”后：

1. 后端先按当前用户授权检查消息和渠道账号；
2. 后端使用 provider ID 回源；
3. 后端解析并清洗为安全纯文本；
4. 文本展示区域先显示原语言最多 3 行；
5. 页面提供“展示全文”操作；
6. 用户展开后查看完整的安全纯文本；
7. 不返回原始 HTML、MIME 或 provider payload。

回源失败时：

- 继续展示数据库中的安全纯文本；
- 显示“原文回源失败”或等价提示；
- 不把数据库缓存内容错误标记为刚刚从 provider 获取的原文。

### 4.3 回源失败和撤销边界

渠道撤销、账号断开、provider 不可用或 provider 已删除原消息时：

- 不绕过渠道授权；
- 不因历史消息存在而继续使用失效凭据；
- 保留数据库安全纯文本和业务历史，除非后续生命周期规则要求删除；
- 允许页面显示安全缓存内容和回源失败状态；
- 不因此扩大用户对历史消息的访问范围。

## 5. 安全展示正文合同

### 5.1 字段

| 字段 | 来源 | 是否单独持久化 | 合同 |
|---|---|---:|---|
| `display_text` | 安全解析结果 | 当前运行时生成 | `text/plain`，最多 12,000 字符 |
| `display_excerpt` | `display_text` 截断 | 当前运行时生成 | 最多 280 字符，作为规则展示摘录 |
| `content_format` | 系统 | API 返回 | 固定为 `text/plain` |
| `content_sanitized` | 系统 | API 返回 | 安全展示结果为 `true` |
| `content_truncated` | 长度判断 | API 返回 | 超过 12,000 字符时为 `true` |
| `test_only` | 来源环境 | 目标需统一 | 真实数据为 `false`，fixture 为 `true` |

Day 7 文档曾记载正文 20,000、摘要 240；Day 8 当前采用正文 12,000、展示摘录 280、中文概要 100 字符。相关文档、测试和实现应统一到这一口径。

### 5.2 清洗规则

安全展示正文必须：

- 输出纯文本而不是 HTML；
- 忽略危险或嵌入元素，包括 `script`、`style`、`iframe`、`frame`、`object`、`embed`、`form`、`svg`、`math`；
- 删除 NUL 和控制字符；
- 规范空格和换行；
- 对 malformed 内容安全降级；
- 前端使用文本插值；
- 不使用 `v-html` 或 `innerHTML`。

PDF、DOCX、图片和 OCR 深度解析不属于当前纯文本范围，后续按计划接入 MinerU 时另行定义。

## 6. 中文概要合同

### 6.1 语义

中文概要是由 LLM 生成的面向运营人员的客户消息业务语义概要，不是逐句翻译，也不等同于当前 `display_excerpt`。概要应优先表达客户意图/问题、请求动作或期望和运营需要关注的关键事实。

当前规则截断只能称为：

> 规则摘录，非 AI 概要

不能把规则摘录、HTML 转纯文本、状态统计或 fake fixture 命名为 AI 概述。

### 6.2 生成范围

自动生成范围：

- 仅 `inbound` 消息；
- 仅未处理、未忽略消息；
- 排除测试 fixture 和 fake provider；
- 生成与查看严格遵守原有消息/询盘授权；
- 不对 outbound 消息自动生成。

同一条消息按以下唯一身份判定：

```text
(channel_account_id, provider, external_message_id)
```

重复入站直接复用已有概要，不再次调用 LLM。

### 6.3 生成时机和任务方式

- 新消息入库后自动生成；
- 采用后端进程内后台任务；
- 不阻塞 provider 入站确认和消息入库；
- 服务重启时，未完成的 `pending` 概要标记为 `failed`；
- 有权用户可以手动重试；
- 后续如需可靠重试、跨进程恢复或规模化处理，再单独引入任务队列。

### 6.4 LLM 输入和配置

LLM 目前尚未接入。未来采用 OpenAI 兼容接口，但不得据此假设已有具体 provider 或模型。

目标配置：

- base URL：环境变量；
- API key：环境变量；
- model：环境变量；
- prompt version：代码/配置版本标识；
- 前端不接触任何 LLM 凭据；
- 不将 key 写入代码、数据库、URL 或日志。

发送给 LLM 的输入只允许是已经保存的安全纯文本：

- 不发送原始 HTML；
- 不发送原始 MIME；
- 不发送 raw provider payload；
- 不发送 token、secret、QR 或 auth state；
- 不发送附件二进制；
- 不发送 provider credential。

### 6.5 持久化表

目标新增 `message_overviews` 表，与 `messages` 一对一。

最小字段建议：

| 字段 | 来源/用途 | 合同 |
|---|---|---|
| `id` | 系统生成 | 主键 |
| `message_id` | Message | 非空外键；唯一 |
| `status` | 生成流程 | `pending` / `ready` / `failed` |
| `overview_text` | LLM 输出 | 安全纯文本，最多 100 字符 |
| `failure_code` | 脱敏错误分类 | 失败时可填，不保存原始错误响应 |
| `retry_count` | 任务/手动重试 | 非负整数 |
| `provider_name` | 非秘密 provider 标识 | 可选，不保存凭据 |
| `model_name` | 环境变量中的模型名 | 非秘密元数据 |
| `prompt_version` | 代码/配置版本 | 用于来源追溯 |
| `generated_at` | 系统时间 | 生成成功时间 |
| `updated_at` | 系统时间 | 最近状态变更时间 |
| `test_only` | 来源环境 | 测试概要为 `true` |

只保留当前最新概要。重新生成成功后覆盖当前失败记录或更新同一条记录；不保留历史概要版本。

中文概要表不重复保存原语言三行摘录。原语言三行和全文由安全纯文本实时计算。

### 6.6 输出校验

概要写入前必须：

- 去除 HTML；
- 去除控制字符；
- 只保存纯文本；
- 最大 100 字符；
- 不保存模型提示词残片；
- 不保存结构化控制标记；
- 不执行模型返回的链接、脚本或工具指令；
- 超长或格式不合格输出标记为失败，或经过明确的安全截断策略处理。

失败时：

- 持久化 `failed` 状态和脱敏错误类别；
- 页面可展示安全正文的规则摘录；
- 明确标记“规则摘录，非 AI 概要”；
- 不把规则摘录伪装成模型输出。

### 6.7 处理状态和概要删除

消息点击“已处理”或“忽略”时：

- 在同一后端事务中清除该消息的当前 `message_overviews` 记录；
- 更新消息人工处理状态；
- 保留 Message、安全纯文本、来源标识、附件 metadata 和审计记录；
- 事务失败时状态更新和概要清除一起回滚。

询盘点击“已处理”或“忽略”时：

- 在同一事务中清除该询盘关联的全部消息概要；
- 保留消息、安全正文和消息—询盘关联记录；
- 保留处理事件和审计记录。

已处理或已忽略对象不能再次自动生成或手动重试概要，除非未来明确增加重新开启业务状态的规则。

## 7. Message—Inquiry 关联合同

当前 `Inquiry` 和 `Message` 没有直接关联。为支持一个询盘关联多条不同客户消息，目标新增：

```text
inquiry_messages
```

最小字段：

| 字段 | 合同 |
|---|---|
| `inquiry_id` | 非空外键，指向 `inquiries.id` |
| `message_id` | 非空外键，指向 `messages.id` |
| `created_at` | 关联创建时间 |
| `test_only` | 关联来源标识，需与来源数据一致 |

约束：

- 一个 Inquiry 可以关联多条 Message；
- 一条 Message 最多关联一个 Inquiry；
- 同一 Inquiry 与 Message 组合不可重复；
- 删除来源对象时关联记录按明确级联规则处理；
- 关联表不复制客户正文和概要内容。

询盘详情应按关联消息逐条读取各自 `message_overviews`：

- 每条不同消息生成自己的概要；
- 同一消息重复入站复用已有概要；
- 不把多条不同内容压成一个不透明的询盘概要。

## 8. 知识资料与 Chunk 合同

### 8.1 当前范围

Day 8 已实现一个 provider-neutral、纯内存的资料清洗/切片模块和隔离测试；它不上传、不持久化、不执行 ACL 决策、不生成 embedding，也不执行检索。当前不创建知识库表或 chunk 数据。

模块仅接受调用方已完成授权判定的 `product` / `public` 文本对象；没有上传 API 或知识库接入，因此不得将本模块表述为资料库/RAG 已实现。

未来资料来源限定为：

- 管理员上传；
- 获授权员工上传。

第一批资料范围：

- 产品资料；
- 公开资料。

客户 Message 和 Inquiry 默认永远不是知识库资料。

### 8.2 资料权限与回复用途

资料可见范围与“是否可用于回复客户”是两个独立字段。

资料可见范围未来可按实际权限模型表达，例如：

- 仅部门内可见；
- 仅相关部门可见；
- 全公司可见；
- 其他经授权的个人/部门范围。

上传表单在资料可见范围之后，单独提供：

```text
当前资料是否可用于回复客户：是 / 否
```

该字段只控制资料能否作为未来客户回复建议的依据，不替代员工读取权限，也不代表资料公开或可以直接发送原文。

### 8.3 当前 provider-neutral Chunk 输出与未来持久化合同

当前模块允许的输入格式为 UTF-8 纯文本、Markdown 和 HTML；PDF、DOCX、图片、OCR、附件及未列出的格式明确拒绝，后续解析可由 MinerU 等独立接入。HTML/Markdown 清洗只产出纯文本；危险 HTML 子树和 Markdown 代码围栏内容不进入 chunk。

当前 chunk 策略：保留标题/段落边界；每个 chunk 最多 1,200 字符；单个超长段落按字符切分，重叠 100 字符；相同内容和处理版本确定性地产生相同 hash 与 chunk 序号。模块只返回结果，不写数据库。

未来的 `knowledge_chunks` 至少需要：

| 字段 | 合同 |
|---|---|
| `id` | chunk 主键 |
| `document_id` | 来源资料 |
| `document_version` | 来源版本 |
| `chunk_index` | 资料内稳定序号 |
| `chunk_text` | 清洗后的文本；建议最多 4,000 字符 |
| `source_locator` | 页码、段落或字符范围等来源位置 |
| `source_title` | 来源标题；建议最多 512 字符 |
| `visibility_scope` | 资料读取权限范围 |
| `reply_eligible` | 是否可用于回复客户 |
| `cleaning_version` | 清洗规则版本 |
| `test_only` | 测试 chunk 必须为 `true` |
| `status` | `pending` / `ready` / `failed` / `deleted` |

检索必须先执行权限过滤，再进行关键词或向量召回。删除或失效资料版本后，其 chunk 不得继续被检索。

### 8.4 向量方向

Day 8 已确认的未来向量方向：

- 向量数据库：PostgreSQL + pgvector；
- embedding 模型：`BAAI/bge-small-zh-v1.5`；
- 当前没有向量数据库；
- 当前没有 embedding 模型部署；
- 不安装 embedding 或向量数据库依赖；
- 不修改 `compose.yaml`；
- 不创建 pgvector 扩展、向量列或索引；
- 不运行真实 embedding；
- 不写入向量数据；
- 不用 fake embedding 或 fake retrieval 结果声称生产 RAG 已完成。

模型和向量库实际部署前仍需单独验证：

- 模型许可；
- CPU/RAM 占用；
- 中文检索质量；
- 2 vCPU/2 GiB 目标环境可行性；
- pgvector 扩展是否可用；
- 资料规模和索引维护成本。

## 9. `test_only` 合同

| 数据来源 | `test_only` |
|---|---:|
| 真实 Gmail 入站 | `false` |
| 真实 Outlook 入站 | `false` |
| 真实 WhatsApp 入站 | `false` |
| 真实内部资料 | `false` |
| fake provider | `true` |
| 测试 fixture | `true` |
| 离线 UI 样例 | `true` |
| 测试中文概要 | `true` |
| 测试 knowledge chunk | `true` |

测试内容不得进入真实用户的消息列表、概要结果或未来知识检索范围。前端如展示测试对象，应明确显示 `TEST_ONLY`。

## 10. 最小迁移影响

本合同尚未执行任何 migration。后续实现至少可能新增：

### 10.1 `message_overviews`

- 新表；
- `message_id` 外键和唯一约束；
- 状态、概要文本、失败分类、重试次数和非秘密模型元数据；
- 消息处理接口的事务清除逻辑；
- 概要权限和失败路径测试。

### 10.2 `inquiry_messages`

- 新表；
- `inquiry_id`、`message_id` 外键；
- `message_id` 唯一约束；
- `(inquiry_id, message_id)` 联合唯一约束；
- 查询索引；
- 入站与询盘创建流程的关联逻辑；
- 询盘详情逐消息加载概要。

### 10.3 现有内容字段语义

新消息采用“写入安全纯文本”的目标语义时，需要：

- 修改各渠道入站 mapping/保存路径；
- 明确当前 `raw_content` / `raw_message` 的字段注释和 API 合同；
- 保证历史数据仍可通过运行时清洗安全展示；
- 不在本轮回填或覆盖历史数据；
- 增加解析失败、超长和异常内容测试。

### 10.4 暂不新增

本轮不新增：

- 独立原始载荷表；
- 独立解析 artifact 表；
- `knowledge_documents`；
- `knowledge_chunks`；
- embedding 列；
- pgvector 扩展或索引；
- 任务队列服务；
- LLM 凭据数据库配置表。

## 11. 必须覆盖的合同测试场景

### 内容和授权

1. 有权运营人员只能查看本人渠道 scope 内的安全纯文本和概要。
2. 业务员只能查看已转交给本人的必要原始信息。
3. 无权用户不能通过消息 ID、询盘 ID、概要 ID 或关联 ID 探测对象存在性。
4. revoked 渠道保留历史数据但不绕过当前授权范围。
5. 派生概要和回源接口不能扩大来源对象权限。

### 原文回源

1. 回源使用 provider、channel account 和 external message ID，而不是浏览器提供 token。
2. 浏览器不收到原始 HTML、MIME、provider payload 或 credential。
3. 回源成功返回安全纯文本。
4. 回源失败继续返回数据库安全纯文本并带失败提示。
5. provider 消息不存在、账号撤销或 provider 超时时不伪报回源成功。
6. 当前用户无权时先拒绝，不执行 provider 探测。

### 中文概要

1. 只有有效 inbound、未处理、非测试消息自动生成。
2. 重复消息不重复调用 LLM。
3. `channel_account_id + provider + external_message_id` 相同的消息复用现有概要。
4. LLM 只收到安全纯文本。
5. API key、token、QR、auth state、附件二进制不进入 LLM 输入。
6. 概要只保存纯文本，最多 100 字符。
7. HTML、控制字符、工具指令和不合格结构不进入概要。
8. LLM 失败保存脱敏失败状态，不保存原始错误响应。
9. 失败页面显示“规则摘录，非 AI 概要”。
10. 服务重启后 pending 概要变为 failed。
11. 有权用户可以重试；成功后只保留当前最新概要。
12. 已处理/已忽略对象不能重新生成。
13. 消息或询盘处理时，概要清除与状态更新同事务完成。
14. 清除概要不删除消息、安全正文、来源入口、附件 metadata 或审计。

### Message—Inquiry 关联

1. 一个 Inquiry 可以关联多条 Message。
2. 一条 Message 最多关联一个 Inquiry。
3. 重复关联被数据库和服务层拒绝。
4. 询盘详情按消息分别读取概要。
5. 关联表不复制正文或概要内容。

### 知识资料

1. 客户消息默认不创建 knowledge chunk。
2. 客户询盘默认不创建 knowledge chunk。
3. 资料可见范围与 `reply_eligible` 独立检查。
4. 未获资料读取权限不能读取或检索 chunk。
5. `test_only=true` 的资料和 chunk 不进入真实范围。
6. 删除或失效资料版本后不能召回其 chunk。
7. 没有 embedding 服务时，不显示向量检索已启用。

## 12. 当前准确结论

Day 8 已确认的是内容合同和后续实现边界，不是功能完成证据。

当前准确表述：

> 三渠道真实入站主链路已完成验收。当前工作台能够在授权范围内展示运行时清洗后的安全纯文本和规则展示摘录。Day 8 计划新增安全纯文本写入语义、后端授权回源查看、中文概要持久化和 Message—Inquiry 多消息关联；中文概要将通过未来配置的 OpenAI 兼容 LLM 异步生成。知识资料只由获授权员工上传，客户消息默认不进入知识库；PostgreSQL + pgvector 和 `BAAI/bge-small-zh-v1.5` 只是未来方向，当前尚未部署、生成 embedding 或提供 RAG 检索。

本文件不证明目标环境浏览器联调、LLM 调用、原文回源、迁移、pgvector 或 embedding 已完成。
