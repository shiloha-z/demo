# 多 Agent 协作审查平台 — 分步实现计划

> 基于 [note.md](note.md) 中的整体设计方案拆分。核心原则：**每一步结束都有可演示、可验证的产出**。

---

## 总体概览

| 步骤 | 名称 | 核心产出 | 状态 |
|------|------|----------|------|
| 1 | 项目骨架 | 两端启动、DB 就绪、页面壳子 | ✅ 完成 |
| 2 | 认证 + 项目管理 | 注册/登录/创建项目 全链路 | 🔲 待开始 |
| 3 | 文件管理 + Git | 文件树浏览、内容查看、Git 初始化 | 🔲 待开始 |
| 4 | Agent 核心 | Agent CRUD、CrewAI 流水线、Diff 审查 | 🔲 待开始 |
| 5 | 实时 + 决策闭环 | WebSocket 推送、审批/驳回、Commit | 🔲 待开始 |
| 6 | 记忆 + 打磨 | Chroma 三层记忆、错误处理、UI 完善 | 🔲 待开始 |

---

## 第1步：项目骨架搭建 ✅

**目标**：两端项目能启动，数据库表创建完毕，前端有布局壳子

### 后端
- FastAPI 项目初始化 (`backend/` 目录结构)
- `core/config.py` — 配置（数据库路径、JWT secret、CORS）
- `core/database.py` — SQLAlchemy 引擎 + SessionLocal
- `models/models.py` — 6 张表（users, projects, agents, tasks, reviews, versions）
- `main.py` — FastAPI 入口，CORS 中间件，空路由占位
- `requirements.txt` — 依赖清单

### 前端
- Vue 3 + Vite 项目初始化 (`frontend/` 目录)
- Element Plus 安装
- 基础布局：顶部导航栏 + 左侧边栏 + 主内容区
- 5 个页面占位组件（标题即可）
- Vue Router 路由配置
- Pinia 空 store 占位（auth, project, websocket）

### 验证标准
- `uvicorn app.main:app --reload` 启动后端，访问 `/docs` 看到 Swagger
- `npm run dev` 启动前端，5 个页面可切换，布局正确
- 数据库表自动创建成功

---

## 第2步：认证 + 项目管理

**目标**：完整的用户注册→登录→创建项目→查看项目列表流程

### 后端
- `core/auth.py` — JWT 生成与验证、密码哈希
- `api/auth.py` — POST /register, POST /login
- `api/projects.py` — CRUD (list, create, get detail)
- 认证依赖注入（get_current_user）

### 前端
- 登录/注册页面
- `stores/auth.ts` — 登录状态、token 存储（完善）
- `stores/project.ts` — 项目列表（完善）
- `api/index.ts` — axios 封装 + 拦截器（完善）
- 项目看板页面基础版（项目列表 + 创建对话框）

### 验证标准
- 注册用户 → 登录获取 token → 创建项目 → 项目列表显示
- 未登录状态下重定向到登录页
- JWT 过期后自动跳转登录

---

## 第3步：文件管理 + Git 集成

**目标**：项目有真实工作区，前端能浏览文件树和查看文件内容

### 后端
- `services/git_service.py` — GitPython 初始化仓库、生成 diff
- `api/files.py` — GET 文件树（递归扫描目录）、GET 文件内容
- 创建项目时自动 `git init` 工作区 (`workspaces/{project_id}/`)

### 前端
- `components/FileTree.vue` — el-tree 展示真实文件结构
- `FileManagerView.vue` — 文件树 + Monaco Editor (readOnly)
- 点击树节点加载文件内容到编辑器

### 验证标准
- 创建项目后在 `workspaces/` 下生成 `.git` 目录
- 前端文件管理器能浏览工作区目录
- 点击文件在 Monaco Editor 中查看内容（语法高亮）

---

## 第4步：Agent 核心 — 审查流水线

**目标**：创建 Agent → 发起任务 → CrewAI 执行代码生成+审查 → 前端展示 Diff 和审查报告

> ⚡ 整个 Demo 的**核心步骤**，工作量最大。

### 后端
- `api/agents.py` — Agent CRUD
- `api/tasks.py` — 任务创建，触发 Agent 执行
- `api/reviews.py` — 审查记录查询
- `agent_service/crews/review_pipeline.py` — CrewAI 流水线：
  - CodeGenAgent → ReviewAgent + SecurityAgent → SummarizerAgent
- `agent_service/tools/file_tools.py` — 文件读写工具（沙箱在 workspace 内）
- `agent_service/tools/git_tools.py` — Git diff 工具
- `services/agent_runner.py` — 调用 CrewAI，用 `asyncio.to_thread()` 避免阻塞
- `services/review_service.py` — 审查结果存储

### 前端
- `AgentPanelView.vue` — Agent 列表、创建 Agent 表单、任务输入框
- `components/AgentChat.vue` — Agent 对话/状态展示
- `components/MonacoDiff.vue` — Monaco Editor diff 模式封装
- `DiffReviewView.vue` — 并排 Diff + 审查意见展示
- Agent 状态机：idle → working → done (loading 动画)

### 验证标准
- 创建 Agent "小码"（代码生成器）
- 输入任务："写一个用户登录接口 login.py"
- Agent 执行 → 生成代码 → Diff 出现 → 审查意见展示
- **核心 Demo 流程在此步骤完成 60%**

---

## 第5步：实时通信 + 人工决策

**目标**：WebSocket 推送 + 通过/驳回 + Git commit + 版本历史

### 后端
- `api/ws.py` — WebSocket 管理器（连接池、广播）
- 定义 WebSocket 消息 schema：
  - `agent_status` — Agent 状态变化
  - `file_change` — 文件变更通知
  - `review_update` — 审查状态更新
  - `task_update` — 任务状态更新
- Agent 执行过程中推送状态变化
- `POST /api/reviews/{rid}/approve` → GitPython commit
- `POST /api/reviews/{rid}/reject` → 反馈注入，触发重新执行
- `api/versions.py` — 版本列表 + 回退

### 前端
- `stores/websocket.ts` — WebSocket 连接管理、自动重连（完善）
- 文件树根据 WebSocket 推送自动刷新
- Agent 状态实时更新（无需轮询）
- `DiffReviewView.vue` 增加通过/驳回按钮
- `VersionHistoryView.vue` — 版本时间线 + 回退按钮

### 验证标准
- Agent 执行时前端实时看到状态变化
- 审查报告出现后可点击"通过"→ 自动 commit → 文件管理器出现新文件
- 点击"驳回"→ Agent 修改代码 → 新审查报告出现
- 版本历史记录 commit，可回退
- **完整 Demo 流程 100% 跑通**

---

## 第6步：记忆系统 + 打磨

**目标**：Chroma 三层记忆、完善的错误处理、UI 细节

### 后端
- `agent_service/memory/memory_manager.py` — Chroma 封装
  - 短期：会话上下文（内存，task 级别）
  - 中期：Agent 经验（collection: `agent_{id}`）
  - 长期：项目知识库（collection: `project_{id}`）
- `agent_service/tools/memory_tools.py` — 记忆检索工具
- 全局异常处理、超时重试
- 分页参数（列表接口）

### 前端
- 全局错误提示（el-message 封装）
- 空状态、loading 状态、错误状态覆盖
- Diff 审查器：点击审查意见高亮对应代码行
- 项目看板增加统计数据（任务数、审查通过率等）
- UI 细节：过渡动画、响应式调整

### 验证标准
- Agent 执行时检索到项目知识库内容
- 驳回过的模式被存入中期记忆，后续任务中 Agent 避免同样错误
- 所有异常场景有友好提示
- UI 流畅、无闪烁

---

## 关键技术决策

| 决策点 | 选择 | 说明 |
|--------|------|------|
| Agent 执行 | `asyncio.to_thread()` | 避免阻塞 FastAPI event loop，后续可升级 Celery |
| CrewAI 调用 | 同进程 import | agent_service/ 作为 backend 子目录被调用 |
| 数据库 | SQLite | 开发阶段单文件零配置，后续可切 PostgreSQL |
| Monaco Editor | `@guolao/vue-monaco-editor` | Vue 3 封装好的 Monaco，开箱即用 |
| LLM 后端 | DeepSeek | OpenAI-compatible API，通过环境变量配置 |
| 前端 UI | Element Plus | 成熟的 Vue 3 组件库 |

---

## 验证方式

每步结束后手动验证上述验证条目。

**最终验收**（第5步结束后）：按 [note.md](note.md) 第九节的 8 步 Demo 流程完整走一遍——

1. 用户 A 注册登录
2. 用户 A 创建项目 "电商后台"
3. 用户 A 创建 Agent "小码"（代码生成器）
4. 输入任务："写一个用户登录接口 login.py"
5. Agent 开始工作（状态：idle → working）
6. Diff 审查器出现修改：并排 Diff + 审查意见
7. 点击"通过"，自动 commit，文件管理器出现 login.py
8. 版本历史中出现记录，可以回退
