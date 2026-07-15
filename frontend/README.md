# Frontend — Multi-Agent Collaborative Review Platform

Vue 3 SPA frontend for managing AI-powered code review projects, agents, tasks, and review workflows.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | Vue 3 (Composition API + `<script setup>`) |
| Build | Vite 6 |
| Language | TypeScript |
| State | Pinia stores |
| Routing | Vue Router 4 (history mode) |
| HTTP | Axios |
| UI library | Element Plus (ElMessage, ElMessageBox, ElDialog) |
| Code editor | Monaco Editor |
| Real-time | Native WebSocket (custom Pinia store) |
| CSS | CSS custom properties — theming via `<html>` class toggle |

## Project Structure

```
frontend/
├── src/
│   ├── main.ts                    # App bootstrap, Pinia + Router install
│   ├── App.vue                    # Root: sidebar + router-view, WS connect/disconnect
│   ├── api/
│   │   └── index.ts               # Axios instance (baseURL=/api, JWT interceptor)
│   ├── router/
│   │   └── index.ts               # Route definitions + auth guard
│   ├── stores/
│   │   ├── auth.ts                # JWT token, user info, login/logout
│   │   ├── project.ts             # Projects list, currentProject, sortBy
│   │   ├── websocket.ts           # WS connection, reconnect, event subscription
│   │   └── theme.ts               # Dark/light theme toggle
│   ├── views/
│   │   ├── LoginView.vue          # Register & login form
│   │   ├── DashboardView.vue      # Project cards + create/delete + sort selector
│   │   ├── FileManagerView.vue    # File tree + Monaco code viewer + upload
│   │   ├── AgentPanelView.vue     # Agent creation + status lights
│   │   ├── TaskListView.vue       # Task list + task detail + approve/reject
│   │   ├── DiffReviewView.vue     # Review list + diff viewer + approve/reject
│   │   └── VersionHistoryView.vue # Git version timeline + rollback
│   └── components/
│       ├── ProjectSidebar.vue     # Global project selector + nav + pending review badge
│       ├── FileTree.vue           # Recursive file tree component
│       └── MonacoEditor.vue       # Monaco editor wrapper component
├── vite.config.ts                 # Vite config: host 0.0.0.0, proxy /api → backend
├── tsconfig.json
└── package.json
```

## Setup & Run

```bash
cd frontend
npm install
npm run dev
```

Starts Vite on `http://localhost:5173` (also accessible on LAN at `http://<your-ip>:5173`).

The dev server proxies `/api/*` → `http://127.0.0.1:8000` (see `vite.config.ts`). Make sure the backend is running first.

## Routing

| Path | View | Notes |
|------|------|-------|
| `/login` | LoginView | `meta.guest` — redirects to /dashboard if logged in |
| `/` | — | Redirects → `/dashboard` |
| `/dashboard` | DashboardView | Project cards, create, delete, sort |
| `/files` | FileManagerView | File tree + editor, needs selected project |
| `/agents` | AgentPanelView | Agent pool, create agents, assign tasks |
| `/tasks` | TaskListView | Task list (left) + detail with review panel (right) |
| `/reviews` | DiffReviewView | Review records (left) + diff/summary (right) |
| `/versions` | VersionHistoryView | Version timeline + rollback |

**Auth guard** (`router/index.ts`): All routes except `/login` require a JWT token in `localStorage`. Unauthenticated users are redirected to `/login`.

## State Management (Pinia Stores)

### `auth.ts`
- `token`, `username`, `displayName` — persisted to localStorage
- `isLoggedIn` — computed from token
- `setUser(data)` / `logout()` — manage auth state

### `project.ts`
- `projects` — all projects (shared across users)
- `currentProject` — the globally selected project (used by all views)
- `sortBy` — current sort preference (`created_desc` default)
- `fetchProjects(sort?)` — load with optional sort parameter
- `createProject(name, desc)` — create + prepend to list
- `setCurrentProject(project)` — set global selected project

### `websocket.ts`
- `connected` — reactive connection state
- `connect()` — establishes WebSocket to `ws://<host>/api/ws?token=...`
- `disconnect()` — clean shutdown
- `on(eventType, callback)` — subscribe to event, returns unsubscribe function
- Auto-reconnect: exponential backoff (1s → 30s), max 10 attempts
- Heartbeat: 30s ping/pong
- Does NOT reconnect on auth failure (code 1008) or normal closure (1000)

### `theme.ts`
- `isDark` — persisted to localStorage
- `toggle()` — switches dark ↔ light, updates `<html>` class

## WebSocket Events

The `websocket` store dispatches these event types to subscribers:

| Event | Data | Sent When |
|-------|------|-----------|
| `task_update` | `{id, project_id, status}` | Task status changes (pending/running/completed/failed) |
| `agent_update` | `{id, status}` | Agent status changes (idle/working/done) |
| `review_update` | `{id, task_id, project_id, status}` | New review created (always status: "pending") |

**Consumers:**
- `App.vue` — connects on mount, disconnects on unmount
- `ProjectSidebar.vue` — listens for `review_update`, refreshes pending badge count
- `AgentPanelView.vue` — listens for `agent_update`, updates agent status lights
- `TaskListView.vue` — listens for `task_update`, refreshes task list + detail

## Global Project Selection Pattern

The `ProjectSidebar` has a `<select>` at the top bound to `store.currentProject`. All views use `store.currentProject` via computed properties. When the user switches projects:
1. All views watch `store.currentProject?.id` with `{ immediate: true }` and reload their data
2. FileManager, TaskListView, DiffReviewView, VersionHistoryView all auto-refresh on project change

## API Client (`api/index.ts`)

- `baseURL: '/api'` — relative, proxied by Vite to backend
- JWT token auto-attached via request interceptor
- 401 auto-logout with guard against redirect loops

## Theme System

CSS custom properties defined globally. Theme toggle in `theme.ts` adds/removes `class="dark"` on `<html>`. Components use `var(--foreground)`, `var(--surface)`, etc. for automatic light/dark adaptation.

Key variables: `--foreground`, `--muted-foreground`, `--surface`, `--surface-hover`, `--surface-selected`, `--surface-border`, `--primary`, `--primary-foreground`, `--success`, `--warning`, `--danger`, `--font-sans`, `--font-mono`, `--radius-sm/md/lg`.

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| vue | ^3.5 | Framework |
| vue-router | ^4.6 | Client-side routing |
| pinia | ^3.0 | State management |
| axios | ^1.18 | HTTP client |
| element-plus | — | UI components (ElMessage, ElMessageBox, ElDialog) |
| monaco-editor | ^0.55 | Code editor |
| vite | ^8.1 | Build tool |
| typescript | ~6.0 | Type checking |

## Dev Notes

- Vite proxy handles `/api` → backend, including WebSocket upgrade (`ws: true` in proxy config)
- `MonacoEditor.vue` wraps Monaco with language detection from file extension
- `FileTree.vue` is a recursive component: folders as expandable nodes, files as clickable items
- All project-scoped views follow the same pattern: `watch(store.currentProject.id, loadData, { immediate: true })`
- The sidebar pending badge calls `GET /api/reviews/pending-count?project_id=N` and updates via WebSocket
