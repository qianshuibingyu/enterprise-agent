# Enterprise Agent

面向企业内部运营与业务协作的 AI 工作台项目。需求、技术基线与待确认事项以 [PROJECT_SPEC.md](PROJECT_SPEC.md) 为准；阶段操作指南见 [plan/](plan/)，当前架构与范围材料见 [docs/](docs/)。

## 当前实现范围

- `backend/app/`：FastAPI 应用、内部用户认证、基于服务端会话的登录/登出、首次登录强制修改密码、首期对象授权和 provider-neutral 渠道连接中心 API。
- `backend/app/models/`、`backend/migrations/`：SQLAlchemy 用户/会话、渠道账号/授权、询盘/附件/内部通知、统一消息/消息附件模型与 Alembic 迁移（当前 head 为 `0003_messages`）。
- `backend/app/message_ingestion.py`：provider-neutral 消息 mapping、fake/provider batch 接入、账号/provider/external ID 幂等和附件 metadata 保存服务；已由用户运行相关回归测试。
- `backend/app/channels/`：provider 合同、能力目录、fake 测试 provider、入站 seam 和凭据引用安全边界；真实 provider 尚未配置。
- `backend/scripts/create_admin.py`：管理员初始化脚本。
- `backend/tests/`：健康检查、数据库配置、认证、迁移、首期对象授权和渠道连接中心测试。
- `frontend/`：Vue 3 + TypeScript + Vite 渠道连接中心最小页面和 API client；已验证构建，尚未完成生产部署/真实 API 联调。
- `compose.yaml`、`backend/Dockerfile`：开发环境服务和后端镜像配置。
- `PROJECT_SPEC.md`、`docs/`、`plan/`：项目范围、架构、交接记录及开发指南。

渠道连接中心的 provider-neutral 内部目录、账号状态 API、fake 状态测试、最小前端页面和三渠道入站 seam 已实现并由用户实际测试验证；Gmail/Outlook/WhatsApp 真实 adapter、授权与真实消息处理、运营收件箱及完整业务工作流尚未实现。设计资料、代码测试和前端构建成功不代表数据库迁移已在目标环境应用、真实渠道已连接或生产部署已验收。当前 Day 3 状态为“已实现，待真实环境验收”，不是整体完成。

## 开发环境

- Python 后端依赖清单：`backend/requirements.txt`。
- 前端依赖与锁文件：`frontend/package.json`、`frontend/package-lock.json`。
- 本地环境文件使用 `.env`，不得提交；可参考 `.env.example` 配置。
- `.venv/`、`node_modules/`、缓存和 `frontend/dist/` 均为本地产物，不属于版本控制内容。

## 数据库迁移

生产 Compose 部署中，PostgreSQL 只在 Compose 网络内提供给 `backend` 服务，数据库主机名为 `db`。因此应从运行中的 backend 容器执行迁移：

```bash
docker compose --env-file .env exec -T backend python -m alembic upgrade head
```

不要在宿主机上以 `DB_HOST=db` 直接连接数据库。开发机直接运行 Alembic 时，后端会读取仓库根目录 `.env` 中尚未导出的变量；已导出的环境变量优先。若仍提示缺少 `POSTGRES_USER`、`POSTGRES_PASSWORD` 或 `POSTGRES_DB`，请在 `.env` 中配置对应的非空值，且不要把它们输出到终端或提交到版本库。

请按对应阶段指南运行并记录测试、迁移及部署验证结果；历史测试或文档计划不能替代当前运行证据。
