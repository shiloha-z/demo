# AgentCollab — 多 Agent 协作审查平台 · 项目文档

> 本文档基于当前代码实际状态梳理，覆盖架构、模块、数据模型、核心机制与运行方式。
> 与顶层 `README.md` 互补：`README.md` 面向使用者，本文档面向开发者/维护者，记录了更完整的实际实现（含 skills、协作、审计、风险看板、Git worktree 隔离、投票审查、合并队列、嵌套 Agent 规划等）。

---

## 1. 项目定位

一个基于多 Agent 框架的**代码生成 + 审查 + 合并**协作平台。用户创建任务后，AI Agent 在隔离的 Git 分支上完成代码编写，随后经过 **AI 审查 → 确定性质量门禁 → 人工投票审查 → 串行合并** 的全流程，产出可合并到主分支的代码变更与结构化审查报告。

核心链路：

```
创建任务 → Agent 在隔离 worktree 写代码 → AI 审查/安全扫描/汇总
        → 确定性质量门禁（七项阻断检查）→ 人工投票（达到法定票数）
        → 项目级合并队列串行集成 → 版本记录（支持回退）
```

---

## 2. 技术栈

### 后端（`backend/`）

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI 0.115（Python 3.12） |
| 数据库 | SQLite + SQLAlchemy 2.0 ORM |
| 认证 | JWT（python-jose）+ PBKDF2 密码哈希（hashlib） |
| 实时推送 | FastAPI 原生 WebSocket |
| Git 操作 | GitPython 3.1（worktree 隔离） |
| Agent 引擎 | CrewAI 0.80 / Claude Code CLI / OpenCode CLI |
| LLM | DeepSeek API（OpenAI 兼容协议） |
| 向量记忆 | ChromaDB 0.5（四层分层记忆） |
| 质量门禁运行时 | pytest / pytest-cov / pip-audit + 内置静态规则 |
| 中文拼音 | pypinyin（工作区/分支名规范化） |

### 前端（`frontend/`）

| 组件 | 技术 |
|------|------|
| 框架 | Vue 3（Composition API + `<script setup>`） |
| 语言 | TypeScript |
| 构建 | Vite 8 |
| UI 库 | TDesign Vue Next |
| 状态管理 | Pinia |
| 路由 | Vue Router 4 |
| 编辑器 | Monaco Editor |
| Markdown | marked（GFM） |

---

## 3. 目录结构（实际）

```
demo/
├── backend/
│   ├── app/
│   │   ├── main.py                  # 入口：lifespan(init_db + 恢复合并队列)、路由注册、健康检查、UTF-8 强制
│   │   ├── api/                     # 17 个路由模块（见 §5）
│   │   │   ├── auth.py projects.py agents.py skills.py tasks.py reviews.py
│   │   │   ├── versions.py models.py settings.py chat.py members.py
│   │   │   ├── messages.py audit.py risk_dashboard.py admin.py ws.py
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings（.env 加载，含并发/门禁配置）
│   │   │   ├── database.py          # SQLAlchemy 引擎 + init_db()
│   │   │   └── auth.py              # 密码哈希 + JWT
│   │   ├── models/models.py         # 全部 ORM 表（见 §4）
│   │   └── services/                # 11 个服务模块（见 §6）
│   │       ├── agent_runner.py execution_service.py merge_service.py
│   │       ├── quality_gate_service.py git_service.py memory_service.py
│   │       ├── audit_service.py audit_actions.py message_service.py
│   │       └── skillhub_service.py
│   ├── agent_service/
│   │   ├── runners/                 # base / factory / crewai / claude / opencode / tool_adapters
│   │   ├── planner.py               # 嵌套 Agent 规划：plan_task + collect_project_context
│   │   └── tools/                   # file_tools / git_tools / memory_tools
│   ├── requirements.txt  .env(.example)  data.db(自动)  chroma_data/(自动)
├── frontend/
│   └── src/
│       ├── main.ts  App.vue  style.css  styles/
│       ├── api/index.ts             # Axios 实例 + 拦截器（全局 timeout 30s）
│       ├── router/index.ts          # 路由 + 登录守卫
│       ├── stores/                  # auth project websocket theme message notification audit
│       ├── utils/markdown.ts
│       ├── components/              # 10 个组件（见 §7）
│       └── views/                   # 13 个页面（见 §7）
├── workspaces/                      # 各项目 Git 工作区（运行时生成）
├── README.md
├── IMPLEMENTATION_PLAN.md
└── PROJECT_DOCUMENTATION.md         # 本文档
```

> 注意：`agent_service/` 位于 `backend/` 内部（与 `app/` 同级），作为同进程子模块被调用。

---

## 4. 数据模型（`app/models/models.py`）

| 表 | 关键字段 | 说明 |
|----|----------|------|
| `users` | `username(唯一) password_hash display_name email phone bio avatar_url` | 用户 |
| `projects` | `project_id(规范ID唯一) name owner_id workspace_path` | 项目 |
| `project_members` | `project_id user_id role(OWNER/ADMIN/MEMBER)` | 成员与角色（唯一约束） |
| `join_requests` | `project_id user_id username status(PENDING/APPROVED/REJECTED)` | 加入申请 |
| `agents` | `role(code_gen/reviewer/security) model runner_type system_prompt` `enable_planning max_subtasks` | Agent 定义，含**嵌套规划开关** |
| `skills` | `name description prompt_content source source_id source_url` | 技能（本地/外部 SkillHub 导入） |
| `tasks` | 见下 | 任务（核心，含嵌套任务树） |
| `quality_gate_runs` | `task_id review_id attempt commit_hash status results_json summary` | 门禁执行（不可变记录） |
| `reviews` | `task_id project_id diff_content agent_review_summary status human_feedback` | AI 审查结果 |
| `review_rounds` | `review_id(唯一) required_approvals veto_on_reject` | 投票配置 |
| `review_reviewers` | `review_id user_id` | 被指派的投票人（唯一约束） |
| `review_votes` | `review_id user_id decision(approve/reject) comment` | 投票（按 user 覆盖更新，唯一约束） |
| `versions` | `project_id commit_hash commit_message review_id` | 合并版本历史 |
| `chat_messages` | `user_id project_id recipient_id message file_url/name/type/size` | 团队/私聊消息 |
| `messages` / `message_reads` | `category level title body link read` / `message_id user_id read_at` | 消息中心 + 每用户已读回执 |
| `audit_logs` | `actor_id actor_type(human/agent/system) action target_type intent payload impact` | Append-only 全链路审计账本 |

### `tasks` 表关键字段

- **基础**：`agent_id`、`reviewer_agent_id`、`security_agent_id`（可覆盖内置审查/安全子 Agent）、`project_id`、`title`、`description`、`approval_percent`、`status`、`archived`
- **Git 隔离**：`branch_name`、`worktree_path`、`base_commit`、`merge_error`、`merge_attempts`、`merge_queued_at`、`started_at`、`completed_at`
- **嵌套任务树**：`parent_task_id`（自引用）、`plan_json`、`subtask_count`、`subtask_done`、`children` 关系

### 任务状态机（`TaskStatus`）

```
PENDING → RUNNING → REVIEWING → MERGE_QUEUED → INTEGRATING → APPROVED
                        │              │            │
                        │              │            ├→ CONFLICT_RESOLUTION → (自动解决/失败)
                        │              │            └→ MERGE_BLOCKED
                        ├→ REJECTED（人工驳回，Agent 重新执行）
                        └→ FAILED
PAUSED（暂停）
── 嵌套规划 ──
PLANNING（父任务拆解中）→ SUBTASK_RUNNING（子任务执行中）
SUBTASK_DONE（子任务完成，并入父分支，不单独审核）
```

---

## 5. 后端 API（`app/api/`）

| 模块 | 前缀 | 主要端点 |
|------|------|----------|
| `auth.py` | `/api/auth` | `register` `login` `GET/PUT profile` 头像上传/读取 |
| `projects.py` | `/api/projects` | 项目 CRUD；文件树/读写/文件夹/上传；`join` 加入申请与审批 |
| `members.py` | `/api` | `/projects/{id}/members` 增删改查、`transfer` 转让 owner |
| `agents.py` | `/api/agents` | Agent CRUD、导出/导入、`check-runner` 检测 CLI 可用性 |
| `skills.py` | `/api/skills` | 本地技能 CRUD；`/skillhub/*` 外部技能搜索/目录/导入 |
| `tasks.py` | `/api/projects/{pid}/tasks` | 任务 CRUD、启动/停止/恢复/归档、`plan` 嵌套规划、`subtasks`、任务文件、批量删除 |
| `reviews.py` | `/api` | 审查列表/详情/投票人；`vote`/`approve`/`reject`/`close`；门禁 `quality-gate`/`rerun-quality-gate`/`reject-quality-gate` |
| `versions.py` | `/api/projects/{id}/versions` | 版本列表、`rollback` 回退 |
| `models.py` | `/api` | `GET /models` 按 runner_type 返回可选模型 |
| `settings.py` | `/api` | 平台配置读写（脱敏）；`global/project/agent-memories` 记忆浏览 |
| `chat.py` | `/api` | 团队聊天消息/成员/在线状态/上传/下载 |
| `messages.py` | `/api` | 消息中心：列表、未读计数、标记已读、批量删除 |
| `audit.py` | `/api/audit` | 审计列表、`chain`（按 task 串联时间线）、`actions` 动作注册表 |
| `risk_dashboard.py` | `/api` | `GET /risk-dashboard` 聚合风险指标 |
| `admin.py` | `/api/admin` | 本地调试管理后台 |
| `ws.py` | `/api/ws` | WebSocket 实时事件通道 |

---

## 6. 后端服务层（`app/services/`）

| 服务 | 职责 |
|------|------|
| `agent_runner.py` | 流水线编排器：调用 Runner 执行 Agent，推送进度，写审查结果与记忆；含嵌套规划路径 |
| `execution_service.py` | **有界并发执行器**：`ThreadPoolExecutor` + 信号量。Agent 运行队列与项目级合并队列分离；父任务子任务用锁串行共享分支，跨父任务受并发上限约束；重启时恢复合并队列 |
| `merge_service.py` | **项目级串行集成**：合并已通过任务分支到主分支，冲突自动交给 Agent 处理（`CONFLICT_RESOLUTION`），失败标记 `MERGE_BLOCKED`，成功写 `Version` |
| `quality_gate_service.py` | **确定性质量门禁**（见 §9），fail-closed，结果不可变持久化 |
| `git_service.py` | Git 分支/worktree/提交/Diff/合并/回退封装 |
| `memory_service.py` | ChromaDB 四层记忆（见 §10） |
| `audit_service.py` / `audit_actions.py` | 审计账本写入与动作注册表 |
| `message_service.py` | 消息中心生成（任务/审查/版本/系统事件） |
| `skillhub_service.py` | 外部技能仓库（SkillHub）搜索与导入 |

---

## 7. 前端结构（`frontend/src/`）

### 页面（`views/`）

| 页面 | 说明 |
|------|------|
| `LoginView` | 登录/注册 |
| `DashboardView` | 项目看板（统计 + 项目网格） |
| `FileManagerView` | 文件树 + Monaco 编辑器 + 上传 |
| `AgentPanelView` | Agent 池：创建/管理 Agent、runner 检测 |
| `TaskListView` | 任务列表/详情/流水线/时间线/审查决策/**自主任务规划** |
| `DiffReviewView` | 审查记录：Diff + Markdown 报告 + 投票 |
| `VersionHistoryView` | 版本历史 + 回退 |
| `SkillRepositoryView` | 技能仓库（本地 + SkillHub 导入） |
| `MessagesView` | 消息中心 |
| `AuditLogView` | 审计日志/链路 |
| `RiskDashboardView` | 风险看板 |
| `ProfileView` | 个人资料 |
| `SettingsView` | 系统设置（API Key/端点/工作空间） |

### 组件（`components/`）

`ProjectSidebar` `FileTree` `MonacoEditor` `DiffViewer` `PipelineStepper` `TaskTimeline` `QualityGatePanel` `AuditChainPanel` `MemberManager` `ChatSidebar`

### 状态（`stores/`）

`auth` `project` `websocket` `theme` `message` `notification` `audit`

---

## 8. 核心机制

### 8.1 Git worktree 分支隔离

每个任务在独立分支 `task/{task_id}` 与独立 worktree 中执行，项目主工作区始终停在基线分支，仅由合并 worker 使用。任务之间完全隔离，仅审查通过并经确定性门禁后才由**项目级串行合并队列**集成到主分支；驳回/结束后清理分支。

### 8.2 有界并发与合并队列

- `execution_service` 用两个独立线程池分别处理 **Agent 运行** 与 **合并集成**，避免无限并发的模型调用。
- 同一父任务的多个子任务共享一条 worktree 分支 → 用 `_parent_run_locks` 串行；不同父任务的子任务可并行，但总量受 `AGENT_MAX_CONCURRENCY` 信号量约束。
- 应用重启时，`recover_merge_queue()` 重新入队中断的合并任务（DB 为状态唯一真相源）。

### 8.3 嵌套 Agent 任务规划（`agent_service/planner.py`）

当 Agent 开启 `enable_planning` 或用户点击「自主任务规划」时：

1. `collect_project_context(workspace)` 生成**受限的项目结构树**（忽略 `.git/node_modules/venv/__pycache__` 等，限制深度 4、条目 130）+ 技术栈线索（解析 `package.json`/`requirements.txt` 等依赖）。
2. `plan_task(...)` 把「任务描述 + 项目结构」交给 LLM，拆解为**依赖有序的子步骤**（每步具体到文件/模块与预期产物，避免空泛的纯调研步骤）。
3. 每个子步骤建一个 child 任务，串行跑在共享父分支上；父任务状态 `PLANNING → SUBTASK_RUNNING → SUBTASK_DONE`。

两个入口：`crewai_runner.py`（planning 模式）与 `POST /plan` 端点，均注入 `project_context`。

### 8.4 多引擎 Runner（`agent_service/runners/`）

`factory.get_runner(runner_type)` 按注册表懒加载分发；缺失 SDK 时给出安装提示：

| runner_type | 类型 | LLM 后端 | 适用 |
|-------------|------|----------|------|
| `crewai` | Python SDK（进程内） | DeepSeek | 低成本快速验证 |
| `claude_code` | CLI 子进程 | Anthropic Claude | 高质量生成 |
| `opencode` | CLI 子进程 | 任意 OpenAI 兼容 | 多模型灵活切换 |

CrewAI 引擎内置 4-Agent 顺序流水线：代码工程师 → 代码审查员 → 安全审查员 → 审查汇总员。

---

## 9. 确定性质量门禁（七项阻断检查）

AI 审查报告生成后，系统在任务隔离分支上执行七项 fail-closed 检查，全部通过才允许人工投通过票：

| 检查 | 执行方式 | 未通过 |
|------|----------|--------|
| 单元测试 | 管理员配置测试命令（严格模式：未配置=失败） | 阻止合并 |
| 代码格式与规范 | 内置语法/行尾空白/超长行 + 可扩展 lint | 阻止合并 |
| 静态安全扫描 | 内置 SQL/命令注入规则 + 可扩展 SAST | 阻止合并 |
| 硬编码密钥扫描 | 内置私钥/凭据规则 + 可扩展密钥扫描 | 阻止合并 |
| 依赖漏洞检查 | 管理员配置依赖审计命令（严格模式） | 阻止合并 |
| 测试覆盖率 | 管理员配置带阈值的覆盖率命令（严格模式） | 阻止合并 |
| 银行内部禁止项 | 内置敏感文件/禁止文本规则 + 可扩展 | 阻止合并 |

- 失败分两类：**代码问题**（测试/覆盖率/安全发现）可「按失败项打回 Agent」；**平台问题**（命令未配置、工具缺失）不打回 Agent，管理员修复后可对原 commit「重新检查」。
- 抑制标记：`quality-gate: allow`、`nosec`、`pragma: allowlist secret`。
- 结果、输出、耗时、失败原因持久化到 `quality_gate_runs`，并通过 WebSocket 实时展示。

门禁命令涉及服务端执行权限，只能由运维写入受控的 `backend/.env`（不可通过普通设置接口修改）：

```bash
QUALITY_GATE_UNIT_TEST_COMMAND=python -m pytest -q
QUALITY_GATE_STYLE_COMMAND=ruff check .
QUALITY_GATE_STATIC_SCAN_COMMAND=bandit -r .
QUALITY_GATE_SECRET_SCAN_COMMAND=gitleaks detect --no-git
QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND=pip-audit -r requirements.txt
QUALITY_GATE_COVERAGE_COMMAND=python -m pytest --cov=. --cov-fail-under=80
QUALITY_GATE_BANK_RULE_COMMAND=
QUALITY_GATE_FORBIDDEN_PATTERNS=TODO,FIXME
```

---

## 10. 四层向量记忆（`memory_service.py`）

ChromaDB 持久化，按「任务 → Agent → 项目 → 全局」顺序检索：

| Collection | 作用域 | 内容 |
|------------|--------|------|
| `task_memory_{task_id}` | 单次任务会话 | 执行过程中的进度、决策、错误（可清理） |
| `agent_memory_{agent_id}` | Agent 级（跨任务/项目） | 历史经验、常见错误模式、设计偏好 |
| `project_memory_{project_id}` | 项目级（跨任务） | 架构知识、历史审查结论、最佳实践 |
| `global_memory` | 全局 | 跨项目通用模式与经验 |

未安装 ChromaDB 时降级为 no-op，不影响主流程。

---

## 11. 投票制人工审查

- 每个 AI 审查结果生成一个 `review_round`，含 `required_approvals`（由任务的 `approval_percent` 换算）与 `veto_on_reject`。
- 指派的 `review_reviewers` 通过 `POST /reviews/{id}/vote` 投票（approve/reject，按用户覆盖更新）。
- 达到法定通过票数 → 任务进入 `MERGE_QUEUED`；若开启一票否决，任一 reject 即驳回。
- 合并前校验门禁通过的 commit 未被替换，防止绕过。

---

## 12. WebSocket 事件

| 事件 | 触发 |
|------|------|
| `task_update` | 任务状态变更 |
| `task_progress` | 流水线进度更新 |
| `pipeline_stage` | 流水线阶段切换 |
| `code_preview` | 代码 Diff 生成 |
| `agent_update` | Agent 状态变更 |
| `review_update` | 审查记录变更 |
| `quality_gate_update` | 门禁进度 |
| `file_change` | 文件变更通知 |

`broadcast_sync()` 兼容两种上下文：主线程用 `loop.create_task()`；后台线程用 `asyncio.run_coroutine_threadsafe()`。

---

## 13. 快速开始

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows（Linux/Mac: source .venv/bin/activate）
pip install -r requirements.txt
cp .env.example .env               # 编辑 .env，设置 DEEPSEEK_API_KEY=sk-...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API 文档：`http://localhost:8000/docs`
- 健康检查：`GET /api/health`（探测 DB / Git / ChromaDB）
- WebSocket：`ws://localhost:8000/api/ws?token=<JWT>`

### 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 数据库迁移

ORM 变更（新增列/表）后需删除 `backend/data.db` 重启（`create_all()` 只建不存在的表，不自动迁移已有结构）。

---

## 14. 环境变量（`backend/.env`）

```bash
# 数据库
DATABASE_URL=sqlite:///./data.db
# 认证
JWT_SECRET=dev-secret-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
# 工作空间
WORKSPACE_ROOT=../workspaces
# LLM
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
ANTHROPIC_API_KEY=
OPENCODE_SERVER_URL=http://localhost:36000
# 并发（execution_service）
AGENT_MAX_CONCURRENCY=...
MERGE_MAX_CONCURRENCY=...
# 质量门禁命令（见 §9，仅运维可改）
QUALITY_GATE_*=...
```

---

## 15. 已知约束与注意事项

- **规划为同步调用**：`POST /plan` 同步等待 LLM 拆解；前端对该请求已单独放宽超时至 180s，后端模型调用超时 150s，避免 axios 全局 30s 提前断开。慢模型场景可后续改为异步 + WebSocket 通知。
- **门禁严格模式**：单元测试/依赖审计/覆盖率命令未配置会判定失败（不会把「未执行」显示为「已通过」）。
- **DB 为状态唯一真相源**：执行器只调度工作，重启后按 DB 恢复合并队列。
- **同进程调用 CrewAI**：`agent_service` 作为 backend 子模块 import；后续可升级为 Celery/独立进程。
