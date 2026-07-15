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
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

# ── Client (lazy init) ───────────────────────────────────────────────────

_client: Optional[chromadb.Client] = None


def _get_client() -> chromadb.Client:
    """Lazy-init ChromaDB persistent client."""
    global _client
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


def _get_or_create(name: str):
    client = _get_client()
    try:
        return client.get_collection(name)
    except Exception:
        return client.create_collection(name)


# ── Public API ───────────────────────────────────────────────────────────

def add_task_memory(task_id: int, doc: str, metadata: dict | None = None) -> str:
    """Record a step/observation during task execution."""
    col = _get_or_create(_task_collection(task_id))
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    ts = datetime.now(timezone.utc).isoformat()
    count = col.count()
    uid = f"t{task_id}_{count + 1}"
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
    logger.debug(f"Task memory [{uid}]: {doc[:80]}...")
    return uid


def add_project_memory(project_id: int, doc: str, metadata: dict | None = None) -> str:
    """Record project-level knowledge (e.g. review feedback patterns)."""
    col = _get_or_create(_project_collection(project_id))
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    ts = datetime.now(timezone.utc).isoformat()
    count = col.count()
    uid = f"p{project_id}_{count + 1}"
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
    logger.debug(f"Project memory [{uid}]: {doc[:80]}...")
    return uid


def add_global_memory(doc: str, metadata: dict | None = None) -> str:
    """Record a global pattern or lesson learned."""
    col = _get_or_create(GLOBAL_COLLECTION)
    meta = metadata or {}
    meta.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    count = col.count()
    uid = f"g_{count + 1}"
    col.add(documents=[doc], metadatas=[meta], ids=[uid])
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


# ── Internal helpers ─────────────────────────────────────────────────────

def _search(collection_name: str, query: str, n_results: int) -> list[str]:
    try:
        col = _get_or_create(collection_name)
        if col.count() == 0:
            return []
        results = col.query(query_texts=[query], n_results=min(n_results, col.count()))
        docs = results.get("documents", [[]])[0]
        return [d for d in docs if d]
    except Exception:
        logger.exception(f"ChromaDB search failed in {collection_name}")
        return []


def _get_recent(collection_name: str, n: int) -> list[str]:
    try:
        col = _get_or_create(collection_name)
        if col.count() == 0:
            return []
        # Fetch all and sort by id (ids are sequential), return last n
        all_data = col.get()
        if not all_data["documents"]:
            return []
        # Sort by id, take last n
        pairs = sorted(zip(all_data["ids"], all_data["documents"]), key=lambda x: x[0])
        return [doc for _, doc in pairs[-n:]]
    except Exception:
        logger.exception(f"ChromaDB get_recent failed in {collection_name}")
        return []


# ── Lifecycle ────────────────────────────────────────────────────────────

def delete_task_memory(task_id: int) -> None:
    """Clean up task-scoped collection after task is complete/merged."""
    name = _task_collection(task_id)
    try:
        client = _get_client()
        client.delete_collection(name)
        logger.info(f"Deleted task memory collection: {name}")
    except Exception:
        pass  # collection may not exist
