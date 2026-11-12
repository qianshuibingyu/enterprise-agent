# Day 1 最小骨架与环境验证记录

> 本记录只整理用户实际提供的命令结果。文件存在、历史记录或计划内容不等于本轮验证通过；未执行项目明确标为待验证。不记录凭据、连接串或客户敏感内容。

## 1. 已有代码与范围文档

- 最小 FastAPI 后端入口、`/health`、Python 依赖、Dockerfile、Compose 配置和 Vue/Vite 前端入口已写入工作区。
- 范围材料已保存为 [day1-scope.md](day1-scope.md) 和 [day1-unknowns.md](day1-unknowns.md)。
- [day1-scope.md](day1-scope.md) 当前仍保留“草稿/待确认”标记，因此不能把范围确认写成完全闭环。
- [architecture.md](../architecture.md) 是逻辑架构基线，不是业务实现或生产部署证明。

## 2. 用户提供的服务器检查

详见 [server-checklist.md](server-checklist.md)。已记录的目标服务器事实：

- Alibaba Cloud Linux 3.2104 系列（U13.4）；
- 2 vCPU；
- 检查时内存约 1.8 GiB；
- 根文件系统约 40 GiB、可用约 23 GiB；
- Docker 26.1.3；
- Docker Compose v2.27.0；
- 当次检查没有启用 Swap。

这些结果只证明当次服务器只读检查，不证明当前服务、数据库或生产部署状态。

## 3. 用户提供的最小应用/测试证据

- 用户曾在 `backend/` 执行认证/健康相关测试，结果为 `15 passed, 1 warning`；该结果属于当时版本的本地 SQLite/TestClient 测试。
- 用户曾提供独立 Docker 容器启动并请求 `/health` 返回 HTTP 200 的记录；该记录未证明数据库、业务路由或生产部署。
- 用户曾提供前端生产构建成功记录；该记录只证明当次构建，不证明浏览器、最新 bundle 或生产反向代理已验收。

## 4. Day 1 未闭环项

- 未有一份与当前工作区完全对应的 Day 1 全步骤新鲜验证输出，尤其是本地 Uvicorn、Compose 配置/启动/停止和容器 `/health` 的同次记录；
- [day1-scope.md](day1-scope.md) 仍是草稿，待用户最终确认；
- 服务器检查记录不包含 Nginx、HTTPS、备份恢复或真实渠道验收；这些也不属于 Day 1 最小骨架的已完成证明。

## 5. 分层结论

**Day 1 状态：最小骨架和部分环境检查已完成；范围确认及完整 Day 1 验证交接仍不完整。**

不能把 Day 1 写成整个项目完成，也不能由 `/health` 或历史 pytest 结果推断数据库、认证、业务页面或真实渠道已完成。
