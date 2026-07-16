# Backend — Multi-Agent Collaborative Review Platform

FastAPI backend for a CrewAI-powered code review platform with real-time WebSocket push, Git branch isolation, and DeepSeek LLM integration.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Web framework | FastAPI (Python) |
| Database | SQLite + SQLAlchemy ORM |
| Auth | JWT (jose) + PBKDF2 password hashing |
| AI pipeline | CrewAI + DeepSeek API (OpenAI-compatible) |
| Git | GitPython |
| Real-time | FastAPI native WebSocket |

## Project Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app entry, lifespan, router registration
│   ├── api/
│   │   ├── auth.py              # POST /api/auth/register, /api/auth/login
│   │   ├── projects.py          # CRUD projects + file management + file upload
│   │   ├── agents.py            # CRUD agents (code_gen / reviewer / security)
│   │   ├── tasks.py             # CRUD tasks + global task listing
│   │   ├── reviews.py           # List/get reviews, approve, reject, pending-count
│   │   ├── versions.py          # Version history list + rollback
│   │   ├── ws.py                # WebSocket endpoint + ConnectionManager
│   │   └── models.py            # GET /api/models — available LLM models list
│   ├── core/
│   │   ├── config.py            # Pydantic Settings (.env → deepseek key/url, DB, JWT)
│   │   ├── database.py          # SQLAlchemy engine, session factory, Base, init_db()
│   │   └── auth.py              # hash_password, verify_password, JWT encode/decode
│   ├── models/
│   │   └── models.py            # SQLAlchemy ORM models (User, Project, Agent, Task, Review, Version)
│   └── services/
│       ├── git_service.py       # Git operations (init, branch, commit, diff, history, rollback)
│       └── agent_runner.py      # Background task: project-level Agent pipeline execution
├── agent_service/
│   ├── crews/
│   │   └── review_pipeline.py   # CrewAI crew definition: 4 agents, 4 sequential tasks
│   └── tools/
│       ├── file_tools.py        # CrewAI tools: FileRead, FileWrite (workspace-scoped)
│       └── git_tools.py         # CrewAI tool: GitDiff
├── .env                         # DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, etc.
├── data.db                      # SQLite database (auto-created)
└── workspaces/                  # Per-project git workspaces (auto-created)
```

## Setup & Run

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: set DEEPSEEK_API_KEY=sk-...

# Run
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Run regression tests

The backend test suite uses Python's built-in `unittest` runner and does not
require an additional test dependency:

```bash
python -m unittest discover -s tests -v
```

### Required Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `DEEPSEEK_API_KEY` | (required) | Your DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API endpoint |
| `DATABASE_URL` | `sqlite:///./data.db` | SQLite path |
| `JWT_SECRET` | `dev-secret-change-in-production` | Change in prod |
| `WORKSPACE_ROOT` | `../workspaces` | Where git repos are stored |

### Database schema updates

Startup creates missing tables and applies the project's additive SQLite
migrations, so an existing `data.db` does not need to be deleted when a table
or supported column is added. Back up the database before deploying schema
changes. Renames, removals and complex constraint changes still require an
explicit versioned migration instead of the additive startup helper.

## API Endpoints

All endpoints under `/api` unless noted. Auth required (`Authorization: Bearer <token>`) except register/login.

### Auth
| Method | Path | Body | Notes |
|--------|------|------|-------|
| POST | `/api/auth/register` | `{username, password, display_name?}` | |
| POST | `/api/auth/login` | `{username, password}` | Returns `{token, username, display_name}` |

### Projects
| Method | Path | Query/Params | Notes |
|--------|------|-------------|-------|
| GET | `/api/projects` | `?sort=created_desc` | Sort: created_desc/asc, updated_desc, name_asc/desc |
| POST | `/api/projects` | `{name, description?}` | |
| GET | `/api/projects/{id}` | | |
| DELETE | `/api/projects/{id}` | | Owner only |
| GET | `/api/projects/{id}/files` | `?path=` | File tree |
| GET | `/api/projects/{id}/file` | `?path=` | Read file content |
| POST | `/api/projects/{id}/file` | `?path=&content=` | Create/write file |
| POST | `/api/projects/{id}/folder` | `?path=` | Create folder |
| POST | `/api/projects/{id}/upload` | multipart `files` + `path` | Upload files (supports multiple) |

### Agents
| Method | Path | Body | Notes |
|--------|------|------|-------|
| GET | `/api/agents` | | |
| POST | `/api/agents` | `{name, role, model?, system_prompt?}` | role: code_gen / reviewer / security |
| DELETE | `/api/agents/{id}` | | |

### Tasks
| Method | Path | Body | Notes |
|--------|------|------|-------|
| GET | `/api/projects/{id}/tasks` | | Tasks for one project |
| POST | `/api/projects/{id}/tasks` | `{title, description?, agent_id}` | Triggers background agent pipeline |
| GET | `/api/projects/{id}/tasks/{task_id}` | | Task detail + associated review |
| GET | `/api/tasks` | | Global task list (all projects) |

### Reviews
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/projects/{id}/reviews` | All reviews for a project |
| GET | `/api/reviews/{id}` | Single review detail |
| POST | `/api/reviews/{id}/approve` | Merge task branch → master, create version |
| POST | `/api/reviews/{id}/reject` | Delete task branch, discard changes |
| GET | `/api/reviews/pending-count` | `?project_id=N` optional scope |

### Versions
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/projects/{id}/versions` | Version history |
| POST | `/api/projects/{id}/versions/{vid}/rollback` | Git revert to a version |

### Models
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/models` | Available LLM model list |

### WebSocket
| Path | Auth | Notes |
|------|------|-------|
| `ws://host:8000/api/ws?token=<JWT>` | query-string JWT | Sends `connected` on connect, responds `pong` to `ping` |

**Push event types:**
- `task_update` — `{id, project_id, status}` — status: pending/running/completed/failed
- `agent_update` — `{id, status}` — status: idle/working/done
- `review_update` — `{id, task_id, project_id, status}` — status: pending

## Architecture Decisions

### Git Branch Isolation per Task

Each task execution gets its own branch `task/{task_id}`:
1. `agent_runner.py` creates the branch before running CrewAI
2. Agent changes are committed on the task branch
3. `diff_vs_master()` computes the isolated diff
4. On approve: merge task branch → master, create version
5. On reject: switch to master, delete task branch
6. After execution: always switch back to master (file manager stays clean)

### Thread-Safe WebSocket Broadcasting

`broadcast_sync()` handles two calling contexts:
- **Main thread** (request handlers): uses `loop.create_task()` — non-blocking
- **Background thread** (agent_runner): uses `asyncio.run_coroutine_threadsafe()` — safe

The ConnectionManager singleton captures the event loop on first WS connection.

### CrewAI Pipeline (Sequential)

```
CodeGen → Reviewer → Security → Summarizer
```

Each agent uses workspace-scoped tools (FileRead, FileWrite, GitDiff). The pipeline runs in a background thread via FastAPI's `BackgroundTasks` to avoid blocking the event loop.

### Database

SQLite with `check_same_thread=False` for multi-threaded access (background tasks need their own sessions via `SessionLocal()`).
