# AgentCollab — 多 Agent 协作审查平台

> 一个基于多 Agent 框架的代码生成与审查平台。用户创建任务后，AI Agent 自动完成代码编写 → 审查 → 安全扫描 → 报告汇总的全流程，产出可直接合并到 Git 主分支的代码变更和结构化审查报告。

## 核心流程

```
用户创建任务 → Agent 流水线执行 → 代码 Diff + 审查报告 → 人工决策（通过/驳回反馈/结束）
```

1. **代码生成** — Agent 分析需求，在隔离的 Git 分支上编写代码
2. **代码审查** — 检查逻辑错误、命名规范、潜在 Bug、代码风格
3. **安全审查** — 扫描 SQL 注入、XSS、命令注入、硬编码密钥等安全漏洞
4. **汇总报告** — 整合审查意见，按严重程度排序，生成 Markdown 报告
5. **人工决策** — 通过则合并到 master；驳回则附反馈让 Agent 修改；结束则丢弃变更

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI (Python 3.12) |
| 数据库 | SQLite + SQLAlchemy ORM |
| 认证 | JWT (python-jose) + PBKDF2 密码哈希 |
| 实时推送 | FastAPI 原生 WebSocket |
| Git 操作 | GitPython |
| Agent 框架 | CrewAI / Claude Code CLI / OpenCode CLI |
| LLM | DeepSeek API（OpenAI 兼容协议） |
| 向量记忆 | ChromaDB（四层分层记忆系统） |

### 前端

| 组件 | 技术 |
|------|------|
| 框架 | Vue 3 (Composition API + `<script setup>`) |
| 语言 | TypeScript |
| 构建工具 | Vite 8 |
| UI 组件库 | TDesign Vue Next |
| 状态管理 | Pinia |
| 路由 | Vue Router 4 |
| 代码编辑器 | Monaco Editor |
| Markdown 渲染 | marked (GFM) |

## 项目结构

```
demo/
├── backend/                          # FastAPI 后端
│   ├── app/
│   │   ├── main.py                   # FastAPI 入口，路由注册，CORS
│   │   ├── api/
│   │   │   ├── auth.py               # 注册/登录 (JWT)
│   │   │   ├── projects.py           # 项目 CRUD + 文件管理 + 上传
│   │   │   ├── agents.py             # Agent CRUD + CLI 检测
│   │   │   ├── tasks.py              # 任务 CRUD + 后台触发流水线
│   │   │   ├── reviews.py            # 审查记录：通过/驳回反馈/结束
│   │   │   ├── versions.py           # 版本历史 + 回退
│   │   │   ├── models.py             # LLM 模型列表查询
│   │   │   ├── settings.py           # 配置读写（.env） + 脱敏
│   │   │   └── ws.py                 # WebSocket 连接管理 + 广播
│   │   ├── core/
│   │   │   ├── config.py             # Pydantic Settings（.env 加载）
│   │   │   ├── database.py           # SQLAlchemy 引擎 + init_db()
│   │   │   └── auth.py               # 密码哈希 + JWT 编解码
│   │   ├── models/
│   │   │   └── models.py             # ORM：User, Project, Agent, Task, Review, Version
│   │   └── services/
│   │       ├── agent_runner.py       # 流水线编排器（后台线程）
│   │       ├── git_service.py         # Git 分支/提交/Diff/合并/回退
│   │       └── memory_service.py      # ChromaDB 四层记忆（任务/Agent/项目/全局）
│   ├── agent_service/
│   │   ├── runners/
│   │   │   ├── base.py               # Runner 抽象基类 + RunResult
│   │   │   ├── factory.py            # Runner 工厂（根据 runner_type 分发）
│   │   │   ├── crewai_runner.py      # CrewAI 4-Agent 顺序流水线
│   │   │   ├── claude_runner.py      # Claude Code CLI（子进程调用）
│   │   │   ├── opencode_runner.py    # OpenCode CLI（子进程调用）
│   │   │   └── tool_adapters.py      # 公共工具适配层
│   │   └── tools/
│   │       ├── file_tools.py         # FileRead / FileWrite（工作区沙箱）
│   │       ├── git_tools.py          # GitDiff 工具
│   │       └── memory_tools.py       # 记忆检索 / 记录工具
│   ├── .env                          # 环境配置（不入仓库）
│   ├── .env.example                  # 配置模板
│   ├── requirements.txt              # Python 依赖
│   ├── data.db                       # SQLite 数据库（自动生成）
│   └── chroma_data/                  # ChromaDB 向量存储（自动生成）
├── frontend/                         # Vue 3 前端
│   ├── src/
│   │   ├── main.ts                   # Vue 应用入口
│   │   ├── App.vue                   # 根组件：侧边栏 + 顶栏 + 内容区
│   │   ├── style.css                 # 全局样式入口
│   │   ├── styles/
│   │   │   ├── tokens.css            # Design Tokens（亮色/暗色主题变量）
│   │   │   └── components.css        # 共享组件样式
│   │   ├── api/
│   │   │   └── index.ts              # Axios 实例 + 拦截器 + 错误处理
│   │   ├── router/
│   │   │   └── index.ts              # 路由定义 + 登录守卫
│   │   ├── stores/
│   │   │   ├── auth.ts               # 认证状态（token/用户信息）
│   │   │   ├── project.ts            # 项目状态（列表/当前项目/排序）
│   │   │   ├── websocket.ts          # WebSocket 连接 + 事件订阅
│   │   │   └── theme.ts              # 主题状态（亮色/暗色切换）
│   │   ├── utils/
│   │   │   └── markdown.ts           # Markdown 渲染（marked + GFM）
│   │   ├── components/
│   │   │   ├── ProjectSidebar.vue    # 项目列表侧边栏 + 系统设置入口
│   │   │   ├── FileTree.vue          # 文件树组件（递归渲染）
│   │   │   ├── MonacoEditor.vue      # Monaco Editor 封装（语法高亮）
│   │   │   ├── DiffViewer.vue        # 代码 Diff 查看器（分组/增删/行号）
│   │   │   ├── PipelineStepper.vue   # 流水线阶段步骤条
│   │   │   └── TaskTimeline.vue      # 任务执行时间线（甘特图风格）
│   │   └── views/
│   │       ├── LoginView.vue         # 登录/注册页
│   │       ├── DashboardView.vue     # 项目看板（统计卡片 + 项目网格）
│   │       ├── FileManagerView.vue   # 文件管理器（文件树 + 编辑器）
│   │       ├── AgentPanelView.vue    # Agent 池（创建/管理 Agent）
│   │       ├── TaskListView.vue      # 任务列表 + 详情 + 流水线 + 审查决策
│   │       ├── DiffReviewView.vue    # 审查记录（Diff + Markdown 报告）
│   │       ├── VersionHistoryView.vue# 版本历史 + 回退
│   │       └── SettingsView.vue      # 系统设置（API Key/端点/工作空间）
│   ├── package.json
│   └── vite.config.ts
├── workspaces/                       # 项目 Git 工作区（运行时生成）
├── .gitignore
└── IMPLEMENTATION_PLAN.md            # 原始实现计划文档
```

## 快速开始

### 环境要求

- **Python** 3.12+
- **Node.js** 18+
- **Git** 2.30+
- **DeepSeek API Key**（CrewAI 引擎使用）
- （可选）**Claude Code CLI** — 使用 `claude_code` 引擎时需要
- （可选）**OpenCode CLI** — 使用 `opencode` 引擎时需要

### 1. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，设置 DEEPSEEK_API_KEY=sk-...

# 启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

后端启动后：
- API 文档：`http://localhost:8000/docs`
- WebSocket：`ws://localhost:8000/api/ws?token=<JWT>`

### 2. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端启动后访问 `http://localhost:5173`。

### 3. 系统设置

登录后，在侧边栏「系统设置」中配置：

| 设置项 | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（CrewAI / OpenCode 引擎使用） |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥（Claude Code 引擎使用） |
| `DEEPSEEK_BASE_URL` | DeepSeek API 端点（默认 `https://api.deepseek.com`） |
| `OPENCODE_SERVER_URL` | OpenCode 服务地址（默认 `http://localhost:36000`） |
| `WORKSPACE_ROOT` | 项目 Git 工作区根目录（默认 `../workspaces`） |

也可以在 `backend/.env` 中直接编辑，修改即时生效。

### 4. 基本使用流程

1. **创建项目** — 在项目看板点击「创建项目」，输入名称和描述
2. **创建 Agent** — 在 Agent 池中创建 Agent，选择角色（代码工程师/审查员/安全审查员）、模型和执行引擎
3. **创建任务** — 在 Agent 面板或任务列表中选择 Agent，输入任务描述，启动执行
4. **查看进度** — 任务详情页实时展示流水线阶段、进度日志、代码预览
5. **审查决策** — 任务完成后查看 Diff 和审查报告，选择：
   - **通过**：合并到 master 分支
   - **驳回并修改**：填写反馈意见，Agent 自动重新执行
   - **结束**：丢弃变更，终止审查
6. **版本管理** — 查看版本历史，支持回退到任意版本

## 环境变量

```bash
# ── 数据库 ──────────────────────────
DATABASE_URL=sqlite:///./data.db      # SQLite 数据库路径

# ── 认证 ────────────────────────────
JWT_SECRET=dev-secret-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440               # Token 有效期（分钟）

# ── 工作空间 ────────────────────────
WORKSPACE_ROOT=../workspaces           # 项目 Git 仓库根目录

# ── LLM 配置 ────────────────────────
DEEPSEEK_API_KEY=sk-...               # DeepSeek API Key（必填）
DEEPSEEK_BASE_URL=https://api.deepseek.com
ANTHROPIC_API_KEY=                    # Anthropic API Key（Claude Code 使用）
OPENCODE_SERVER_URL=http://localhost:36000
```

## 执行引擎对比

| 特性 | CrewAI | Claude Code | OpenCode |
|------|--------|-------------|----------|
| 类型 | Python SDK（进程内调用） | CLI 子进程 | CLI 子进程 |
| LLM 后端 | DeepSeek | Anthropic Claude | 任意 OpenAI 兼容 API |
| 安装要求 | `pip install crewai` | `npm install -g @anthropic-ai/claude-code` | 安装 OpenCode CLI |
| 工具支持 | FileRead/Write, GitDiff, Memory | 原生文件编辑/Git/Bash | 原生文件编辑/Git/Bash |
| 适用场景 | 低成本快速验证 | 高质量代码生成 | 多模型灵活切换 |

创建 Agent 时会自动检测本地是否安装了对应的 CLI 工具，并可通过「检测模型」按钮验证 API Key 是否可用。

## Agent 流水线

```
代码工程师 (code_gen)
    │  根据任务描述，在隔离的 Git 分支上编写代码
    ▼
代码审查员 (reviewer)
    │  检查逻辑错误、命名规范、潜在 Bug、代码可读性
    ▼
安全审查员 (security)
    │  扫描注入攻击、越权访问、硬编码密钥等安全漏洞
    ▼
审查汇总员 (summarizer)
    │  整合审查意见 → 按严重程度排序 → Markdown 报告
    ▼
人工决策
    ├── 通过 → 合并到 master → 创建版本记录
    ├── 驳回并修改 → Agent 根据反馈在同一分支重新执行
    └── 结束 → 丢弃变更 → 清理分支
```

## Git 分支隔离

每次任务执行在独立的 Git 分支上进行：

```
master ──┬── task/1 (Agent 修改) ──→ 通过 → merge → master
           ├── task/2 (Agent 修改) ──→ 驳回反馈 → 继续修改 → 通过 → merge → master
           └── task/3 (Agent 修改) ──→ 结束 → 删除分支
```

- 任务之间完全隔离，互不影响
- 仅审查通过后才合并到 master
- 版本历史记录每次合并，支持回退

## 确定性合并门禁

AI 完成代码生成和审查报告后，系统立即在任务隔离分支上执行七项阻断型检查。只有检查通过，界面和后端才允许人工投通过票：

| 检查 | 执行方式 | 未通过时 |
|------|----------|----------|
| 单元测试 | 管理员配置项目测试命令 | 阻止合并 |
| 代码格式与规范 | 内置语法、行尾空白、超长行检查，可扩展 lint 命令 | 阻止合并 |
| 静态安全扫描 | 内置 SQL 注入、命令注入规则，可扩展 SAST 命令 | 阻止合并 |
| 硬编码密钥扫描 | 内置私钥、访问密钥、凭据规则，可扩展密钥扫描命令 | 阻止合并 |
| 依赖漏洞检查 | 管理员配置依赖审计命令 | 阻止合并 |
| 测试覆盖率 | 管理员配置带阈值的覆盖率命令 | 阻止合并 |
| 银行内部禁止项 | 内置敏感文件及禁止文本规则，可扩展内部规则命令 | 阻止合并 |

执行顺序和合并条件为：

```text
AI 生成代码与审查报告
    → 七项确定性检查
        ├─ 代码失败：禁止投通过票 → 按失败项打回 Agent → 重新生成并检查
        ├─ 平台失败：禁止无效打回 → 管理员修复工具/命令 → 原提交重新检查
        └─ 通过：开放人工投票
                    → 达到法定票数
                    → 校验门禁通过的 commit 未被替换
                    → 合并到主分支
```

其中单元测试、依赖漏洞检查和覆盖率检查采用严格模式：命令未配置也会判定失败，不会把“未执行”显示为“已通过”。系统会区分两类失败：测试断言、覆盖率、安全发现等代码问题可以“按失败项打回 Agent”；命令未配置、工具/模块缺失等平台问题不会再无效打回 Agent，管理员修复环境后可对同一提交直接“重新检查”。没有依赖清单的项目会记录为“无第三方依赖可审计”，不会强迫 Agent 创建虚假依赖文件。CrewAI 代码工程师也可以在结束前主动调用同一套门禁，形成“修改—自检—再修改”的闭环。

门禁命令涉及服务端进程执行权限，为避免浏览器配置造成命令注入，只能由运维人员写入受控的 `backend/.env`，不能通过普通设置接口修改：

```bash
# Python 项目示例（工具需安装在执行环境中）
QUALITY_GATE_UNIT_TEST_COMMAND=python -m pytest -q
QUALITY_GATE_STYLE_COMMAND=ruff check .
QUALITY_GATE_STATIC_SCAN_COMMAND=bandit -r .
QUALITY_GATE_SECRET_SCAN_COMMAND=gitleaks detect --no-git
QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND=pip-audit -r requirements.txt
QUALITY_GATE_COVERAGE_COMMAND=python -m pytest --cov=. --cov-fail-under=80
QUALITY_GATE_BANK_RULE_COMMAND=
QUALITY_GATE_FORBIDDEN_PATTERNS=TODO,FIXME
```

每项检查的状态、输出、耗时和失败原因会持久化，并通过 WebSocket 实时展示在任务详情与审查详情中。

## WebSocket 事件

平台通过 WebSocket 实时推送以下事件：

| 事件类型 | 触发时机 | 数据 |
|----------|----------|------|
| `task_update` | 任务状态变更 | `{id, project_id, status, started_at, completed_at}` |
| `task_progress` | 流水线进度更新 | `{task_id, project_id, message, step, timestamp}` |
| `pipeline_stage` | 流水线阶段切换 | `{task_id, stage, status, label, timestamp}` |
| `code_preview` | 代码 Diff 生成 | `{task_id, project_id, diff, timestamp}` |
| `agent_update` | Agent 状态变更 | `{id, status, current_task_id, current_task_title}` |
| `review_update` | 审查记录变更 | `{id, task_id, project_id, status}` |
| `quality_gate_update` | 确定性门禁进度 | `{id, task_id, project_id, status, checks}` |
| `file_change` | 文件变更通知 | `{project_id}` |

## 记忆系统

ChromaDB 驱动的四层向量记忆，按“任务 → Agent → 项目 → 全局”的顺序检索：

| 层级 | 作用域 | 存储内容 |
|------|--------|----------|
| **短期** | 单个任务会话 | 任务执行过程中的进度、决策、错误 |
| **中短期** | Agent 级别 | 该 Agent 的历史经验、常见错误模式、设计偏好 |
| **长期** | 项目级别 | 项目架构知识、历史审查结论、最佳实践积累 |
| **通用** | 全局 | 可复用的跨项目模式与通用经验 |

Agent 在代码生成、审查、安全扫描各阶段都会检索相关记忆，并在完成后将有价值的发现记录到对应层级。

## API 端点

### 认证（无需 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 `{username, password, display_name?}` |
| POST | `/api/auth/login` | 登录，返回 `{token, username, display_name}` |

### 项目

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 项目列表 `?sort=created_desc` |
| POST | `/api/projects` | 创建项目 `{name, description?, workspace_name?}` |
| GET | `/api/projects/{id}` | 项目详情 |
| DELETE | `/api/projects/{id}` | 删除项目（仅所有者） |
| GET | `/api/projects/{id}/files` | 文件树 `?path=` |
| GET | `/api/projects/{id}/file` | 读文件内容 `?path=` |
| POST | `/api/projects/{id}/file` | 创建/写文件 `?path=&content=` |
| POST | `/api/projects/{id}/folder` | 创建文件夹 `?path=` |
| POST | `/api/projects/{id}/upload` | 上传文件（multipart `files` + `path`） |

### Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents` | Agent 列表 |
| POST | `/api/agents` | 创建 Agent `{name, role, model?, system_prompt?, runner_type?}` |
| DELETE | `/api/agents/{id}` | 删除 Agent |
| GET | `/api/agents/check-runner` | 检测 CLI 可用性 `?runner_type=claude_code` |
| GET | `/api/models` | 可用模型列表 |

### 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects/{id}/tasks` | 项目任务列表 `?sort=&archived=` |
| POST | `/api/projects/{id}/tasks` | 创建任务 `{title, description?, agent_id, approval_percent?}` |
| GET | `/api/projects/{id}/tasks/{tid}` | 任务详情（含关联审查记录） |
| GET | `/api/tasks` | 全局任务列表 |
| POST | `/api/projects/{id}/tasks/{tid}/archive` | 归档任务 |
| POST | `/api/projects/{id}/tasks/{tid}/unarchive` | 恢复归档 |
| GET | `/api/projects/{id}/tasks/{tid}/quality-gate` | 获取最近一次确定性门禁结果 |
| DELETE | `/api/projects/{id}/tasks/{tid}` | 删除任务 |

### 审查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects/{id}/reviews` | 项目审查列表 |
| GET | `/api/reviews/{id}` | 审查详情 |
| GET | `/api/reviews/{id}/quality-gate` | 获取该轮审查对应的确定性门禁结果 |
| POST | `/api/reviews/{id}/rerun-quality-gate` | 平台环境修复后对原提交重新执行门禁 |
| POST | `/api/reviews/{id}/approve` | 通过 → 合并到 master |
| POST | `/api/reviews/{id}/reject` | 驳回并反馈 → Agent 重新执行 `{feedback}` |
| POST | `/api/reviews/{id}/reject-quality-gate` | 将确定性检查失败明细打回 Agent |
| POST | `/api/reviews/{id}/close` | 结束审查（终止，不重跑） |
| GET | `/api/reviews/pending-count` | 待审查数量 `?project_id=N` |

### 版本

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects/{id}/versions` | 版本历史列表 |
| POST | `/api/projects/{id}/versions/{vid}/rollback` | 回退到指定版本 |

### 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 读取当前配置（敏感字段脱敏） |
| POST | `/api/settings` | 更新配置项 `{key, value}` → 写入 `.env` |

## 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | 登录/注册 | 未登录时自动跳转 |
| `/dashboard` | 项目看板 | 统计卡片 + 项目网格 + 创建/删除项目 |
| `/files` | 文件管理器 | 文件树 + Monaco Editor + 上传/删除 |
| `/agents` | Agent 池 | Agent 列表 + 创建 Agent + 模型检测 |
| `/tasks` | 任务列表 | 任务列表 + 详情 + 流水线阶段 + 时间线 + 审查决策 |
| `/reviews` | 审查记录 | 审查列表 + Diff 查看器 + Markdown 报告 |
| `/versions` | 版本历史 | 版本时间线 + 回退操作 |
| `/settings` | 系统设置 | API Key / 端点 / 工作空间配置 |

## 数据库迁移

ORM 模型变更后（新增列/表），需要删除 `data.db` 后重启：

```bash
del backend\data.db          # Windows
# rm backend/data.db          # Linux/Mac
python -m uvicorn app.main:app --port 8000
```

SQLAlchemy 的 `create_all()` 仅创建不存在的表，不会自动迁移已有表结构。

## 架构要点

### 线程安全的 WebSocket 广播

`broadcast_sync()` 处理两种调用上下文：
- **主线程**（请求处理器）：`loop.create_task()` — 非阻塞
- **后台线程**（agent_runner）：`asyncio.run_coroutine_threadsafe()` — 安全跨线程

### Git 分支隔离

每个任务的 Agent 修改在独立分支 `task/{task_id}` 上进行，与 master 完全隔离。通过后才合并，驳回/结束后清理分支。

### 流水线后台执行

Agent 流水线通过 FastAPI 后台任务在线程池中执行，不阻塞事件循环。驳回反馈的重跑使用 daemon 线程触发。

### 多引擎支持

通过 Runner 工厂模式支持三种执行后端。每个 Runner 实现统一接口，流线编排器不感知具体执行引擎。

## 许可

MIT
