# 管理后台（调试用，独立前端）

与现有 `frontend/` **完全分离**的轻量管理后台前端，零构建依赖（纯 HTML + CSS + 原生 JS），
直接调用后端无鉴权的 `/api/admin/*` 接口，用于本地调试：查看/删除账号、项目、Agent。

## 功能
- 三个分页签：账号 / 项目 / Agent
- 列表（带搜索）、详情抽屉、删除二次确认
- 删除采用与线上一致的级联清理（含物理工作目录删除）

## 启动方式

1. 先启动后端（FastAPI），确保 `/api/admin/*` 可访问（默认 `http://localhost:8000`）。
2. 在本目录起一个静态服务器（任选其一）：

   ```powershell
   # 方式 A：Python 自带（推荐，零依赖）
   python -m http.server 8080
   # 或者指定 venv 的 python
   ..\backend\venv\Scripts\python.exe -m http.server 8080
   ```

   然后浏览器打开 http://localhost:8080

> 若前端与后端不同源（跨域），把 `app.js` 顶部的 `API_BASE` 改成后端地址，
> 例如 `const API_BASE = 'http://localhost:8000'`。当前后端 `main.py` 允许
> CORS 的情况下可直接访问。

## 后端接口（无鉴权，仅本地调试）
- `GET  /api/admin/users` / `GET /api/admin/users/{id}` / `DELETE /api/admin/users/{id}`
- `GET  /api/admin/projects` / `GET /api/admin/projects/{id}` / `DELETE /api/admin/projects/{id}`
- `GET  /api/admin/agents` / `GET /api/admin/agents/{id}` / `DELETE /api/admin/agents/{id}`

## 安全提示
该路由没有任何访问控制，仅限本地调试使用。生产环境上线前请：
- 移除 `backend/app/main.py` 中的 `admin_router` 注册，或
- 在 `backend/app/api/admin.py` 中补齐 `is_admin` 校验。
