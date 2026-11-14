# 阶段一：账号生命周期、授权边界与部署验收

> 本文件独立记录阶段一验收，不属于 Day 1–3 认证 handoff。区分当前工作区测试、本机 Compose 数据库/服务证据和用户提供的黑盒 API 结果；不把未执行的管理操作或未覆盖角色写成通过。记录中不保存账号密码、cookie、token 或其他凭据。

## 1. 验收版本

```text
日期：2026-11-14
Git HEAD：944c90d3657586db25987fc65be59c952f90983c
tracked diff SHA-256：e72cbbb4a28bd79f56ee3d0ecc4395ff70c597836f167536c2511d14e6a07015
untracked files aggregate SHA-256：d602e22377670be3f2d968192d3230c7a05709c6a63f42a2d2226807c59f4081
```

该标识为当时工作区快照：HEAD 加 tracked diff 和未跟踪文件聚合哈希共同识别，不能只用 HEAD 代表未提交源码。

## 2. 后端与前端验证

- 在 `backend/` 执行全量 pytest：**401 passed, 3 warnings**。
- 在 `frontend/` 执行 `npm run test:unit`：**36 passed, 0 failed**。
- 在 `frontend/` 执行 `npm run build`：成功，Vite 生产构建完成。
- `git diff --check`（按 CRLF 文件使用 `core.whitespace=cr-at-eol`）通过。
- 后端测试包含 0025 的 NULL/空白部门实际回填测试、`unassigned` 隔离、经理叠加及账号身份变化时授权/会话清理覆盖。
- 测试 warning 为依赖/配置弃用提示，不影响本轮退出结果；warning 不等于无后续维护事项。

## 3. 0024/0025 迁移与数据库结果

迁移前先核对了 Docker context、目标 Compose 数据库 revision 和 0025 影响：

- Docker context：`default`。
- 迁移前 revision：`0023_users_full_name`。
- 迁移前共有 5 个账号：1 个 `department IS NULL`，无纯空白部门，无旧 `manager` 角色。
- 0024 影响：新增非空 `manager_overlay_enabled`（默认 false）；如存在历史 `manager` 角色则转为 `operations` 并开启 overlay。本库没有旧 `manager` 角色。
- 0025 影响：NULL 或 trim 后为空的部门回填为 `unassigned`，然后将 `department` 设为 NOT NULL。已确认 `unassigned` 是隔离桶，不授予隐式部门范围。
- 首次应用发现旧 revision 字符串超过 Alembic `version_num VARCHAR(32)`；将 revision ID 缩短为 `0025_department_identity`，重新预览 pending SQL 后执行成功。

迁移后只读核验：

```text
alembic_version = 0025_department_identity
users.department: NOT NULL
users.manager_overlay_enabled: NOT NULL
5 users; department NULL/blank count = 0
admin.department = unassigned
```

## 4. 本机 Compose 部署核验

- backend 和 frontend 使用当前工作区构建并重新启动；未重建 WhatsApp bridge。
- 容器内 `auth.py`、`auth_routes.py`、`authorization.py`、`business_routes.py`、`models/user.py` 的 SHA-256 与该验收工作区对应文件一致。
- backend `/health`、前端 `/`、首页引用的 JS/CSS 资源返回 HTTP 200。
- Compose 曾提示孤立容器 `enterprise-agent-api-1`；未删除或操作该容器。
- 这些结果证明本机 Compose 目标状态，不自动代表其他服务器或生产目标环境。

## 5. 用户提供的黑盒 HTTP/API 角色验收

用户确认采用黑盒 HTTP/API 验收，不依赖浏览器；测试过程中没有业务写操作，也没有修改授权。

| 账号 | 确认身份 | 可见询盘数 | 员工目录 | 管理员检查 | 登出 |
|---|---|---:|---:|---:|---:|
| admin | admin | 31 | 200 | 200 | 204 |
| user1 | staff | 11 | 403 | 403 | 204 |
| sales1 | sales | 2 | 403 | 403 | 204 |

补充结果：匿名访问 `/auth/me` 和 `/api/inquiries` 均返回 401；首页 `/`、`/inbox` 及首页 JS/CSS 返回 200。

本证据覆盖 admin、staff、sales 的身份、询盘可见范围、管理员端点隔离和登出。可见询盘数是该次测试数据下的观察值，不是固定业务期望值。

## 6. 覆盖边界与结论

本轮有通过证据的范围：后端全量测试、前端测试/构建、0024/0025 数据库迁移与回填、本机 Compose backend/frontend 与当前源码匹配、admin/staff/sales 黑盒读范围和管理员端点隔离。

本轮没有在目标环境实际变更或演练：

- 经理 overlay 开关的授权授予/撤销及生产会话行为；
- 员工授权授予/撤销、停用/恢复、角色/部门变更和渠道归属的目标环境写操作；
- engineering、production、procurement 账号的黑盒 API 登录与数据范围。

这些场景在自动化测试中的覆盖不等同于目标环境现场操作证据；不得将上述未演练项推定为生产行为已验收。依据已提供的阶段一范围，测试、构建、迁移、本机部署及 admin/staff/sales 黑盒隔离均有记录；如阶段一要求上述现场写操作或其他部门角色实测，则需追加证据后才能对该子范围签收。
