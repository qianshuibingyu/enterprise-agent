# Day 5 消息可靠性、失败恢复与入站处理验证记录

> 本记录只使用当前工作区代码和用户实际提供的本地/目标环境结果。fake/provider-neutral 测试不等同于真实 provider，目标数据库 revision 不等同于 PostgreSQL 并发/约束专项验收。本文件不记录凭据、token、QR、auth state 或客户敏感内容。

## 1. Day 5 代码增量

已完成并保留在当前工作区：

- internal analysis 固定状态键合同：
  - `new`/`assigned`；
  - `pending`/`processed`/`ignored`；
  - 缺失状态补 `0`；
- 前端分析 API 类型和人工处理分析卡片；
- 消息唯一约束驱动的幂等入库；
- 重复消息不覆盖原始正文或追加附件；
- 单条 SAVEPOINT 与批次 SAVEPOINT 事务边界；
- flush、commit、唯一冲突、非唯一数据库错误和批次终止分类；
- provider 暂时失败、限流、授权失效、来源校验失败、消息合同错误、数据库暂时/不可恢复错误分类；
- Gmail history 顺序：来源校验 → provider history → detail → mapping → 幂等入库 → 成功后局部 cursor → batch commit；
- 空批次、缺失 message ID/外部 ID、重复通知和失败不推进虚假 cursor；
- revoked 账号在业务读取和 Gmail provider 调用前被拒绝；
- 入站重放不重复创建 InquiryEvent、InternalNotification 或人工状态。

## 2. 用户提供的测试证据

用户亲自执行定向跨功能测试：

```text
66 passed, 1 warning in 39.67s
```

用户随后执行后端全量回归：

```text
105 passed, 2 warnings in 41.41s
```

之后再次执行全量回归：

```text
105 passed, 2 warnings in 47.82s
```

warning：

- Starlette 当前 httpx 组合的弃用提示；
- Alembic 配置缺少 `path_separator` 的弃用提示。

测试覆盖最终数据、事件数量、通知数量、人工状态、provider 调用次数、授权撤销、重放幂等和 rollback，不只断言 HTTP 200。

## 3. 用户提供的目标环境证据

用户核对到：

```text
current: 0005_channel_external_account (head)
heads:   0005_channel_external_account (head)
```

容器内 migration 文件只有 `0001`–`0005`。因此：

- 本轮 Day 5 没有新增必须应用的 migration；
- 不能把旧文档提到的 `0006`/`0007`当作当前仓库或当前容器的待应用项；
- 当前证据只证明 revision/head 状态，不证明 PostgreSQL 唯一约束、CHECK 约束、行锁或跨进程并发已经专项验收。

## 4. 尚未完成的环境验收

- 目标 PostgreSQL 跨进程唯一冲突和锁/事务专项测试；
- 真实 Gmail OAuth、Pub/Sub、history cursor 恢复、真实限流和授权撤销；
- 真实 Outlook MCP/Graph/Entra 入站；
- 真实 WhatsApp Baileys 入站；
- 真实附件存储/下载；
- 真实出站发送；
- 最新工作区前端 bundle 在运行 frontend 容器中的部署核对。

这些事项不能由本地 SQLite/TestClient、fake provider 或 revision 查询代替。

## Day 6 渠道关联记录

- Gmail 真实入站验收记录见 [day6-gmail-verification.md](day6-gmail-verification.md)。
- WhatsApp 关联与真实入站待验收记录见 [day6-whatsapp-verification.md](day6-whatsapp-verification.md)。

这些记录只包含非敏感运行证据，不包含 token、secret、OAuth code、QR、auth state、消息正文或附件内容。

## 5. Day 5 状态

**Day 5 代码增量和本地隔离回归已完成。目标 PostgreSQL 并发/约束和真实 provider 仍是后置用户验收，不属于已完成证据。**
