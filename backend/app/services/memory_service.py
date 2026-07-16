"""ChromaDB 三层记忆系统 — task / project / global.

Collection design:
  - task_memory_{task_id}    — 单次任务执行的上下文（任务完成后可清理）
  - project_memory_{proj_id} — 项目级别的知识积累（跨任务共享）
  - global_memory            — 跨项目的通用模式与经验

Each entry stores:
  - id:        unique key (e.g. "step_1" / "review_feedback")
  - document:  free-text content
  - metadata:  {type, source, timestamp, ...}
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

# ── ChromaDB optional import ─────────────────────────────────────────────
_chromadb_available = False
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _chromadb_available = True
except ImportError:
    logger.warning("chromadb not installed — memory service will be a no-op")

# ── Client (lazy init) ───────────────────────────────────────────────────

_client = None  # Optional[chromadb.Client]


def _get_client():
    """Lazy-init ChromaDB persistent client."""
    global _client
    if not _chromadb_available:
        return None
    if _client is None:
        persist_dir = os.path.join(os.path.dirname(__file__), "..", "..", "chroma_data")
        persist_dir = os.path.abspath(persist_dir)
        os.makedirs(persist_dir, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info(f"ChromaDB client initialized at {persist_dir}")
    return _client


# ── Collection helpers ───────────────────────────────────────────────────

def _task_collection(task_id: int) -> str:
    return f"task_memory_{task_id}"


def _project_collection(project_id: int) -> str:
    return f"project_memory_{project_id}"


GLOBAL_COLLECTION = "global_memory"

# Capacity caps — project/global collections keep only the most recent N entries;
# older entries are evicted on write to bound retrieval noise and storage growth.
PROJECT_MEMORY_CAP = 200
GLOBAL_MEMORY_CAP = 200


def _get_or_create(name: str):
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get_collection(name)
    except Exception:
        return client.create_collection(name)


def _enforce_cap(col, cap: int) -> None:
    """Evict the oldest entries (by metadata timestamp) when over `cap`.

    Ids are uuid-based (order-free), so eviction is driven by the `timestamp`
    metadata set on every write. We delete the first `total - cap` oldest.
    """
    if col is None or cap <= 0:
        return
    try:
        all_data = col.get()
        ids = all_data.get("ids", [])
        metas = all_data.get("metadatas", [])
        total = len(ids)
        if total <= cap:
            return
        # Pair each id with its timestamp (fallback: id string) and keep newest.
        def _ts(m):
            if isinstance(m, dict) and m.get("timestamp"):
                return m["timestamp"]
            return ""
        pairs = sorted(zip(ids, metas), key=lambda p: _ts(p[1]))
        stale = [pid for pid, _ in pairs[: total - cap]]
        col.delete(ids=stale)
        logger.info(f"Evicted {len(stale)} old entries from {col.name} (cap={cap})")
    except Exception:
        logger.exception(f"Failed to enforce cap on {col.name if col else '?'}")


# ── Public API ───────────────────────────────────────────────────────────

def _new_uid(prefix: str) -> str:
    """Generate a collision-free uid.

    We avoid `count()+1` style ids because ChromaDB's `count()` may include
    tombstones after deletions (observed in 1.x), which would reuse/shift ids
    and break eviction ordering. A uuid is always unique.
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def add_task_memory(task_id: int, doc: str, metadata: dict | None = None) -> str:
    """Record a step/observation during task execution."""
    col = _get_or_create(_task_collection(task_id))
    if col is None:
        return ""
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    uid = _new_uid(f"t{task_id}")
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
    logger.debug(f"Task memory [{uid}]: {doc[:80]}...")
    return uid


def add_project_memory(project_id: int, doc: str, metadata: dict | None = None) -> str:
    """Record project-level knowledge (e.g. review feedback patterns)."""
    col = _get_or_create(_project_collection(project_id))
    if col is None:
        return ""
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    uid = _new_uid(f"p{project_id}")
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
    _enforce_cap(col, PROJECT_MEMORY_CAP)
    logger.debug(f"Project memory [{uid}]: {doc[:80]}...")
    return uid


def add_global_memory(doc: str, metadata: dict | None = None) -> str:
    """Record a global pattern or lesson learned."""
    col = _get_or_create(GLOBAL_COLLECTION)
    if col is None:
        return ""
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    uid = _new_uid("g")
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
    _enforce_cap(col, GLOBAL_MEMORY_CAP)
    logger.debug(f"Global memory [{uid}]: {doc[:80]}...")
    return uid


def search_task_memory(task_id: int, query: str, n_results: int = 5) -> list[str]:
    """Semantic search within the current task's memory."""
    name = _task_collection(task_id)
    return _search(name, query, n_results)


def search_project_memory(project_id: int, query: str, n_results: int = 5) -> list[str]:
    """Semantic search across all memories in this project."""
    name = _project_collection(project_id)
    return _search(name, query, n_results)


def search_global_memory(query: str, n_results: int = 5) -> list[str]:
    """Semantic search across global (cross-project) memories."""
    return _search(GLOBAL_COLLECTION, query, n_results)


def search_all(task_id: int, project_id: int, query: str, n_results: int = 3) -> dict[str, list[str]]:
    """Search all three memory layers at once. More recent/specific layers first."""
    return {
        "task": search_task_memory(task_id, query, n_results),
        "project": search_project_memory(project_id, query, n_results),
        "global": search_global_memory(query, n_results),
    }


def get_recent_task_memories(task_id: int, n: int = 10) -> list[str]:
    """Return the n most recent task memories (no semantic search)."""
    name = _task_collection(task_id)
    return _get_recent(name, n)


def build_memory_context(project_id: int, query: str, n_results: int = 5) -> str:
    """Aggregate project + global memories into a single injectable text block.

    Used by the orchestrator to *proactively* feed historical context into the
    task prompt — so the agent starts each run with relevant prior knowledge
    rather than having to remember to search. Returns "" when no memories exist.
    """
    if not mem_ok():
        return ""

    blocks: list[str] = []
    try:
        proj = search_project_memory(project_id, query, n_results)
        if proj:
            blocks.append("【项目历史经验】\n" + "\n".join(f"- {d}" for d in proj))
    except Exception:
        logger.exception("build_memory_context: project search failed")

    try:
        glob = search_global_memory(query, n_results)
        if glob:
            blocks.append("【通用模式/经验】\n" + "\n".join(f"- {d}" for d in glob))
    except Exception:
        logger.exception("build_memory_context: global search failed")

    if not blocks:
        return ""
    return "\n\n".join(blocks)


def mem_ok() -> bool:
    """Whether the memory backend (ChromaDB) is available."""
    return _chromadb_available and _get_client() is not None


# ── Internal helpers ─────────────────────────────────────────────────────

def _search(collection_name: str, query: str, n_results: int) -> list[str]:
    if not _chromadb_available:
        return []
    try:
        col = _get_or_create(collection_name)
        if col is None or col.count() == 0:
            return []
        results = col.query(query_texts=[query], n_results=min(n_results, col.count()))
        docs = results.get("documents", [[]])[0]
        return [d for d in docs if d]
    except Exception:
        logger.exception(f"ChromaDB search failed in {collection_name}")
        return []


def _get_recent(collection_name: str, n: int) -> list[str]:
    if not _chromadb_available:
        return []
    try:
        col = _get_or_create(collection_name)
        if col is None:
            return []
        all_data = col.get()
        if not all_data.get("documents"):
            return []
        # Sort by metadata timestamp (ids are uuid-based, order-free), take last n.
        ids = all_data["ids"]
        docs = all_data["documents"]
        metas = all_data.get("metadatas", [])

        def _ts(m):
            if isinstance(m, dict) and m.get("timestamp"):
                return m["timestamp"]
            return ""
        pairs = sorted(zip(ids, docs, metas), key=lambda p: _ts(p[2]))
        return [doc for _, doc, _ in pairs[-n:]]
    except Exception:
        logger.exception(f"ChromaDB get_recent failed in {collection_name}")
        return []


# ── Lifecycle ────────────────────────────────────────────────────────────

def delete_task_memory(task_id: int) -> None:
    """Clean up task-scoped collection after task is complete/merged."""
    if not _chromadb_available:
        return
    name = _task_collection(task_id)
    try:
        client = _get_client()
        if client is None:
            return
        client.delete_collection(name)
        logger.info(f"Deleted task memory collection: {name}")
    except Exception:
        pass  # collection may not exist
