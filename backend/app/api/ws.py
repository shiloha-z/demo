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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# ── Connection Manager ─────────────────────────────────────────────────

class ConnectionManager:
    """Track connected WebSocket clients and broadcast messages.

    Thread-safe: broadcast_sync() can be called from any thread.
    """

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        # Capture main loop on first connection
        if self._main_loop is None:
            self._main_loop = asyncio.get_running_loop()
        logger.info(f"WS client connected (total: {len(self._connections)})")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(f"WS client disconnected (total: {len(self._connections)})")

    async def _broadcast_async(self, event_type: str, data: dict) -> None:
        """Internal: send a typed event to all connected clients."""
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast(self, event_type: str, data: dict) -> Future | None:
        """Thread-safe broadcast. Schedules the send on the main event loop.

        Returns a Future, or None if no main loop is available.
        """
        if self._main_loop is None or self._main_loop.is_closed():
            logger.warning("WS broadcast skipped — no main loop")
            return None
        return asyncio.run_coroutine_threadsafe(
            self._broadcast_async(event_type, data),
            self._main_loop,
        )

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Singleton
manager = ConnectionManager()


def broadcast_sync(event_type: str, data: dict) -> None:
    """Sync wrapper for background threads (e.g. agent_runner).

    Uses the main event loop to send to all WebSocket clients.
    Safe to call from any thread.
    """
    try:
        fut = manager.broadcast(event_type, data)
        if fut:
            fut.result(timeout=5)
    except Exception:
        logger.exception(f"WS broadcast failed: {event_type}")


# ── Helpers ────────────────────────────────────────────────────────────

async def _get_user_from_ws(token: str) -> int | None:
    """Validate JWT token from query string. Returns user_id or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        return None


# ── WebSocket endpoint ─────────────────────────────────────────────────

@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    """WebSocket connection endpoint. Auth via query-string token."""
    user_id = await _get_user_from_ws(token)
    if user_id is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    await manager.connect(ws)
    try:
        # Send initial connected message
        await ws.send_text(json.dumps({"type": "connected", "data": {"user_id": user_id}}))
        # Keep alive — receive pings / detect disconnect
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        manager.disconnect(ws)
