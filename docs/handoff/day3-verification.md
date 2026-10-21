# Day 2 数据库、认证与授权验证记录

> 保留原有文档中的 Day 1 历史记录；本 Day 2 节记录数据库准备、应用连接、迁移、认证/RBAC 的证据与缺项。区分用户提供的服务器输出和本地工作区实际检查结果，不记录真实凭据。

## 9. 数据库与认证/授权决策和验证状态

> 本节区分用户确认的方案、当前工作区代码状态及实际运行证据。此前用户提供的服务器输出是该服务器当时的记录，不代表当前本地工作区或服务器当前状态。不要记录真实密码或连接串。

### 9.1 数据库方案决策

- **已确认**：当前目标服务器和后续项目部署目标均为该服务器；数据库采用 Docker Compose 管理 PostgreSQL。用户确认服务名 `db`、镜像 `postgres:16`、命名卷持久化、用户名/数据库名 `enterprise_agent`，并要求数据库只由 backend 访问。密码使用服务器 `.env`，不进入 Git。
- **服务器历史证据（用户提供，2026-10-20）**：Compose 配置成功解析；`db` 容器显示 healthy；`docker compose exec db pg_isready` 输出 `accepting connections`；backend 通过 SQLAlchemy engine 执行 `SELECT 1` 输出 `1`。这证明当时数据库就绪与应用级连接，不能证明现在状态或网络隔离已落实。
- **数据安全**：用户曾在对话中粘贴含数据库明文密码的 `docker compose config` 输出；此前已提醒轮换。此处不记录秘密。命名卷不等于备份；此前用户提供 `docker compose down -v` 输出显示删除了命名卷并重建，新卷开始时为空。

### 9.2 已确认的认证/授权设计

用户逐项确认的认证和角色/资源矩阵已记录于 [PROJECT_SPEC.md §3.1–§3.2](../../PROJECT_SPEC.md#31-已确认的授权设计尚非实现) 及 [architecture.md §5.1](../architecture.md#51-已确认的认证与授权矩阵设计)。主要约束：系统只供已登录内部员工使用；授权在后端执行且必须先于对象读取；跨权限请求统一返回“没有权限访问”；AI 以发起用户权限为限；修改/删除/改派授权通过后需确认；未决的被选跨部门协作者内部排班/记录可见性仍不授予。

本次实施选择（在已确认方向上补充的首版参数）：

- 登录标识为唯一员工用户名；管理员通过显式 CLI 交互初始化首个管理员，不将默认凭据写入源码或迁移。
- 密码采用 Argon2id；Unicode 长度为 6–15 个字符。具体 Argon2id 成本参数需在目标服务器资源上压测后定值。
- Cookie 承载 PostgreSQL 服务端 opaque session；数据库仅存 session token 摘要及 CSRF token 摘要，绝对寿命 8 小时，不滑动续期。Cookie 属性为 HttpOnly、Secure、SameSite=Lax、Path=/。
- CSRF 采用同步器 token + Origin 校验。Origin 必须通过 `AUTH_ORIGIN` 显式配置为规范 HTTPS 源；缺失/非 HTTPS 时失败关闭。
- 首次登录必须改密；改密前只开放改密和登出。管理员账号管理 API、重置/解封以及 5 次连续失败锁定不在本轮实现范围，仍未实现。
- 当前轮接口草稿：`GET /auth/csrf`、`POST /auth/login`、`POST /auth/logout`、`PATCH /auth/password`、`GET /auth/me`、`GET /auth/admin-check`。暂不实现前端登录页。
- 用户要求按自动化测试及必要手动验证分层记录数据库准备、应用连接、迁移、认证与授权的正反链路，并将此文件作为 Day 2 handoff；本节遵循该要求，只记录当前可证事实与阻塞项。

### 9.3 当前本地工作区实现与验证（2026-10-20）

- **代码已写入本地工作区**：包含 user/session ORM、Alembic revision 文件、Argon2id auth/session/CSRF 组件、登录/登出/改密、`/me`、只读管理员检查 API、管理员初始化 CLI 和认证测试。当前未运行数据库迁移、未连接部署 PostgreSQL、未启动 Compose 服务，也未创建管理员账号。
- **依赖安装（用户提供，成功）**：用户在项目根目录的 `.venv` 中执行 `python -m pip install 'argon2-cffi>=23.1,<26'`，从配置的阿里云 PyPI 镜像安装成功；输出版本为 `argon2-cffi 25.1.0`、`argon2-cffi-bindings 26.1.0`、`cffi 2.1.1`、`pycparser 3.11`。用户执行 `python -c "from argon2 import PasswordHasher; print('argon2 available')"`，输出 `argon2 available`。未记录任何凭据。
- **第一次 pytest（用户提供，未执行测试）**：从项目根目录运行 `python -m pytest tests -q` 返回 `ERROR: file or directory not found: tests`；当时工作目录不正确。
- **本地自动化测试（用户提供，成功）**：在 `/root/enterprise-agent/backend` 目录运行 `python -m pytest tests -q`，输出 **15 passed, 1 warning in 6.79s**。警告来自 Starlette：当前通过 `starlette.testclient` 使用 `httpx` 已弃用，建议安装 `httpx2`。本轮测试包括健康检查、数据库配置和认证 API 的 SQLite/TestClient 路径。
- **测试覆盖边界**：这些是本地自动化测试结果，不是部署服务器的 API/数据库验证。SQLite 测试未连接 PostgreSQL；未应用 Alembic migration，未验证 PostgreSQL schema、8 小时过期计时、真实 HTTPS 代理/Origin、目标服务器 Argon2 成本和并发行为。成功的 API 测试不代表完整客户/部门/渠道权限矩阵已实现。
- **静态检查**：工作区源码 compileall 与 `git diff --check` 曾通过；语法/格式检查不等于运行验收。
- **尚未执行/暂缓**：迁移检查/应用、PostgreSQL schema 检查、管理员 CLI 实际建号、服务器部署验证、管理员创建/停用/重置/解封 API、连续 5 次失败锁定及管理员恢复，以及完整业务 RBAC。不能将这些项目记为已完成。
- **未实现/暂缓**：管理员创建/停用/重置/解封 API；连续 5 次失败后锁定及管理员恢复；全角色/部门/渠道/客户/资料/经理/Agent/节点完整授权。只读 `/auth/admin-check` 仅验证最小管理员区分，不代表完整 RBAC 已实现。

### 9.4 历史数据库迁移证据（用户提供）

服务器当时的 `/app/migrations` 只有 `env.py`，没有版本迁移文件；`alembic upgrade head` 退出 0，但 `alembic current` 无 revision 输出，`alembic_version` 查询为 0 行。用户明确当时没有身份表和权限表。新建 revision 草稿尚未应用，不应将上述历史记录覆盖成迁移已完成。

---

## 10. Day 3 步骤 1：数据库与应用连接本轮核验（用户提供，2026-10-21）

> 以下为用户粘贴的服务器终端记录。本节只整理这些实际输出；不代表本地工作区的运行状态。原始命令尝试中的错误也予以保留，避免把排障过程误写成一次性成功。未记录凭据。

### 10.1 Compose 与 PostgreSQL 状态

- `AUTH_ORIGIN=https://localhost docker compose --env-file .env config --quiet`：成功退出，无错误输出；证明 Compose 配置可解析，不证明服务当前健康或迁移已应用。
- `AUTH_ORIGIN=https://localhost docker compose --env-file .env ps --all`：`backend` 为 `Up 19 hours`，`db` 为 `Up 19 hours (healthy)`，映射 `127.0.0.1:8000->8000/tcp`；旧 `api` 容器为 `Exited (0) 2 days ago`。这是当时的容器状态，不应将已退出的 `api` 记为运行中。
- `pg_isready`（在 `db` 容器内，使用容器的 `POSTGRES_USER`/`POSTGRES_DB`）输出 `/var/run/postgresql:5432 - accepting connections`，证明 PostgreSQL 当时接受连接。

### 10.2 schema 与 Alembic

- 首次通过宿主 Shell 展开 `$POSTGRES_USER`/`$POSTGRES_DB` 的 `psql` 尝试报错 `FATAL: role "root" does not exist`：变量在宿主机展开，实际连接用户名变成 `root`，该次不能证明目标数据库查询结果。
- 后续不带 `AUTH_ORIGIN` 的 Compose 命令失败：`AUTH_ORIGIN` 必须设置；之后命令显式设置 `AUTH_ORIGIN=https://localhost`。
- `information_schema.columns` 查询在 `public` schema、`users`/`user_sessions` 两表范围内返回 **0 rows**（重复执行两次，均为 0 行）。因此该次连接的数据库中这两张表尚未发现；该查询不证明其他 schema 或其他数据库的情况。
- `AUTH_ORIGIN=https://localhost docker compose --env-file .env exec -T backend alembic current` 无 revision 输出。结合上述表查询，用户/会话迁移在该次检查时未见应用证据；命令无输出本身不能替代版本表检查。
- 曾尝试将 SQL 语句放入 `psql -c`，但因 shell 引号/SQL 不完整而失败或中断；这些失败没有数据库结果，不作为 schema 证据。

### 10.3 FastAPI 使用的应用级数据库连接

- `python -c` 第一次因输入拼写 `form sqlalchemy import text` 得到 `SyntaxError`，未执行连接。
- 更正后，在 `backend` 容器内通过 `from sqlalchemy import text; from app.database import engine` 执行 `SELECT 1`，输出 `1`。这证明该次 FastAPI 配置所用 SQLAlchemy engine 可连接并执行只读查询；不证明迁移、身份表或授权已完成。

### 10.4 本轮结论与遗留项

- **通过（仅限本轮证据）**：Compose 配置解析、PostgreSQL ready、backend SQLAlchemy engine 的只读 `SELECT 1`。
- **未通过/未完成**：`users`、`user_sessions` 表在所查 `public` schema 中未发现；Alembic current 无 revision 输出。仍须确认目标库后审阅并应用迁移，再查询 revision、表结构、索引及约束。
- **容器注意事项**：`api` 旧容器已退出；当前运行服务为 `backend` 和 `db`。本次没有提供 API 请求结果。
- **安全注意**：不要将 `.env`、密码或连接串复制到交接记录。后续 Compose 命令需在 Compose 插值环境中显式提供 `AUTH_ORIGIN`，数据库变量应在容器内引用，避免被宿主 Shell 展开成错误用户。
