"""Append-only audit ledger service.

Records the full chain of accountability: human actions, AI dispatch intents,
and the impact those actions have on the project. Designed as a thin insert
that never alters caller logic and never breaks the main flow — every write is
wrapped in try/except and uses its own short-lived session (safe to call from
background threads, the executor, and merge workers).

The ledger is append-only: rows are immutable once written, so the audit trail
itself is trustworthy. Correlation is achieved via `task_id` (and the reserved
`task_node_id` column for future finer-grained linking), letting any incident be
replayed back to "who initiated → who approved → what instruction AI ran →
what changed". New action types are registered in `audit_actions.py` so both
the backend and frontend render them without code duplication.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import (
    AuditAction,
    AuditActorType,
    AuditLog,
    Project,
    User,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    """Serialize payload/impact to a compact JSON string, tolerating non
    JSON-native types by coercing datetimes to ISO strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _actor_name(db: Session, actor_id: int | None) -> str:
    if not actor_id:
        return ""
    user = db.get(User, actor_id)
    if not user:
        return ""
    return user.display_name or user.username


def record(
    *,
    action: AuditAction,
    actor_id: int | None = None,
    actor_type: AuditActorType = AuditActorType.HUMAN,
    project_id: int | None = None,
    task_id: int | None = None,
    task_node_id: int | None = None,
    target_type: str = "",
    target_id: str | int | None = None,
    intent: str = "",
    payload: Any = None,
    impact: str = "",
    ip: str = "",
    ua: str = "",
) -> AuditLog | None:
    """Append an immutable audit entry.

    Returns the created row on success, or ``None`` if disabled / failed. All
    failures are swallowed so callers never need to guard around auditing.
    """
    if not settings.AUDIT_ENABLED:
        return None

    try:
        log = AuditLog(
            actor_id=actor_id,
            actor_type=actor_type,
            project_id=project_id,
            task_id=task_id,
            task_node_id=task_node_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else "",
            intent=intent,
            payload=_json(payload),
            impact=impact,
            ip=ip,
            ua=ua,
            created_at=_now(),
        )
        db = SessionLocal()
        try:
            db.add(log)
            db.commit()
            db.refresh(log)
            _broadcast(db, log)
            return log
        finally:
            db.close()
    except Exception:
        # Auditing must never break the caller's main flow.
        return None


def batch_record(entries: Iterable[dict]) -> None:
    """Record several audit entries in one shot (same semantics as `record`)."""
    for entry in entries:
        try:
            record(**entry)
        except Exception:
            continue


def _broadcast(db: Session, log: AuditLog) -> None:
    """Best-effort real-time push so the audit view can refresh live."""
    try:
        payload = {
            "id": log.id,
            "action": log.action.value if hasattr(log.action, "value") else log.action,
            "actor_type": log.actor_type.value if hasattr(log.actor_type, "value") else log.actor_type,
            "actor_name": _actor_name(db, log.actor_id) if log.actor_id else "",
            "project_id": log.project_id,
            "task_id": log.task_id,
            "task_node_id": log.task_node_id,
            "intent": log.intent,
            "impact": log.impact,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        if log.project_id is not None:
            from app.api.ws import broadcast_sync_to_project
            broadcast_sync_to_project(log.project_id, "audit_new", payload)
        else:
            from app.api.ws import broadcast_sync
            broadcast_sync("audit_new", payload)
    except Exception:
        pass
