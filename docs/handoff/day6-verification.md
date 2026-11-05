# Day 6 三渠道真实入站验收总览

> 本记录只汇总非敏感证据和剩余行动，不记录密码、OAuth code、access/refresh token、client secret、MCP bearer token、Pub/Sub push token、QR、Baileys auth state、手机号、完整认证 URL、邮件正文或附件内容。它汇总分渠道记录，不替代各渠道详细证据。

## 1. 验收标准来源

Day6 验收标准以 [plan/day6.md](../../plan/day6.md) 为准。本文件只记录已经发生的代码、部署和用户提供的真实环境结果；未单独证明的项目保持待验收。

## 2. 当前分渠道状态

| 渠道 | 当前状态 | 主入站结论 | 仍待补证据 |
|---|---|---|---|
| Gmail | `verified_inbound` | OAuth、Watch、Pub/Sub、History/Message、mapping、目标 PostgreSQL Message 入库和线上状态收口已有记录 | 专门 redelivery、Watch 续订/过期恢复、history reconciliation、OIDC/JWT、附件、限流/撤销持续验证 |
| Outlook | `verified_inbound` | 用户提供页面显示主动读取完成：确认 10 条、新增 8 条、重复 2 条；页面显示真实入站验收状态 | 目标 PostgreSQL/外部 ID 的独立非敏感记录、撤销/限流/失败恢复持续验证 |
| WhatsApp | `verified_inbound` | 用户提供收件箱截图显示真实入站消息；bridge → backend inbound → mapping → Message → 收件箱路径已有代码和状态收口 | 真实生产重放、disconnect/revoked 后拒绝与历史保留、重新关联恢复、bridge 现场构建；当前无另一 WhatsApp 个人账号，跨身份测试待执行 |

详细记录：

- [Gmail 验收记录](day6-gmail-verification.md)
- [Outlook 验收记录](day6-outlook-verification.md)
- [WhatsApp 验收记录](day6-whatsapp-verification.md)

## 3. 共同代码路径

三渠道均经过 provider-specific 读取/事件入口、来源/授权与账号范围检查、规范化 mapping 和统一幂等 Message 入库。唯一身份为：

```text
(channel_account_id, provider, external_message_id)
```

前端“我的 / 账号管理”只调用本项目 `/api/...` 后端接口，不直接调用 Gmail、Microsoft Graph、Outlook MCP、Baileys 或 bridge provider；前端未发现长期保存 access token、refresh token、client secret 或 auth state 的实现。WhatsApp QR 只短时保留在当前页面内存。

## 4. 已确认的 Day6 交付

- 三渠道 provider 方案与实际代码路径已核对；
- Gmail 真实 OAuth/Watch/Pub/Sub/History/Message 主链路已有目标环境记录；
- Outlook 真实主动读取结果已由用户页面提供；
- WhatsApp 真实入站消息已由用户收件箱页面提供；
- 三渠道 mapping 和统一 Message 幂等服务已实现；
- “我的”个人渠道连接、重新授权/重新关联和状态展示已实现；
- fake/provider-neutral fixture 保留并标记为 `test_only`；
- 未执行真实出站消息；
- 未把 Day7 的 HTML 清洗、正文展示优化写入 Day6 完成项。

## 5. 尚未使严格 Day6 全部闭环的项目

以下项目不能用代码测试、页面状态或单次成功消息替代：

1. Gmail 对同一 Pub/Sub 投递的受控生产 redelivery 结果；
2. Gmail Watch 续订、过期恢复和 history cursor 过期 reconciliation；
3. Gmail Pub/Sub OIDC/JWT、service account/audience 的来源认证（当前记录仍是 shared push token）；
4. Outlook 目标 PostgreSQL、external message ID 和第二次主动读取的独立非敏感记录；
5. WhatsApp 同一真实事件生产重放不重复入库；
6. WhatsApp disconnect/revoked 后新事件拒绝且历史消息保留；
7. WhatsApp 重新关联后的恢复入站；
8. WhatsApp bridge 当前版本的现场 TypeScript build；
9. 三渠道真实附件下载/metadata；
10. provider 限流、授权撤销、长时间运行和失败恢复的真实环境证据；
11. 三渠道目标 PostgreSQL revision/schema/唯一约束/事务核验的统一记录。

## 8. 目标 PostgreSQL 只读核对结果（2026-11-04）

用户授权在核对阶段执行只读命令；未执行 migration、清理或数据写入。结果如下：

```text
Compose services: backend/db/frontend/whatsapp-bridge = running
db health: healthy
Alembic current: 0009_outlook_account_credential (head)
Alembic heads:   0009_outlook_account_credential (head)
```

已确认目标 PostgreSQL 具有：

- `channel_accounts` 的 external account、Gmail credential reference/ciphertext、Gmail Watch cursor/expiration 和 Outlook credential ciphertext 字段；
- `messages` 表及 provider/account/external message ID 唯一约束 `uq_messages_account_provider_external_id`；
- 消息 direction/status/handling_status CHECK 约束；
- `message_attachments.message_id` 外键及 `ON DELETE CASCADE`；
- 三个渠道账号均有 external account mapping，且当前状态为 `verified_inbound`；
- Gmail 和 Outlook credential reference 存在；只确认存在性，未读取密文。

这项只读核对支持目标 schema/revision/状态基础项已完成；不替代三渠道各自的真实重复、撤销/断开恢复、附件和 provider 失败恢复证据。

同一只读核对还得到各 canonical provider 的目标库消息计数（只读聚合，不读取正文或外部 ID）：

```text
gmail_api_pubsub      inbound/received = 3
outlook_mcp_graph     inbound/received = 10
whatsapp_web_baileys  inbound/received = 9
```

计数证明目标库已有三渠道消息记录，但不单独证明每一条记录的真实来源或生产重放结果。

这些项目中，无法执行的项目应记录具体外部原因；不得用 fake、fixture、手工 normalized 请求或页面状态伪造真实证据。

## 6. Day6 当前表达

准确表达为：

> 三渠道真实 provider 入站主链路均已实现并已有真实运行结果，其中 Gmail、Outlook、WhatsApp 当前页面状态均为 `verified_inbound`。Day6 的严格补充验收仍包括真实重放、撤销/断开恢复、部分 provider 来源/恢复/附件和目标 PostgreSQL 证据；这些边界未完成前，不表述为所有 Day6 验收项无条件全部通过。

## 7. 下一步执行顺序

1. 先核对并记录目标 PostgreSQL revision/schema/唯一约束，不执行迁移或清理；
2. 对 Gmail 执行一次受控 Pub/Sub redelivery（若 subscription 无可用重放对象，记录阻塞）；
3. 对 Outlook 再执行一次主动读取，记录 total/created/duplicates 和非敏感 provider 结果；
4. WhatsApp 条件允许时用另一身份发送专用测试消息；没有另一身份则记录跨身份测试阻塞；
5. 在确认影响和恢复方式后，验证 WhatsApp disconnect/revoked、历史保留和重新关联；
6. 记录仍未完成的 Watch、OIDC/JWT、附件、限流和恢复边界；
7. Day6 结束后再进入 Day7 的 HTML/MIME 清洗和收件箱展示优化，不把两者混在本记录中。

## 9. 渠道映射展示与账号退出（2026-11-04）

当前代码和线上页面已核对：

- “我的”页面通过渠道账号接口读取非敏感 `external_account_id` 和状态，不把业务收件箱账号接口缺少映射字段误判为映射丢失；
- Gmail、Outlook、WhatsApp 的账号记录均可展示外部账号映射；
- 前端退出登录调用 `POST /auth/logout`，后端撤销当前 `UserSession` 并删除 session/CSRF cookie；
- 该退出登录是系统账号会话退出，不等同于撤销 Google/Microsoft 授权或断开 WhatsApp 关联设备；provider 侧撤销仍需在各自官方入口或渠道断开入口执行；
- 历史消息不因系统退出登录而删除；
- 前端仍不保存 token、refresh token、client secret、QR 或 auth state。

本次验证：

```text
frontend unit tests: 7 passed
frontend production build: passed
backend channel/disconnect/authorization tests: 32 passed, 1 warning
```

代码实现和隔离测试已完成；真实 provider 撤销、WhatsApp 断开恢复和生产重放仍只在有实际环境证据时记录，不因系统退出登录而宣称已完成。

## 10. Day6 当前收口结论（2026-11-04）

基于三渠道真实入站结果、当前线上 `verified_inbound` 状态、外部账号映射展示和前后端系统退出登录实现，Day6 的**代码实现与真实入站主链路验收可以标记为完成**。当前完成范围包括：

- 三渠道 provider-specific 入站路径；
- 来源/授权和账号映射；
- provider mapping 与统一 Message 幂等入库；
- 授权收件箱显示；
- `verified_inbound` 状态收口；
- “我的”渠道账号管理和非敏感映射展示；
- 系统账号退出登录；
- 前端不直连 provider、不长期保存 provider 凭据；
- 未执行真实出站发送。

以下是已知的**补充验收边界**，不影响上述主任务完成结论，但不能写成已通过：真实 provider redelivery/replay、Watch 续订和 history 恢复、Pub/Sub OIDC/JWT、附件下载、限流/撤销/长时间恢复、WhatsApp 断开后恢复，以及没有第二个 WhatsApp 身份时无法完成的跨身份测试。它们应作为后续环境核验项保留。

## 11. 本轮最小验收复核（2026-11-04）

本轮在当前工作区重新执行了不依赖外部 provider 的隔离回归：

```text
backend Day6 定向回归: 96 passed in 16.29s
backend 全量回归: 136 passed, 1 warning in 17.21s
frontend unit tests: 7 passed
frontend production build: passed
WhatsApp bridge tests: 7 passed
```

后端定向回归覆盖了：

- Gmail 重复 Pub/Sub 投递不新增 Message；
- Outlook 统一入库幂等和主动读取边界；
- WhatsApp 同一 `external_message_id` 重放不新增 Message；
- 错误 external account mapping 被拒绝；
- revoked 账号不能接收新入站，历史记录保留在数据库但不进入当前授权读取范围；
- 授权范围和无权用户的账号/消息访问隔离；
- provider 401/403、临时失败、限流和数据库 rollback 的隔离失败路径；
- 系统 `POST /auth/logout` 后 session 失效，且不撤销 provider 授权或删除历史消息。

本轮当前机器无法完成的复核：

- `docker compose ps`：本机未发现 Docker CLI，因此不能把本轮运行中的 backend/frontend/PostgreSQL/bridge 状态写成已重新核验；
- 本轮已补齐本机 Alembic 依赖并通过后端全量 pytest；唯一 warning 是 Alembic 配置缺少 `path_separator` 的弃用提示；
- 目标 PostgreSQL revision、schema 和线上最新 frontend bundle：只能引用本文件第 8 节已有的用户提供证据，不能冒充本轮实测。

附件状态明确记录如下：

```text
本次真实测试无附件；
真实附件下载和 metadata 尚未验收。
```

因此当前阶段仍准确表述为：**Day6 核心真实入站链路已完成，Day6 最小隔离安全/幂等/权限收口已有证据；Day6 长期运行、真实重放/恢复、附件和部分目标环境复核待补。可以开始 Day7，但不得将 Day6 写成所有验收项全部通过。**

## 12. 幂等、权限和撤销隔离收口（2026-11-04）

本轮按要求只使用 fake provider、SQLite 和 TestClient；没有调用真实 Gmail、Outlook、WhatsApp，也没有修改真实账号、目标 PostgreSQL 或生产部署。

代码收口：

- 三渠道消息统一使用 `(channel_account_id, provider, external_message_id)` 唯一身份；重复投递返回已有 Message，不覆盖正文、不追加附件；
- Gmail Pub/Sub、Outlook 主动读取和 WhatsApp inbound 都经过账号映射和渠道状态检查；错误 external account mapping 被拒绝；
- revoked 账号拒绝新入站，历史消息保留在数据库；授权查询只返回当前有效授权账号；
- Outlook 消息入库和 `verified_inbound` 状态改为单事务提交；提交失败 rollback；
- WhatsApp inbound 提交失败显式 rollback；
- 系统账号 logout 只撤销项目 session，不撤销 provider 授权，不删除历史消息。

隔离后端全量回归结果：

```text
136 passed, 1 warning
```

以上结果只能证明本地代码路径和隔离数据库行为，不能替代真实 provider 重放、真实撤销/断开、目标 PostgreSQL 或长期运行验证。
