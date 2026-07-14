多 Agent 协作审查平台 — 整体设计
一、系统架构

┌─────────────────────────────────────────────────────────────────┐
│                      浏览器 (Vue 3)                              │
│  项目看板 │ 文件管理器 │ Diff审查器 │ Agent对话面板 │ 代码查看器    │
└──────┬──────────────┬──────────────┬────────────────────────────┘
       │ HTTP REST    │ WebSocket    │
       ▼              ▼              │
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI 后端 (Python)                         │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ 用户认证  │ │ 项目管理  │ │ Agent管理 │ │ 文件管理  │           │
│  │ (JWT)    │ │ CRUD     │ │ 任务指派  │ │ WebSocket│           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │              审查流水线服务                        │           │
│  │  Agent提交 → 多Agent审查 → 汇总 → 人工审查 → Commit │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌────────────────┐  ┌────────────────────┐                      │
│  │ GitPython      │  │ AgentRunner        │                      │
│  │ (版本管理)     │  │ (调用 CrewAI)      │                      │
│  └────────────────┘  └────────────────────┘                      │
└──────────────┬───────────────────────────────────────────────────┘
               │ Python 函数调用（同进程，简化部署）
               ▼
┌──────────────────────────────────────────────────────────────────┐
│                   CrewAI Agent 层                                │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ CodeGenAgent    │  │ ReviewAgent  │  │ SecurityAgent    │   │
│  │ (代码生成)      │  │ (代码审查)   │  │ (安全检查)       │   │
│  └─────────────────┘  └──────────────┘  └──────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  自定义 Tools                                     │           │
│  │  文件读写 │ Git Diff │ Chroma记忆检索              │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  记忆系统 (Chroma向量库)                          │           │
│  │  短期：会话上下文 │ 中期：Agent经验 │ 长期：项目知识│           │
│  └──────────────────────────────────────────────────┘           │
└──────────────┬───────────────────────────────────────────────────┘
               │ OpenAI-compatible API
               ▼
         ┌──────────┐
         │ DeepSeek │
         └──────────┘
二、核心数据流
主流程：用户指派任务 → Agent 生成代码 → 审查 → 合并

用户创建任务
    │
    ▼
CrewAI CodeGenAgent 生成代码
    │
    ▼
GitPython 生成 diff
    │
    ▼
多 Agent 审查流水线 (Sequential)
    ├── ReviewAgent: 检查逻辑、风格、bug
    ├── SecurityAgent: 检查安全漏洞
    └── 汇总审查报告
    │
    ▼
WebSocket 推送给前端 → Diff 审查器展示
    │
    ├── 人点击"通过" → GitPython commit → 版本快照 → 文件管理器刷新
    │
    └── 人点击"驳回" → 反馈发回 Agent → 修改 → 重新审查
实时同步流

Agent 状态变化 / 文件变更
    │
    ▼
FastAPI WebSocket Manager
    │
    ▼
广播给项目内所有在线用户
    ├── 文件树更新
    ├── Agent 状态变化 (idle → working → done)
    └── 审查状态变化
三、数据库表设计（6 张表）

users                           projects
┌──────────────────┐           ┌──────────────────┐
│ id               │           │ id               │
│ username         │           │ name             │
│ password_hash    │           │ description      │
│ display_name     │           │ owner_id ────────┼──→ users.id
└──────┬───────────┘           │ workspace_path   │
       │                       └──────┬───────────┘
       │                              │
       │   agents                     │
       │  ┌──────────────────┐       │
       │  │ id               │       │
       ├──│ creator_id       │       │
       │  │ name             │       │
       │  │ role             │       │
       │  │ system_prompt    │       │
       │  │ project_id ──────┼───────┤
       │  │ status           │       │
       │  └──────┬───────────┘       │
       │         │                   │
       │   tasks │                   │
       │  ┌──────┴───────────┐      │
       │  │ id               │      │
       ├──│ agent_id         │      │
       │  │ project_id ──────┼──────┤
       │  │ title            │      │
       │  │ description      │      │
       │  │ status           │      │
       │  └──────┬───────────┘      │
       │         │                   │
       │  reviews│                   │
       │  ┌──────┴───────────┐      │
       │  │ id               │      │
       ├──│ task_id          │      │
       │  │ project_id ──────┼──────┤
       │  │ diff_content     │      │
       │  │ agent_review_sum │      │
       │  │ status           │      │
       │  │ human_feedback   │      │
       │  └──────┬───────────┘      │
       │         │                   │
       │ versions│                   │
       │  ┌──────┴───────────┐      │
       │  │ id               │      │
       │  │ project_id ──────┼──────┘
       │  │ commit_hash      │
       │  │ commit_message   │
       │  │ review_id        │
       └──│ created_at       │
          └──────────────────┘
四、API 设计
REST APIs

POST   /api/auth/register         注册
POST   /api/auth/login            登录 → 返回 JWT

GET    /api/projects              项目列表
POST   /api/projects              创建项目
GET    /api/projects/{id}         项目详情

GET    /api/projects/{id}/agents  Agent 列表
POST   /api/projects/{id}/agents  创建 Agent
DELETE /api/projects/{id}/agents/{aid}  删除 Agent

GET    /api/projects/{id}/tasks   任务列表
POST   /api/projects/{id}/tasks   创建任务 → 触发 Agent 执行

GET    /api/projects/{id}/reviews 审查记录列表
GET    /api/reviews/{rid}         审查详情（含 diff）
POST   /api/reviews/{rid}/approve   人工通过
POST   /api/reviews/{rid}/reject    人工驳回（含反馈）

GET    /api/projects/{id}/files   文件树（GET 参数 path）
GET    /api/projects/{id}/file?path=xxx  读取文件内容

GET    /api/projects/{id}/versions  版本列表
POST   /api/projects/{id}/versions/{vid}/rollback  回退版本
WebSocket

ws://localhost:8000/ws/{project_id}
  → 推送: agent_status, file_change, review_update, task_update
五、Agent 流水线设计（CrewAI）
Agent 角色定义

# Code Generator Agent
code_gen_agent = Agent(
    role="代码工程师",
    goal="根据任务描述生成代码并写入文件",
    tools=[FileReadTool(), FileWriteTool(), GitDiffTool()],
)

# Code Reviewer Agent
code_review_agent = Agent(
    role="代码审查员",
    goal="审查代码质量：逻辑是否正确、命名是否清晰、是否有潜在 bug",
    tools=[FileReadTool(), MemorySearchTool()],
)

# Security Reviewer Agent
security_agent = Agent(
    role="安全审查员",
    goal="检查代码安全漏洞：注入、越权、敏感信息泄露",
    tools=[FileReadTool(), MemorySearchTool()],
)

# Summarizer Agent
summarizer_agent = Agent(
    role="审查汇总员",
    goal="汇总各审查 Agent 的意见，生成统一的审查报告",
)
审查流水线（Sequential Process）

Task 输入
    │
    ▼
CodeGenAgent ──生成代码──→ 文件变更
    │
    ▼
[ReviewAgent, SecurityAgent] ──并行审查──→ 审查意见
    │
    ▼
SummarizerAgent ──汇总──→ 审查报告
    │
    ▼
输出：diff + 审查报告 → 存入 Review 表 → WebSocket 推前端
六、三层记忆设计

┌─────────────────────────────────────────────┐
│ 短期记忆（会话上下文）                        │
│ 存储：当前 Task 执行过程（内存）              │
│ 内容：Agent 对话历史、中间输出                │
│ 生命周期：单个 Task 结束后清空                │
├─────────────────────────────────────────────┤
│ 中期记忆（Agent 个人经验）                    │
│ 存储：Chromadb collection: agent_{id}        │
│ 内容：该 Agent 过去的成功/失败案例、偏好      │
│ 检索：任务开始时加载相关经验                  │
├─────────────────────────────────────────────┤
│ 长期记忆（项目级知识库）                      │
│ 存储：Chromadb collection: project_{id}      │
│ 内容：代码规范、架构决策(ADR)、API 文档       │
│ 来源：用户上传 or Agent 自动提取              │
│ 检索：所有 Agent 共享，任务执行时检索         │
└─────────────────────────────────────────────┘
七、前端页面设计
整体布局

┌─────────────────────────────────────────────────────┐
│  顶部导航栏：项目名 | 用户头像                        │
├────────────┬──────────────────────────────────────────┤
│  左侧边栏  │  主内容区                                │
│            │                                          │
│  · 项目看板│  ┌ 页面标题 ───────────────────────────┐ │
│  · 文件管理│  │                                       │ │
│  · Agent池 │  │   具体页面内容                        │ │
│  · 任务列表│  │                                       │ │
│  · 审查记录│  └─────────────────────────────────────┘ │
│  · 版本历史│                                          │
│            │                                          │
└────────────┴──────────────────────────────────────────┘
5 个页面
页面	功能	核心组件
项目看板	总览：Agent 状态、任务统计、最近审查	el-card、el-statistic、el-timeline
文件管理器	真实文件树、文件内容查看（只读）	el-tree、Monaco Editor (readOnly)
Agent 对话面板	创建 Agent、指派任务、查看 Agent 对话流	el-form、el-chat-message
Diff 审查器	并排 Diff 视图、审查意见、通过/驳回按钮	Monaco Editor (diff mode)、el-comment
版本历史	版本列表、回退按钮	el-timeline、el-table
八、项目文件结构

agent-collaboration-platform/
│
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/
│   │   │   ├── DashboardView.vue       # 项目看板
│   │   │   ├── FileManagerView.vue     # 文件管理器
│   │   │   ├── AgentPanelView.vue      # Agent 对话面板
│   │   │   ├── DiffReviewView.vue      # Diff 审查器
│   │   │   └── VersionHistoryView.vue  # 版本历史
│   │   ├── components/
│   │   │   ├── ProjectSidebar.vue      # 左侧边栏
│   │   │   ├── FileTree.vue            # 文件树
│   │   │   ├── MonacoDiff.vue          # Monaco Diff 封装
│   │   │   └── AgentChat.vue           # Agent 对话组件
│   │   ├── stores/                     # Pinia 状态
│   │   │   ├── auth.ts
│   │   │   ├── project.ts
│   │   │   └── websocket.ts
│   │   ├── api/                        # HTTP 请求封装
│   │   │   └── index.ts
│   │   └── router/
│   │       └── index.ts
│   └── package.json
│
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── main.py              # 入口：CORS、路由注册、WebSocket
│   │   ├── core/
│   │   │   ├── config.py        # 配置
│   │   │   ├── database.py      # SQLAlchemy + SQLite
│   │   │   └── auth.py          # JWT
│   │   ├── models/
│   │   │   └── models.py        # 6 张表
│   │   ├── api/
│   │   │   ├── auth.py          # 注册/登录
│   │   │   ├── projects.py      # 项目 CRUD
│   │   │   ├── agents.py        # Agent CRUD
│   │   │   ├── tasks.py         # 任务管理
│   │   │   ├── reviews.py       # 审查管理
│   │   │   ├── files.py         # 文件浏览
│   │   │   └── ws.py            # WebSocket
│   │   └── services/
│   │       ├── agent_runner.py  # 调用 CrewAI
│   │       ├── git_service.py   # GitPython
│   │       └── review_service.py
│   └── requirements.txt
│
├── agent_service/               # CrewAI 定义（被 backend 调用）
│   ├── crews/
│   │   └── review_pipeline.py   # 审查流水线定义
│   ├── tools/
│   │   ├── file_tools.py        # 文件读写工具
│   │   ├── git_tools.py         # Git diff 工具
│   │   └── memory_tools.py      # 记忆检索工具
│   └── memory/
│       └── memory_manager.py    # Chroma 封装
│
└── workspaces/                  # 每个项目的 Git 仓库
    └── {project_id}/
        └── ...
九、Demo 能演示的完整流程

1. 用户 A 注册登录
2. 用户 A 创建项目 "电商后台"
3. 用户 A 创建 Agent "小码"（代码生成器）
4. 用户 A 在 Agent 面板输入任务："写一个用户登录接口 login.py"
5. Agent 开始工作（状态：idle → working）
6. 30 秒后，Diff 审查器出现修改：
   ├── 并排 Diff 显示新增的 login.py
   ├── 审查意见：ReviewAgent 说命名OK、SecurityAgent 说密码未加密
   └── 用户看到审查报告
7. 用户点击"通过"，自动 commit，文件管理器出现 login.py
8. 版本历史中出现一条记录，可以回退
