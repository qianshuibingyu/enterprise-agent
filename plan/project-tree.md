# 当前项目目录架构说明

> 本文记录当前工作区结构与状态。文件/目录存在不代表对应功能已实现或验证通过。

## 1. 当前目录树

```text
enterprise-agent/
├─ PROJECT_SPEC.md
├─ README.md
├─ .env.example
├─ compose.yaml
├─ backend/
│  ├─ requirements.txt
│  └─ app/
│     └─ main.py
├─ frontend/
│  ├─ index.html
│  ├─ package.json
│  └─ src/
│     └─ main.ts
├─ docs/
│  ├─ architecture.md
│  └─ handoff/
│     ├─ day1-scope.md
│     └─ day1-unknowns.md
└─ plan/
   ├─ day1.md
   ├─ day2.md
   ├─ day3.md
   └─ project-tree.md
```

本地可能另有 `.venv/` Python 虚拟环境；它不是项目源码，不纳入上述共享目录结构，按本地需要保留或重建。

## 2. 当前最小骨架

| 路径 | 当前状态 | 不代表 |
|---|---|---|
| `backend/app/main.py` | FastAPI 应用入口及 `GET /health`，返回 `{"status":"ok"}` | 数据库/队列已连接或其他业务功能已实现 |
| `frontend/index.html` | Vite 页面入口 | 前端已启动或构建 |
| `frontend/package.json` | Vue、TypeScript、Vite 依赖和开发/构建脚本定义 | 依赖已安装或构建已通过 |
| `frontend/src/main.ts` | Vue 占位页入口 | 已有工作台或 API 集成 |
| `backend/requirements.txt` | FastAPI 与 Uvicorn 后端运行依赖 | 依赖已安装或服务已启动 |
| `compose.yaml` | 本次保持原样（空配置占位） | Compose 有有效服务定义或容器已启动 |
| `.env.example` | 本次保持原样（空文件） | 环境变量已配置或包含凭据 |

Day 1 范围保留用户指定的最小骨架、`backend/requirements.txt` 和必要父目录；`.env.example` 与 `compose.yaml` 保持原样。当前没有预建业务模块、迁移、测试、部署、前端视图等目录。

## 3. 保留的文档

- `PROJECT_SPEC.md`：项目需求、范围和技术基线，不是实现证明。
- `docs/architecture.md`：逻辑架构与决策状态，不等于部署拓扑或代码实现。
- `docs/handoff/day1-scope.md`：Day 1 范围记录/草稿；需按指南核对状态。
- `docs/handoff/day1-unknowns.md`：待确认事项记录。
- `plan/day1.md`、`plan/day2.md`、`plan/day3.md`：阶段操作指南，不是完成报告。
- `plan/project-tree.md`：当前结构说明。
- `README.md`：项目入口说明。

Day 1 的 `docs/handoff/server-checklist.md` 与 `docs/handoff/day1-verification.md`，以及后续 Day 2/3 验证记录，均在相应检查/开发阶段实际执行时创建；不要提前建空文件。

## 4. 后续目录按阶段创建

不要一次性创建完整项目树。进入相应阶段、确认实现需要后再创建最小必要结构，例如：

- Day 2 数据库与身份授权阶段：按实际采用方案创建配置、数据库/模型、迁移及测试所需目录，并创建 `docs/handoff/day2-verification.md` 记录实际结果。
- Day 3 邮箱接入阶段：按适配器、消息持久化、任务/调度及测试的实际边界增建目录，并创建 `docs/handoff/day3-verification.md`。
- 后续部署阶段：确认运行方式后再建立部署/Nginx 等配置目录。

以上是阶段化说明，不是要求现在创建这些候选路径；具体文件名和职责须以对应阶段的方案与实际实现为准。

## 5. 当前限制

- `backend/app/main.py` 已定义 FastAPI `GET /health`，但尚未运行验证。当前保留的 `.venv/` 为 Python 3.6，无法安装 `backend/requirements.txt` 中 FastAPI ≥0.115 的依赖，故本地启动验证受阻。
- 前端入口和依赖配置已建立为最小占位，需实际安装依赖并运行开发/构建验证；当前没有单独 TypeScript 配置文件，因此尚未配置独立的类型检查。
- `compose.yaml` 为空。
- 当前没有证据证明 PostgreSQL、异步任务、渠道、Agent/RAG 或生产部署已实现或验证。
