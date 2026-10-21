# Enterprise Agent

面向企业内部运营与业务协作的 AI 工作台项目。需求、技术基线与待确认事项以 [PROJECT_SPEC.md](PROJECT_SPEC.md) 为准；阶段操作指南见 [plan/](plan/)，当前架构与范围材料见 [docs/](docs/)。

## 当前实现范围

- `backend/app/`：FastAPI 应用、内部用户认证、基于服务端会话的登录/登出、首次登录强制修改密码及管理员检查。
- `backend/app/models/`、`backend/migrations/`：SQLAlchemy 用户/会话模型与 Alembic 初始迁移。
- `backend/scripts/create_admin.py`：管理员初始化脚本。
- `backend/tests/`：健康检查、数据库配置及认证测试。
- `frontend/`：Vue 3 + TypeScript + Vite 最小前端入口，尚无业务工作台页面。
- `compose.yaml`、`backend/Dockerfile`：开发环境服务和后端镜像配置。
- `PROJECT_SPEC.md`、`docs/`、`plan/`：项目范围、架构、交接记录及开发指南。

渠道连接中心、Gmail/Outlook/WhatsApp 实际授权与消息处理、运营收件箱及业务工作流尚未实现。设计资料与代码文件存在不代表数据库迁移已在目标环境应用、真实渠道已连接或生产部署已验收。

## 开发环境

- Python 后端依赖清单：`backend/requirements.txt`。
- 前端依赖与锁文件：`frontend/package.json`、`frontend/package-lock.json`。
- 本地环境文件使用 `.env`，不得提交；可参考 `.env.example` 配置。
- `.venv/`、`node_modules/`、缓存和 `frontend/dist/` 均为本地产物，不属于版本控制内容。

请按对应阶段指南运行并记录测试、迁移及部署验证结果；历史测试或文档计划不能替代当前运行证据。