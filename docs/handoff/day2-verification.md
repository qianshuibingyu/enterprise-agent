# Day 2 数据库、认证与首期授权验证记录

> 本记录按配置、数据库、认证代码、本地测试和完整授权分别记录。历史用户输出只证明当次环境，不替代当前环境核验；不记录密码、token、Cookie 或完整连接串。

## 1. Day 2 目标与已确认方案

- 数据库目标为服务器 Docker Compose 管理的 PostgreSQL；数据库只由 backend 访问，凭据不进入 Git。
- 认证基础包括内部用户、服务端 session、密码哈希、CSRF/Origin 校验和受保护 API。
- 首期对象授权边界是：运营按本人授权渠道账号处理；sales 只读本人转交对象；内部分析只读；完整未来部门/经理/Agent/节点权限不在本阶段自动实现。

## 2. 已实现代码

当前工作区包含：

- `User`、session ORM 和认证 migration 基础；
- Argon2id 密码哈希；
- 登录、登出、改密、当前用户和管理员检查接口；
- HttpOnly/Secure/SameSite 会话 cookie 及 CSRF/Origin 检查；
- 首期对象授权查询和统一越权响应；
- 认证、数据库配置、首期授权和只读分析测试。

## 3. 用户提供的历史本地测试证据

用户曾在 backend 目录执行认证基础测试：

```text
15 passed, 1 warning
```

后续用户执行当前工作区后端全量回归：

```text
105 passed, 2 warnings
```

后者覆盖了当前认证、授权及 Day 3–Day 5 代码，但不是 Day 2 当日的专属结果，也不证明完整未来 RBAC 或目标 PostgreSQL schema。

## 4. 数据库与 migration 证据

早期 Day 2/Day 3 记录显示，目标数据库曾未发现用户/会话表且未有应用 revision。用户后续在当前运行环境核对到：

```text
current: 0005_channel_external_account (head)
heads:   0005_channel_external_account (head)
```

并确认运行 backend 容器内 migration 文件为 `0001`–`0005`。

这说明后续目标环境已有 `0005` revision 证据，但不能把它倒写成 Day 2 当日已完成，也没有提供 Day 2 所需的用户/会话表字段和约束专项查询。

## 5. Day 2 未完成项

以下不应标为 Day 2 已完成：

- 管理员创建、停用、重置、解封完整 API；
- 连续失败锁定及管理员恢复；
- 完整部门/经理/客户/资料/Agent/节点 RBAC；
- 目标 PostgreSQL 用户/session schema 的 Day 2 专项查询；
- PostgreSQL session 过期、并发和生产代理 HTTPS 行为；
- 完整生产部署、备份恢复和真实 provider。

## 6. Day 2 状态

**Day 2 认证/session 基础和首期对象授权代码已实现，并有本地测试证据；完整数据库/schema、管理员生命周期和未来完整 RBAC 未完成验收。**

后续 `0005` revision 记录属于 Day 3/Day 5 环境状态，不改变上述分层结论。
