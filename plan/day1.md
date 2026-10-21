# Day 1 执行指南：由你亲手完成

> 本文是操作指南，不代表 Day 1 已完成。请按顺序手动执行。Claude 不替你运行下面的 Prompt、终端命令或服务器检查；你每完成一步，再把结果或卡点发回来，我们一起判断是否通过。

## 项目约束与来源

- **用户明确说明**：项目在服务器上部署，但公司局域网内使用，不面临高并发；服务器为 Alibaba Cloud Linux 3.2104 LTS、2 vCPU、2 GiB RAM。
- **项目说明书基线**：以 `PROJECT_SPEC.md` 为本项目功能、技术和边界依据。
- **建议**：Day 1 先由你亲手完成范围梳理和最小开发骨架，不实施业务功能；低并发不代表可以省略权限、Webhook 校验和备份。
- **待我确认**：未决事项不能由建议替代你的决定。
- **P2 表述**：合同 OCR、生产/库存/物流集成和额外渠道属于原基线 P2；是否纳入本次范围待确认。不得写成“本次已纳入”或“本次已排除”。

## 先学会：如何从需求推导出一个好问题

本手册中的 Prompt 是推导结果，不是要背诵的句式。遇到新任务时，先自己回答以下问题，再决定要不要请 AI 帮忙：

1. **要解决什么问题？** 用一句话描述结果，不先指定工具或实现方式。
2. **我知道什么、还不知道什么？** 分别找出项目说明、用户已确认内容、当前代码/环境和缺失证据。
3. **猜错会造成什么后果？** 影响范围、安全边界和可逆性决定应先分析、先提问还是可以动手。
4. **这一步请 AI 做什么？** 例如整理、解释、提出选项或检查证据；决定权、实现和真实验证仍由你负责。
5. **怎么判断结果可靠？** 写出能观察到的证据，以及哪些相似证据不能证明目标。

可以把它记成：**问题 → 事实/未知 → 风险 → AI 的任务边界 → 用户行动 → 验收证据**。不是每个 Prompt 都要把六项写成标题，也不需要反复重复所有规则；只把会影响本次回答的依据和约束交代清楚。

### 用步骤 1 示范推导，而不是背 Prompt

- 项目说明书里既有原始基线，也有待确认和 P2 内容，因此风险是 AI 把建议写成用户决定；Prompt 才要求标出状态、章节来源和未决项。
- 这一步的目标是让你审阅范围草稿，而不是生成最终规范，所以要求只在对话输出、不修改文件。
- 验收不是“AI 说整理好了”，而是你能逐项回到来源核对，且未决事项没有被写成已定。

之后每一步都可以照这个方式反推 Prompt：每个限制都要能回答“它防止什么误判/越界”，每个输出都要能回答“我会如何核对”。如果说不出理由，就重新判断该要求是否必要。

## 今天的完成标准

今天不是完成整个项目。Day 1 应留下以下产物：

1. `docs/handoff/day1-scope.md`：核对并确认后的范围文档，包含目标、非目标、范围边界及来源状态。
2. `docs/handoff/day1-unknowns.md`：仅保留未决定事项的待确认问题表；未决定项必须标为“待我确认”，建议必须标为“建议（非决定）”。
3. `docs/architecture.md`：项目逻辑架构基线，说明已确认的组件边界、技术基线、关键数据流及未决设计。当前文档已存在，需按本指南核对/更新；文档基线不代表代码已经实现。
4. 项目最小骨架：你亲手创建并理解的目录，以及最小前后端运行文件。
5. `docs/handoff/server-checklist.md`：目标服务器检查的实际结果；未检查的项目标为待执行或阻塞。
6. `docs/handoff/day1-verification.md`：FastAPI 本地启动、API 测试、前端、Dockerfile 与 Compose 构建/运行、容器 `/health` 请求的实际验证结果和未解决问题。

步骤 1、2 的 AI 对话输出只是草稿；经你核对后，分别保存到范围与待确认记录。架构文档应由已确认范围和技术基线推导，并明确未决项；不能把逻辑图当成实现证明。项目目录、最小运行骨架和检查/验证记录按后续步骤由你亲自创建。未执行的检查不能记为通过。

当前文档约定：`plan/` 保存各阶段操作指南；`docs/` 保存架构基线，`docs/handoff/` 保存你在对应阶段亲手填写的交接记录。保留现有文档，不因整理代码骨架而清除；尚未产生的检查/验证记录只在执行相应步骤时创建。Day 1 代码骨架包括现有 `backend/app/main.py`、`backend/requirements.txt`、前端入口文件，以及本阶段补全的 `backend/Dockerfile` 和最小测试材料 `backend/requirements-dev.txt`、`backend/tests/test_health.py`、`backend/.dockerignore`。其中 `backend/Dockerfile` 当前是不完整的占位内容，`compose.yaml` 当前为空，Day 1 按本指南新增单服务 Compose 配置。不要提前创建 Day 2/3 的业务模块目录或增加数据库、Redis、Nginx 等服务。

---



## 步骤 1：你自己确认 Day 1 范围



### 这一步要消除的不确定性是什么

本步骤要确定 Day 1 的目标、哪些只是原始基线、哪些仍待你决定；主要风险是把建议或 P2 项目误写为已决定。

### prompt 是什么

将下面内容复制到你使用的 AI 对话中。请让它只产出文档草稿，不要让它修改文件：

```text
请阅读项目根目录 PROJECT_SPEC.md，帮我整理一份 Day 1 范围草稿，先在对话中输出，不要创建或修改任何文件。
严格按“用户明确确认 / 原始基线 / 建议 / 待我确认”标注每项，并附 PROJECT_SPEC.md 章节来源。
内容包含目标、非目标、范围边界。特别写明：合同 OCR、生产/库存/物流集成和额外渠道属于原基线 P2；是否纳入本次范围待我确认。不要补造验收标准、流程、权限、时间安排或技术选型。
最后列出需要我逐项确认的内容。
```



### 为什么这么做：从来源和误判风险推导

项目说明书要求把未确认内容单独列出。Prompt 中要求分类并附章节来源，是为了让你能够回到依据核对；先只输出草稿，是因为范围草稿还需要你决定哪些内容可确认；禁止替你决定，是为了避免将原始基线或 AI 建议误写成用户决定。

### 验收时我看什么

- **一个动作**：你阅读 AI 输出，按《项目说明书》核对来源和状态。
- **一个判断标准**：每条都能归入四种状态之一；P2 和未决事项没有被写成你已决定。



### 产出与保存位置

- 对话中的范围草稿经你核对后，保存为 `docs/handoff/day1-scope.md`。
- 草稿不是最终结论；未确认事项继续标注“待我确认”，不得写成已决定。



### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
你确认或修改的要点：

---



## 步骤 2：你自己排序待确认问题



### 这一步要消除的不确定性是什么

哪些决定会影响整体架构、渠道接入、数据权限和验收，哪些可以之后再决定。

### prompt 是什么

```text
根据 PROJECT_SPEC.md 第 14 节，帮我在对话中整理待确认问题，不要修改文件。
每项列出：排序、问题、影响范围（高/中/低）、不确定程度（高/中/低）、候选答案 A/B、默认建议（明确写“建议，非决定”）、选错后的后果、当前状态（未确认项统一写“待我确认”）。按“影响范围 × 不确定程度”排序。
覆盖渠道身份与授权、邮箱供应商/授权、抓取日历/时区、角色与资料权限、工程生产范围、外网搜索、报表、异常负责人、自动发送条件及 P2 范围。不要替我选择答案。
```



### 为什么这么做：从决定后果推导排序问题

渠道授权、时间规则和权限边界可能改变接口或数据结构；报表指标等事项也会影响验收。让 AI 同时标影响、不确定度和选错后果，能帮助你判断哪些必须先确认、哪些可留到对应功能阶段。候选项/建议用于比较，不意味着 AI 可以替你选择。

### 验收时我看什么

- **一个动作**：按顺序阅读问题表。
- **一个判断标准**：每项有候选项、影响、不确定度、后果和状态；所有未决定的状态写“待我确认”，默认建议没有变成决定。
- 若不能排序或问题遗漏：这一步猜错了。替代方案是回到 `PROJECT_SPEC.md` 第 14 节逐项抄入，再由你自行排序。



### 产出与保存位置

- 经你核对的问题表保存为 `docs/handoff/day1-unknowns.md`。
- 未决定的问题保持“待我确认”；默认建议不能写成你的决定。



### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
你确认或修改的要点：

---



## 步骤 3：推导架构基线并写入架构文档



### 这一步要解决什么问题

范围和待确认事项已核对后，需要把“系统有哪些边界、组件负责什么、哪些关系尚未决定”表达成可供后续开发讨论的架构基线。架构文档不是代码实现说明，也不等于所有细节已定。

### 如何从证据推导要问什么

- **需求**：PROJECT_SPEC 给出内部工作台、FastAPI、Vue、PostgreSQL、Agent/RAG、渠道及部署等目标。
- **已确认决策**：使用 Day 1 范围记录中本轮明确确认的渠道、流程和安全边界。
- **未知**：从待确认清单找出未决定的调用接口、部署拓扑、权限细节和外部授权条件；不要用常见架构习惯补答案。
- **风险**：图若把目标组件画成已部署，或把两个组件画成固定调用关系，会误导后续实现；要用状态标注区分基线、待设计和待验证。
- **输出与验证**：产出逻辑层次、职责和有依据的关系；用来源链接检查每条决定，用“实现/验证状态”防止架构图被误当成运行证据。

这些依据决定 Prompt 应要求：整理逻辑基线、标来源状态、指出缺失决策、避免臆造部署和调用细节。若你无法说明图中一条边来自哪项需求/决定，应把它改成待设计或先向用户确认。

### Prompt 是什么

先自己列出已确认组件及未决边界，再让 AI 根据你提供的来源形成架构草案；不要只粘贴 Prompt 而不理解关系：

```text
请依据 PROJECT_SPEC.md、经我核对的 docs/handoff/day1-scope.md 和 docs/handoff/day1-unknowns.md，起草当前逻辑架构基线。先说明系统边界、组件职责和有依据的数据流，再把每项标为“原始基线 / 用户明确确认 / 建议（非决定）/ 待我确认 / 实现前验证”。不要把目标架构说成已实现，不要补完整业务模型、部署拓扑或未确认的模块调用关系。每条关键连线说明依据；依据不足就标待设计或先问我。只在对话输出，不修改文件。
```



### 为什么这么做

先有范围和未知项，再抽象组件关系，能避免架构文档反过来替代需求决定。要求说明每条连线依据，是为了让你能审查“为什么这样连接”，而不是只得到一张看似完整的图。

### 验收时我看什么

- **一个动作**：你逐条核对组件、职责、连线和状态标签；无法映射到来源的内容标为待设计/待确认。
- **一个判断标准**：文档区分逻辑目标与实际运行；不把 Compose、`/health` 或图中连线当应用连接/部署证明；未决内容没有被 AI 补成决定。



### 产出与保存位置

- 经你核对后保存为 `docs/architecture.md`；这属于 Day 1 设计产物，不代表业务代码已经实现。
- 这一步的 AI 草案不直接当定稿；来源缺失或决策冲突时先向你确认。



### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
本轮架构来源与已确认项：  
仍待设计/验证的关系：

---



## 步骤 4：你亲手创建项目骨架（含最小测试与 Docker 文件）



### 这一步要消除的不确定性是什么

代码、文档、部署与测试材料分别放在哪里，以及当天是否需要真实实现服务。架构文档已定义逻辑组件边界，但没有替你决定具体目录；目录选择应同时考虑可理解性和当天只实现最小骨架的范围。

### prompt 是什么

用 AI 协助时，先在对话里要求它解释方案；确认理解后，再由你手动创建文件：

```text
基于 PROJECT_SPEC.md，给我一个适用于低并发内部系统和 2 vCPU/2 GiB RAM 的 Day 1 最小目录树与每个目录用途。只在对话中输出，不要创建或修改文件，不写业务代码、不引入未确认服务。异步队列已确认使用 PostgreSQL，不默认加入 Redis。请说明每个建议来自项目说明书还是你的建议。
```



### 为什么这么做：从资源与学习目标推导最小骨架

2 vCPU/2 GiB 的目标环境和低并发说明方案需要克制，但不自动决定具体目录或服务。先让 AI 解释候选目录及来源，再由你选择自己理解的部分，能避免引入不必要的依赖或目录。验收看你能否说明每个目录的用途，而不是目录是否“看起来标准”。

### 验收时我看什么

- **一个动作**：你在编辑器中检查自己创建的目录树。
- **一个判断标准**：每个目录你都能说清用途，并能说明它服务于哪项 Day 1 产物；没有因为“看起来标准”就加入不理解的服务或技术，也不根据架构图的组件名称机械地为每个组件建独立目录/服务。
- 如果没有明确标准：这一步猜错了。替代方案是先只建 `plan/` 与 `docs/handoff/` 文档目录，代码目录等确认后再建。



### 产出与保存位置

- 项目根目录下实际创建的目录结构。
- 只创建经你确认、且你理解用途的目录；目录树草稿本身不需要另存为文档。



### 可选终端命令

先确认当前路径是项目根目录，再由你手动运行。Linux shell 示例：

```bash
# 创建后端应用、测试和前端源码目录。
mkdir -p backend/app backend/tests frontend/src  # 创建后端应用、测试和前端源码目录。
# 创建测试依赖、健康检查测试、Dockerfile 和 Docker 忽略文件。
touch backend/requirements-dev.txt backend/tests/test_health.py backend/Dockerfile backend/.dockerignore  # 创建测试依赖、健康检查测试、Dockerfile 和 Docker 忽略文件。
```

`backend/requirements.txt`、`backend/app/main.py` 和前端骨架文件已经存在；不要用 `touch` 覆盖它们。`backend/Dockerfile` 已存在但内容不完整，`compose.yaml` 已存在但为空，本阶段会配置最小后端服务。以上命令只创建本次新增的空测试/忽略文件，不会写入代码或证明任何验证通过。Day 1 需新增最小健康检查测试材料并补全后端 Dockerfile；`.env.example` 保持不变。不要提前创建 `infra/`、`scripts/`、业务模块、迁移目录或前端功能目录。本文、`PROJECT_SPEC.md`、架构文档及现有交接文档均保留。后续步骤实际执行时再创建相应记录：Day 1 服务器检查与验证分别写入 `docs/handoff/server-checklist.md`、`docs/handoff/day1-verification.md`；Day 2/3 的模块目录和验证记录见各阶段指南，届时按实际实现需要创建。

### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
实际创建的目录：

---



## 步骤 5：你自己理解、运行并验证最小服务



### 这一步要消除的不确定性是什么

当前 `backend/app/main.py` 已经有真实的 FastAPI 应用与 `/health` 路由；需要先理解并运行这份实现，再分别用测试和 Docker 收集证据。测试不是服务实现，Dockerfile 也不是业务功能实现。Day 1 不添加数据库、Agent、队列、渠道或其他业务功能。

### prompt 是什么

```text
请先阅读 backend/app/main.py、backend/requirements.txt、backend/Dockerfile、compose.yaml 和前端文件。逐个说明哪些源码/配置已经存在、哪些为空或不完整。先基于现有源码讲解 FastAPI 应用对象、GET /health 路由、处理函数和响应；明确这段 FastAPI 源码本身才是应用实现，pytest/TestClient 只是测试，不能把测试代码当成实现。说明如何用 Uvicorn 在本机实际启动应用，以及如何请求它。
然后分别教学：1) 为现有实现编写独立的 pytest + TestClient 测试；2) 补全当前不完整的 backend/Dockerfile；3) 从空白 compose.yaml 编写仅包含此 FastAPI 后端的最小 Compose 配置。解释 build context、Dockerfile 路径、service、端口映射和容器启动命令。给出 `docker compose config`、`docker compose up --build`、`curl /health` 和 `docker compose down` 的顺序与预期结果。所有示例必须匹配实际目录/模块路径和 Python 3.11.13 环境。先讲解并提供供我手动创建/核对的代码，不要直接修改文件。不要加入 PostgreSQL、Redis、Nginx 或任何业务功能；明确每项验证能证明和不能证明什么。
```



### 为什么这么做：从最小目标与失败风险推导实现问题

Day 1 的功能目标仍只有健康检查和静态占位页。实际 FastAPI 源码、Uvicorn 服务进程、TestClient 测试、Dockerfile 镜像构建和 Compose 编排是不同层次：测试不实现服务，镜像构建不证明容器可运行，Compose 配置可解析不证明 API 正常。只有在 Compose 启动后通过 HTTP 请求 `/health`，才能证明本机这次启动的容器可响应健康接口。它仍不证明 Nginx、HTTPS、数据库连接或生产部署已通过。Vue 前端用 Vite 开发服务器验证，并单独运行生产构建；Vite 开发服务器不作为生产服务。

### 验收时我看什么

- **一个动作**：先读懂现有 FastAPI 源码，分别验证本机 Uvicorn、TestClient 测试和前端；再补全 Dockerfile/Compose 配置，启动 Compose 服务并请求 `/health`。
- **一个判断标准**：本机 Uvicorn 和 Compose 容器的 `/health` 均返回 HTTP 200 及 `{"status":"ok"}`；测试断言通过；Compose 配置校验与镜像构建/启动有实际结果；前端可见且生产构建成功。记录每一步原始结果。单测不代替服务启动，镜像构建或 `compose config` 成功不代表 API 正常。
- 若当前没有可验证的运行条件：明确记录“待执行”或阻塞原因，不要声称通过。



### 产出与保存位置

- 后端实现：保留并理解 `backend/app/main.py`、运行依赖 `backend/requirements.txt`；新增测试依赖 `backend/requirements-dev.txt` 和测试 `backend/tests/test_health.py`；补全现有 `backend/Dockerfile` 并添加 `backend/.dockerignore`。
- Compose 实现：在现有空白 `compose.yaml` 中配置单一 FastAPI 后端服务，不加入其他服务。前端文件为 `frontend/src/main.ts`、`frontend/index.html`、`frontend/package.json`；`.env.example` 不修改。本步不创建 `deploy/`，Compose 配置不是最终生产拓扑。
- 实际启动方式、测试/构建/请求结果记录到 `docs/handoff/day1-verification.md`。如果未能执行，记录错误，不标记为通过。



### 单独为实际实现写测试

在 `backend/requirements.txt` 中列出开发测试依赖，例如：

```text
-r requirements.txt  # 继承运行依赖清单中的全部依赖。
httpx>=0.27,<1.0  # 添加 TestClient 所需的 HTTP 客户端依赖。
pytest>=8,<9  # 添加测试运行器依赖。
```

`TestClient` 需要 HTTPX；把这些依赖放在开发/测试文件中，避免它们进入后端运行镜像。本地环境 Python 3.11.13 可运行上述开发依赖；如果使用其他版本，先核对依赖支持范围。安装报错时记录实际 Python 版本和错误，不要通过随意升级/降级绕过。

先阅读当前的 `backend/app/main.py`。目前源码创建了标题为 `Enterprise Agent API`、版本 `0.1.0` 的 FastAPI 应用，并通过 `GET /health` 返回 `{"status":"ok"}`。下面的测试是针对这份实际源码写的回归测试，不是要求重写 FastAPI 应用。

在 `backend/tests/test_health.py` 中写（这是验证代码，不是 FastAPI 服务实现）：

```python
from fastapi.testclient import TestClient  # 导入 FastAPI 的测试客户端。

from app.main import app  # 导入待验证的 FastAPI 应用。


def test_health_returns_ok():  # 定义健康检查接口的回归测试。
    client = TestClient(app)  # 为应用创建测试客户端。
    response = client.get("/health")  # 请求健康检查接口。

    assert response.status_code == 200  # 确认接口返回 HTTP 200。
    assert response.json() == {"status": "ok"}  # 确认响应 JSON 内容正确。
```

此测试假定 `backend/` 是当前工作目录，以便 `from app.main import app` 对应现有源码路径。若以后源码结构或响应内容改变，应根据新的实际实现更新测试；不要为让测试通过而盲目改源码或断言。

在项目根目录运行：

```bash
# 查看当前 Python 解释器版本。
python --version  # 查看当前 Python 解释器版本。
# 在项目根目录创建虚拟环境。
python -m venv .venv  # 在项目根目录创建虚拟环境。
# 激活虚拟环境。
source .venv/bin/activate  # 激活虚拟环境。
# 切换到后端目录，使测试导入路径正确。
cd backend  # 切换到后端目录，使测试导入路径正确。
# 安装后端及测试所需依赖。
python -m pip install -r requirements-dev.txt  # 安装后端及测试所需依赖。
# 安静模式运行后端测试。
python -m pytest tests -q  # 安静模式运行后端测试。
```

Windows PowerShell 从项目根目录激活命令为 `.\.venv\Scripts\Activate.ps1`；激活后先运行 `cd backend`，再使用同样的 pip/pytest 命令。若项目已有虚拟环境，先确认其中 Python 版本符合依赖要求再使用。预期测试显示 1 项通过。TestClient 在当前进程内调用 ASGI 应用；它不启动网络端口，也不证明 Docker 容器或 Compose 可运行。

### 补全后端 Dockerfile 并构建镜像

当前入口文件 `backend/app/main.py` 定义的应用对象名为 `app`，因此下方启动命令使用 `app.main:app`。将当前只有未完成 `FROM python:` 指令的 `backend/Dockerfile` 替换为以下完整内容：

```dockerfile
# 使用轻量的 Python 3.11 基础镜像。
FROM python:3.11-slim  # 使用轻量的 Python 3.11 基础镜像。

# 将容器内的工作目录设为 /app。
WORKDIR /app  # 将容器内的工作目录设为 /app。

# 先复制运行依赖清单以便缓存依赖安装层。
COPY requirements.txt .  # 先复制运行依赖清单以便缓存依赖安装层。
# 安装后端运行依赖且不保留 pip 缓存。
RUN pip install --no-cache-dir -r requirements.txt  # 安装后端运行依赖且不保留 pip 缓存。

# 将 FastAPI 应用代码复制到镜像中。
COPY app ./app  # 将 FastAPI 应用代码复制到镜像中。

# 声明应用使用的容器端口。
EXPOSE 8000  # 声明应用使用的容器端口。
# 启动 Uvicorn 并监听容器内所有网络接口的 8000 端口。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]  # 启动 Uvicorn 并监听容器内所有网络接口的 8000 端口。
```

这里的 Docker 构建上下文是 `backend/`：Docker 只能复制上下文目录中的文件。`requirements.txt` 先单独复制，使应用代码改变时可复用依赖安装层；随后复制 `app/`，其中包含实际的 `app/main.py`。镜像只含运行依赖及 FastAPI，不含 pytest、HTTPX、前端或其他服务。若后续源码增加依赖文件或模块，需相应更新 Dockerfile 的复制路径和构建说明。`EXPOSE` 是镜像端口说明，不会自动把端口发布到主机；Uvicorn 监听 `0.0.0.0` 才能从容器外访问。

在 `backend/.dockerignore` 中排除不需要送入构建上下文的本地文件，例如：

```text
# 忽略项目本地 Python 虚拟环境。
.venv/
# 忽略 Python 字节码缓存目录。
__pycache__/
# 忽略 pytest 运行缓存目录。
.pytest_cache/
# 忽略仅用于开发测试的测试目录。
tests/
```

不要忽略 `app/`、`requirements.txt` 或 Dockerfile。

在项目根目录执行（`-f` 指定 Dockerfile，最后的 `backend` 是构建上下文）：

```bash
# 从 backend 构建上下文构建并标记本地 FastAPI 镜像。
docker build -t day1-fastapi:local -f backend/Dockerfile backend  # 从 backend 构建上下文构建并标记本地 FastAPI 镜像。
```

构建成功只证明 Docker 能按 Dockerfile 生成镜像，不证明容器运行或 API 正常。

启动容器并验证：

```bash
# 在前台启动容器并仅将服务端口绑定到本机回环地址。
docker run --rm --name day1-fastapi -p 127.0.0.1:8000:8000 day1-fastapi:local  # 在前台启动容器并仅将服务端口绑定到本机回环地址。
```

该命令会占用当前终端；保持运行，另开终端执行：

```bash
# 请求本机容器的健康检查接口并显示 HTTP 响应头。
curl -i http://127.0.0.1:8000/health  # 请求本机容器的健康检查接口并显示 HTTP 响应头。
```

预期 HTTP 200，JSON 为 `{"status":"ok"}`。按 `Ctrl+C` 停止容器；因使用 `--rm`，容器停止后会自动删除。需要移除测试镜像时运行 `docker image rm day1-fastapi:local`。主机只绑定 `127.0.0.1`，仅本机可访问；不要为这项练习将端口公开到局域网或公网。

单独 `docker run` 验证完成后，继续使用 Compose 使用同一个后端服务。Compose 不是另一份 FastAPI 实现，而是声明如何构建镜像、发布端口并启动服务。

### 从空白 compose.yaml 编写最小后端服务

`compose.yaml` 当前为空，因此 Compose 尚无可运行服务。在项目根目录的 `compose.yaml` 中填写（这是本阶段配置服务编排，不是 FastAPI 实现）：

```yaml
# 声明 Compose 管理的服务集合。
services:  # 声明 Compose 管理的服务集合。
  # 定义名为 backend 的 API 服务。
  backend:  # 定义名为 backend 的 API 服务。
    # 配置服务镜像的构建方式。
    build:  # 配置服务镜像的构建方式。
      # 将后端目录作为 Docker 构建上下文。
      context: ./backend  # 将后端目录作为 Docker 构建上下文。
      # 使用构建上下文中的 Dockerfile。
      dockerfile: Dockerfile  # 使用构建上下文中的 Dockerfile。
    # 将容器端口映射到仅本机可访问的主机端口。
    ports:  # 将容器端口映射到仅本机可访问的主机端口。
      - "127.0.0.1:8000:8000"  # 将主机回环地址端口映射到容器端口。
```

`services.backend` 是服务名；`build.context` 相对 Compose 文件所在的项目根目录，指向 `./backend`；`dockerfile` 相对 build context，因此写 `Dockerfile`；`ports` 左侧是主机端口，右侧是容器端口，并将主机端口限制为本机访问。服务使用 Dockerfile 的默认 `CMD` 启动，不必重复写 `command`。本配置只有 API 服务，不包含数据库、Redis、Nginx，也不是生产部署配置。

从项目根目录执行：

```bash
# 校验 Compose 配置能否解析。
docker compose config  # 校验 Compose 配置能否解析。
# 构建镜像并启动 Compose 服务。
docker compose up --build  # 构建镜像并启动 Compose 服务。
```

`config` 成功只表示 Compose 文件能解析；`up --build` 会构建镜像并启动服务，保持终端运行。另开终端执行：

```bash
# 请求本机容器的健康检查接口并显示 HTTP 响应头。
curl -i http://127.0.0.1:8000/health  # 请求本机容器的健康检查接口并显示 HTTP 响应头。
```

检查 HTTP 200 及 `{"status":"ok"}`，然后回到运行 Compose 的终端按 `Ctrl+C`，再在项目根目录执行：

```bash
# 停止并移除本练习创建的 Compose 容器和网络。
docker compose down  # 停止并移除本练习创建的 Compose 容器和网络。
```

`down` 停止并移除本练习创建的容器和网络，不删除构建镜像。不要运行会清理其他项目数据的全局 prune 命令。Compose 冒烟通过只证明此单机后端服务当前能构建和响应，不证明 HTTPS、Nginx、数据库、备份或生产部署。

### 前端手动验证

在 `frontend/` 目录按 `package.json` 中脚本安装依赖，运行开发服务器查看占位页，并运行 `npm run build` 验证前端生产构建。记录实际使用的包管理器和输出；构建成功不代表 Nginx 已部署。以下是构建输出示例，不是代码。

### 你的记录

```text
# 以下为历史构建终端输出示例，不是可执行代码。
root@iZj6cj2jk6fiwhspq216jqZ frontend]# npm run build

> [enterprise-agent-frontend@0.1.0](mailto:enterprise-agent-frontend@0.1.0) build

> vite build

vite v6.4.4 building for production...

✓ 8 modules transformed.

dist/index.html                 0.33 kB │ gzip:  0.24 kB

dist/assets/index-WnPuYi0Y.js  65.91 kB │ gzip: 26.25 kB

✓ built in 1.93s
```

状态：部分完成；本记录仅汇总目前提供的证据，不代表 Day 1 全部验收完成。详见 [day1-verification.md](../docs/handoff/day1-verification.md) 第 6 节。  
本机 Uvicorn 启动与 `/health` 请求：本轮输出记录独立 Docker 容器内 Uvicorn 成功启动；容器日志中 `/health` 返回 HTTP 200 OK，未提供响应体。`/` 与 `/favicon.ico` 返回 HTTP 404（不影响本次健康检查路由结果）。  
FastAPI 测试命令与结果：在 `backend/` 运行 `python -m pytest tests -q`，1 passed、1 warning。首次因环境中未安装 pytest 而失败；在已激活的 `.venv` 中安装 `pytest httpx` 后通过。Starlette 输出了使用 `httpx` 的弃用警告。  
前端访问和构建结果：本轮记录没有提供新的前端浏览器/DOM 验证；此前生产构建结果见本指南上方示例及 handoff 记录。  
独立 Docker 镜像构建/运行结果：在 `backend/` 下使用项目根目录相对路径首次失败（context `backend` 不存在）；回到项目根目录后同一构建命令成功。首次运行遇到旧容器占用同名；用户检查并移除旧容器后，新容器成功启动，日志见上。记录未显示新容器停止结果。  
Compose 配置校验结果：本轮未提供证据，待执行。  
Compose 服务启动及 `/health` 请求结果：本轮未提供 Compose 运行证据，待执行。  
Compose 停止结果：待执行。

---



## 步骤 6：你亲手核查目标服务器条件



### 这一步要消除的不确定性是什么

目标 Alibaba Cloud Linux 服务器是否具备运行项目的真实条件；本机 Windows 检查不能代替远程检查。操作系统、CPU/内存/磁盘、Docker/Compose 和 Swap 各是独立条件，不能相互推断。

### prompt 是什么

```text
请根据 PROJECT_SPEC.md 帮我解释下面这些 Alibaba Cloud Linux 检查命令分别检查什么，并指出输出中哪些内容需要我记录。只解释，不连接服务器、不执行命令、不修改配置：cat /etc/os-release；nproc；free -h；df -h；docker --version；docker compose version；swapon --show。
```



### 为什么这么做：从检查对象和证据来源推导

项目目标环境是远程 Alibaba Cloud Linux，而你的开发终端可能是本机；因此 Prompt 只解释检查命令，由你在目标服务器执行，避免把本机输出冒充服务器状态。每项需要实际输出或明确标为待执行/阻塞，因为操作系统、资源、Docker、Swap、域名和 HTTPS 是不同检查对象，不能由其中一个推断其他项通过。

### 验收时我看什么

- **一个动作**：你 SSH 登录目标服务器并执行只读检查命令。
- **一个判断标准**：记录了实际输出，或明确标记“待我确认/待检查”；没有用 Windows 输出冒充服务器结果。
- 若你当天没有服务器访问权限：这一步不算失败，标为待执行。替代方案是 Day 1 只验收本地运行基线。



### 产出与保存位置

- 将目标服务器只读检查的实际输出或摘要保存到 `docs/handoff/server-checklist.md`。
- 未执行的检查标为“待执行”；被权限或环境阻塞的项目标明原因。



### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
服务器检查证据：

---



## 步骤 7：你自己做最终冒烟验收并留证



### 这一步要消除的不确定性是什么

今天的结果是否真的可运行、可复现，以及哪些项目仍未完成。

### prompt 是什么

```text
请根据我提供的实际命令输出，帮我判断 Day 1 冒烟验收是否通过。只依据我贴出的证据，不要推断未执行的步骤已通过。逐项检查本机 Uvicorn 启动与 /health 请求、FastAPI 测试、前端页面与构建、Docker 镜像构建/运行及目标服务器检查；指出通过项、失败项、待执行项及下一步建议。Docker 镜像构建成功不能代替容器 HTTP 验收。Compose 也按实际证据评估，不要把配置检查通过说成服务已运行。不要修改文件。
```



### 为什么这么做：从验收目标反推证据

本步骤要判断 FastAPI 实际实现、本机服务、API 测试、前端、Docker 镜像/容器、Compose 和服务器检查分别做到哪里，所以 Prompt 要求逐项依据真实输出，而非笼统问“Day 1 完成了吗”。TestClient 通过不能证明网络服务已启动；镜像构建成功不能证明容器能响应；容器 `/health` 200 不能证明数据库连接或生产部署；Compose 状态也要如实记录，没执行的检查应保留为待执行。记录失败和证据缺口，是为了让 Day 2 从实际状态继续，而不是从假设继续。

### 验收时我看什么

- **一个动作**：亲自运行本机 FastAPI 服务及请求、API 测试、前端访问/构建、独立 Docker 镜像构建和容器启动，再请求 `/health` 并记录结果。
- **一个判断标准**：本机服务和 Docker 容器的 `/health` 均返回 HTTP 200 和预期 JSON；pytest、前端生产构建、Docker 镜像构建及容器启动分别有实际结果。Compose 配置和验证均按本步骤执行；未执行的服务器/渠道检查明确标为待执行。测试和镜像构建各自只证明对应层次；这些结果不等于 Nginx、HTTPS、数据库或生产部署已验证。
- 若其中一项失败：这一步不通过。替代方案是记录失败输出和阻塞，不掩盖问题，不声称 Day 1 全部完成。



### 产出与保存位置

- 将本机 Uvicorn 启动/请求、FastAPI 测试、前端访问/构建、Docker 镜像构建与容器 `/health` 响应、停止结果、未解决问题和各项状态保存到 `docs/handoff/day1-verification.md`。
- 服务器检查结果仍保存于 `docs/handoff/server-checklist.md`，此处引用其状态即可，不必重复粘贴完整输出。



### 你的记录

状态：待你填写（待执行 / 已完成 / 阻塞）  
本机 Uvicorn 启动与 `/health`：  
FastAPI 测试结果：  
前端访问/构建结果：  
Dockerfile 镜像构建/运行结果：  
Compose 配置结果：  
Compose 启动和 `/health` 请求结果：  
Compose 停止结果：  
未解决问题：

---



## 迁移练习：把思路用到一个新问题

假设 Day 1 验收时页面能打开，但你没有保存访问地址或截图。先不要套用上面的 Prompt，也不要直接问“Day 1 是否完成”。请自己写下：

- 现在能确认的事实是什么？证据来自哪里？
- 哪个结论仍不能成立？缺少什么证据？
- 你希望 AI 做分析、提出下一步证据清单，还是替你修改文件？本次应把工作边界设在哪里？
- 你将亲自做什么，什么结果才足以把这一项标为通过？

完成后再对照开篇推导链检查：问题是否来自真实不确定性，结论是否强于证据，验收是否能由你观察。重点不是复刻某段 Prompt，而是能解释为什么需要每一项要求。

## Day 1 结束检查

- [ ] 我确认并修订了范围，而不是接受 AI 自动决定。
- [ ] 我把未决问题保留为“待我确认”。
- [ ] 我理解自己创建的目录和文件；能区分 FastAPI 应用实现与 pytest 测试，并说明 Dockerfile、构建上下文和 Compose 配置为何不属于本阶段；还能说明架构文档是逻辑目标基线，不代表对应代码/服务已经实现。
- [ ] 我分别记录了本机 Uvicorn、pytest、Docker 镜像/容器和 HTTP 冒烟验证，或明确记录各自阻塞；没有把测试或配置解析结果冒充服务运行证明。
- [ ] 服务器检查只记录了目标服务器的真实结果。
- [ ] P2 内容仍以“原基线 P2；是否纳入本次范围待确认”表述。



## 交接包内容

完成过程中由你手动填写或确认后保存：

- `docs/handoff/day1-scope.md`
- `docs/handoff/day1-unknowns.md`
- `docs/handoff/server-checklist.md`
- `docs/handoff/day1-verification.md`

这份指南本身不是这些步骤的完成证明。