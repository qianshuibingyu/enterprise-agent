# Enterprise Agent

面向企业内部运营与业务协作的 AI 工作台项目。需求、技术基线与待确认事项以 [PROJECT_SPEC.md](PROJECT_SPEC.md) 为准；阶段操作指南见 [plan/](plan/)，当前架构与范围材料见 [docs/](docs/)。

## 当前实现范围

- `backend/app/`：FastAPI 应用、内部用户认证、基于服务端会话的登录/登出、首次登录强制修改密码、首期对象授权、三渠道连接/入站路径、运营收件箱和内容处理 API。
- `backend/app/models/`、`backend/migrations/`：SQLAlchemy 用户/会话、渠道账号/授权、询盘/附件/内部通知、统一消息/消息附件、消息概要模型与 Alembic 迁移；工作区 head 为 `0012_message_overviews`，目标环境以用户最新核验为准。
- `backend/app/message_ingestion.py`：provider-specific/provider-neutral 消息 mapping、批量入站、账号/provider/external ID 幂等和附件 metadata 保存服务；已由用户运行相关回归测试。
- `backend/app/channels/`：provider 合同、能力目录、fake 测试 provider、入站 seam 和凭据引用安全边界；三渠道真实入站主链路已有 Day 6 证据，补充重放/撤销/附件/长期运行专项仍待验收。
- `backend/scripts/create_admin.py`：管理员初始化脚本。
- `backend/tests/`：健康检查、数据库配置、认证、迁移、首期对象授权和渠道连接中心测试。
- `frontend/`：Vue 3 + TypeScript + Vite 渠道账号“我的”页、运营收件箱、消息详情、原文预览/展开和人工状态操作；前端单元测试与生产构建已有 Day 8 证据，目标浏览器异常路径仍按 handoff 记录。
- `backend/app/document_processing.py`：provider-neutral、纯内存、确定性资料清洗与切片；不上传、不持久化、不生成 embedding、不执行检索。
- `backend/app/overview_service.py`、`backend/app/models/overview.py`：中文概要异步生成、状态/失败回退和概要持久化边界；生产目标环境自动生成仍待完整浏览器证据。
- `compose.yaml`、`backend/Dockerfile`、`frontend/Dockerfile`、`whatsapp-bridge/`：开发/验收服务和镜像配置。
- `PROJECT_SPEC.md`、`docs/`、`plan/`：项目范围、架构、交接记录及开发指南。

三渠道真实入站主链路、授权收件箱、原文回源代码、中文概要代码闭环和内存资料清洗/切片基础已有 Day 6–Day 8 证据。知识资料上传/持久化、embedding、pgvector、检索/RAG、回复建议、人工审批和真实出站仍未实现。代码、隔离测试、目标环境 schema 和镜像构建不自动代表所有生产/真实 provider 补充验收已完成。

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
