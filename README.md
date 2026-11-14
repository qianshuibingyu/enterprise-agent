# Enterprise Agent

面向企业内部运营与业务协作的 AI 工作台项目。需求、技术基线与待确认事项以 [PROJECT_SPEC.md](PROJECT_SPEC.md) 为准；阶段操作指南见 [plan/](plan/)，当前架构与范围材料见 [docs/](docs/)。

## 当前实现范围

- `backend/app/`：FastAPI 应用、内部用户认证、基于服务端会话的登录/登出、首次登录强制修改密码、首期对象授权、三渠道连接/入站路径、运营收件箱和内容处理 API。
- `backend/app/models/`、`backend/migrations/`：SQLAlchemy 用户/会话、渠道账号/授权、询盘/附件/内部通知、统一消息/消息附件、消息概要、询盘—消息关联及操作日志模型；当前工作区 Alembic head 为 `0025_department_identity`。本机 Compose 数据库已核验迁移至该 revision（2026-11-14）；其他目标环境须另行核验。
- `backend/app/message_ingestion.py`、`contact_identity.py`、`business_service.py`：provider-specific/provider-neutral 入站、身份规范化、消息幂等、询盘归链/人工关联和人工状态转换服务。当前工作区代码含 Gmail/Outlook/WhatsApp 入站与回源路径；本机全量回归证据见[阶段一验收补记](docs/handoff/stage1-account-authorization-acceptance.md)，不替代其他目标环境验收。
- `backend/app/channels/`：provider 合同、能力目录、fake 测试 provider、入站 seam 和凭据引用安全边界；三渠道真实入站主链路已有 Day 6 证据，补充重放/撤销/附件/长期运行专项仍待验收。
- `backend/scripts/create_admin.py`：管理员初始化脚本。
- `backend/tests/`：健康检查、认证/授权、消息入站与回源、询盘—消息关联、身份规范化、内部只读分析、概要、渠道和迁移测试；2026-11-14 当前工作区全量后端测试为 401 passed（3 warnings），见[阶段一验收补记](docs/handoff/stage1-account-authorization-acceptance.md)。
- `frontend/`：Vue 3 + TypeScript + Vite 渠道账号“我的”页、运营收件箱、消息详情、原文预览/展开和人工状态操作；2026-11-14 当前工作区前端单测 36 passed、生产构建成功；本机 Compose 首页及关键静态资源 HTTP 200。
- `backend/app/document_processing.py`：provider-neutral、纯内存、确定性资料清洗与切片；不上传、不持久化、不生成 embedding、不执行检索。
- `backend/app/overview_service.py`、`backend/app/models/overview.py`：中文概要异步生成、状态/失败回退和概要持久化边界；生产目标环境自动生成仍待完整浏览器证据。
- `compose.yaml`、`backend/Dockerfile`、`frontend/Dockerfile`、`whatsapp-bridge/`：开发/验收服务和镜像配置。
- `PROJECT_SPEC.md`、`docs/`、`plan/`：项目范围、架构、交接记录及开发指南。

三渠道真实入站主链路及 Day 8 内容处理曾有交接记录；当前工作区另有询盘—消息关联/人工确认、业务类型、官网表单隔离、操作日志、消息列表索引，以及 bridge 持久化加密消息归档等增量。阶段一账号生命周期与权限相关代码、全量测试、前端测试/构建、本机 Compose 迁移和部署已于 2026-11-14 验证，详见[阶段一验收补记](docs/handoff/stage1-account-authorization-acceptance.md)。知识资料上传/持久化、embedding、pgvector、检索/RAG、回复建议、审批发送仍未形成完整闭环；真实 provider 和生产状态按各 handoff 的证据边界判断。

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
