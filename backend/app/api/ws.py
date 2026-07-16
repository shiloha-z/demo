"""WebSocket connection manager and endpoint for real-time push.

Usage:
    from app.api.ws import broadcast_sync
    broadcast_sync("task_update", {"id": 1, "status": "running"})
"""

import asyncio
import json
import logging
from concurrent.futures import Future
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import JWTError, jwt

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import User, Project, ProjectMember

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# ── Connection Manager ─────────────────────────────────────────────────

class ConnectionManager:
    """Track connected WebSocket clients and broadcast messages.

    Thread-safe: broadcast_sync() can be called from any thread.
    Maps user_id to connection info for online-user tracking.
    """

    def __init__(self):
        # user_id -> {"ws": WebSocket, "username": str, "display_name": str}
        self._clients: dict[int, dict] = {}
        # user_id -> project_id (which project the user is currently viewing)
        self._user_project: dict[int, int] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    async def connect(self, ws: WebSocket, user_id: int, username: str, display_name: str) -> None:
        await ws.accept()
        self._clients[user_id] = {"ws": ws, "username": username, "display_name": display_name}
        if self._main_loop is None:
            self._main_loop = asyncio.get_running_loop()
        logger.info(f"WS client connected: {username} (total: {len(self._clients)})")

    def disconnect(self, user_id: int) -> None:
        removed = self._clients.pop(user_id, None)
        if removed:
            logger.info(f"WS client disconnected: {removed['username']} (total: {len(self._clients)})")

    def get_online_users(self) -> list[dict]:
        """Return list of online users with id, username, display_name."""
        return [
            {"user_id": uid, "username": info["username"], "display_name": info["display_name"]}
            for uid, info in self._clients.items()
        ]

    def is_user_online(self, user_id: int) -> bool:
        return user_id in self._clients

    def set_user_project(self, user_id: int, project_id: int) -> None:
        """Record which project a user is currently viewing."""
        self._user_project[user_id] = project_id

    def get_user_project(self, user_id: int) -> int | None:
        """Get the project a user is currently viewing."""
        return self._user_project.get(user_id)

    def get_online_users_in_project(self, project_id: int) -> list[dict]:
        """Return list of online users currently viewing the given project."""
        return [
            {"user_id": uid, "username": info["username"], "display_name": info["display_name"]}
            for uid, info in self._clients.items()
            if self._user_project.get(uid) == project_id
        ]

    async def _broadcast_to_project_async(self, project_id: int, event_type: str, data: dict) -> None:
        """Send a typed event to all clients currently viewing the given project."""
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead: list[int] = []
        for uid, info in self._clients.items():
            if self._user_project.get(uid) != project_id:
                continue
            try:
                await info["ws"].send_text(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(uid)

    def broadcast_to_project(self, project_id: int, event_type: str, data: dict) -> Future | None:
        """Thread-safe project-scoped broadcast."""
        if self._main_loop is None or self._main_loop.is_closed():
            logger.warning("WS broadcast skipped — no main loop")
            return None
        return asyncio.run_coroutine_threadsafe(
            self._broadcast_to_project_async(project_id, event_type, data),
            self._main_loop,
        )

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def _broadcast_async(self, event_type: str, data: dict) -> None:
        """Internal: send a typed event to all connected clients."""
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead: list[int] = []
        for uid, info in self._clients.items():
            try:
                await info["ws"].send_text(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(uid)

    async def _send_to_user_async(self, user_id: int, event_type: str, data: dict) -> bool:
        """Send a message to a specific user. Returns True if sent."""
        info = self._clients.get(user_id)
        if not info:
            return False
        try:
            message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
            await info["ws"].send_text(message)
            return True
        except Exception:
            self.disconnect(user_id)
            return False

    def broadcast(self, event_type: str, data: dict) -> Future | None:
        """Thread-safe broadcast. Schedules the send on the main event loop."""
        if self._main_loop is None or self._main_loop.is_closed():
            logger.warning("WS broadcast skipped — no main loop")
            return None
        return asyncio.run_coroutine_threadsafe(
            self._broadcast_async(event_type, data),
            self._main_loop,
        )


# Singleton
manager = ConnectionManager()


def broadcast_sync(event_type: str, data: dict) -> None:
    """Thread-safe broadcast. Works from both main thread and background threads."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager._broadcast_async(event_type, data))
    except RuntimeError:
        fut = manager.broadcast(event_type, data)
        if fut:
            try:
                fut.result(timeout=10)
            except Exception:
                pass
    except Exception:
        logger.exception(f"WS broadcast failed: {event_type}")


def broadcast_sync_to_project(project_id: int, event_type: str, data: dict) -> None:
    """Thread-safe project-scoped broadcast. Works from both main thread and background threads."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager._broadcast_to_project_async(project_id, event_type, data))
    except RuntimeError:
        fut = manager.broadcast_to_project(project_id, event_type, data)
        if fut:
            try:
                fut.result(timeout=10)
            except Exception:
                pass
    except Exception:
        logger.exception(f"WS project broadcast failed: {event_type}")


# ── Helpers ────────────────────────────────────────────────────────────

def _decode_token(token: str) -> dict | None:
    """Validate JWT and return payload dict or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except (JWTError, ValueError, TypeError):
        return None


# ── WebSocket endpoint ─────────────────────────────────────────────────

@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    """WebSocket connection endpoint. Auth via query-string token."""
    payload = _decode_token(token)
    if payload is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    user_id = int(payload.get("sub"))
    username = payload.get("username", "")
    display_name = payload.get("display_name", "")

    # If JWT doesn't carry user info (old token), look up from DB
    if not display_name:
        try:
            db = SessionLocal()
            user = db.query(User).get(user_id)
            if user:
                username = user.username
                display_name = user.display_name or user.username
            db.close()
        except Exception:
            pass
    if not display_name:
        username = f"user_{user_id}"
        display_name = username

    # Check if user already has a connection (reconnect scenario)
    was_online = manager.is_user_online(user_id)
    if was_online:
        manager.disconnect(user_id)  # Remove old connection

    await manager.connect(ws, user_id, username, display_name)

    # Send connected confirmation to the user (no global broadcast until they join a project)
    await ws.send_text(json.dumps({
        "type": "connected",
        "data": {"user_id": user_id, "online_users": manager.get_online_users()}
    }))
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            else:
                # Handle incoming client messages
                try:
                    msg = json.loads(data)
                    msg_type = msg.get("type")

                    if msg_type == "join_project":
                        project_id = msg.get("project_id")
                        if project_id is not None:
                            project_id = int(project_id)
                            db = SessionLocal()
                            try:
                                project = db.query(Project).filter(Project.id == project_id).first()
                                member = db.query(ProjectMember).filter(
                                    ProjectMember.project_id == project_id,
                                    ProjectMember.user_id == user_id,
                                ).first()
                                if project and (project.owner_id == user_id or member):
                                    manager.set_user_project(user_id, project_id)
                                    broadcast_sync_to_project(project_id, "user_online", {
                                        "user_id": user_id, "username": username, "display_name": display_name,
                                        "online_users": manager.get_online_users_in_project(project_id),
                                    })
                            finally:
                                db.close()

                    elif msg_type == "typing":
                        project_id = manager.get_user_project(user_id)
                        if project_id is not None:
                            broadcast_sync_to_project(project_id, "user_typing", {
                                "user_id": user_id,
                                "username": username,
                                "display_name": display_name,
                                "project_id": project_id,
                                "typing": msg.get("typing", True),
                            })

                except (json.JSONDecodeError, KeyError):
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        # Broadcast offline to the project the user was in
        user_project = manager.get_user_project(user_id)
        manager.disconnect(user_id)
        if user_project is not None:
            broadcast_sync_to_project(user_project, "user_offline", {
                "user_id": user_id, "username": username, "display_name": display_name,
                "online_users": manager.get_online_users_in_project(user_project),
            })
