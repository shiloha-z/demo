"""Ad-hoc test for the memory-service optimizations (Step A + cap eviction).

Run from backend/:  python _memory_test.py

Validates:
  1. project/global memory capacity cap + oldest-eviction (correct seq order)
  2. build_memory_context aggregates project + global into a text block
  3. task memory add + delete lifecycle
  4. empty memory -> build_memory_context returns ''
  5. mem_ok reflects backend
"""

import os
import sys
import time
import tempfile
import shutil

import app.services.memory_service as mem


def fresh_client():
    """Reset the lazy singleton and point it at a brand-new temp dir."""
    tmp = tempfile.mkdtemp(prefix="mem_test_")
    mem._client = None

    def _patched():
        if not mem._chromadb_available:
            return None
        if mem._client is None:
            os.makedirs(tmp, exist_ok=True)
            mem._client = mem.chromadb.PersistentClient(
                path=tmp, settings=mem.ChromaSettings(anonymized_telemetry=False))
        return mem._client

    mem._get_client = _patched
    mem._client = None
    return tmp


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


print("== Test 1: capacity cap + oldest eviction (project, seq order) ==")
tmp = fresh_client()
mem.PROJECT_MEMORY_CAP = 10
PID = 999001
for i in range(15):
    mem.add_project_memory(PID, f"project memory item {i}")
    time.sleep(0.01)  # simulate realistic inter-write latency
cnt = mem._get_or_create(mem._project_collection(PID)).count()
check(f"project collection count == cap (got {cnt}, cap 10)", cnt == 10)
docs = mem._get_recent(mem._project_collection(PID), 100)
# Exact-match check (avoid substring trap: "item 1" ⊂ "item 14")
doc_set = set(docs)
check("oldest items evicted (no 'item 0'/'item 4')",
      "project memory item 0" not in doc_set and "project memory item 4" not in doc_set)
check("newest items kept (has 'item 14')", "project memory item 14" in doc_set)
check("item 5..14 kept (has 'item 5')", "project memory item 5" in doc_set)
shutil.rmtree(tmp, ignore_errors=True)

print("== Test 2: global cap eviction ==")
tmp = fresh_client()
mem.GLOBAL_MEMORY_CAP = 5
for i in range(8):
    mem.add_global_memory(f"global pattern {i}")
    time.sleep(0.01)
gcnt = mem._get_or_create(mem.GLOBAL_COLLECTION).count()
check(f"global collection count == cap (got {gcnt}, cap 5)", gcnt == 5)
shutil.rmtree(tmp, ignore_errors=True)

print("== Test 3: build_memory_context aggregates ==")
tmp = fresh_client()
mem.PROJECT_MEMORY_CAP = 200
mem.GLOBAL_MEMORY_CAP = 200
PID2 = 999002
mem.add_project_memory(PID2, "项目经验：登录接口要加限流", {"type": "review_result"})
mem.add_global_memory("通用经验：错误处理要返回统一格式", {"type": "pattern"})
ctx = mem.build_memory_context(PID2, "登录接口 限流 错误处理 统一格式")
check("context is non-empty str", isinstance(ctx, str) and ctx.strip() != "")
check("context includes project memory", "登录接口要加限流" in ctx)
check("context includes global memory", "统一格式" in ctx)
check("context has project label", "项目历史经验" in ctx)
check("context has global label", "通用模式" in ctx)
shutil.rmtree(tmp, ignore_errors=True)

print("== Test 4: build_memory_context returns '' when truly empty ==")
tmp = fresh_client()
empty_ctx = mem.build_memory_context(888888, "anything")
check("empty backend -> empty context", empty_ctx == "")
shutil.rmtree(tmp, ignore_errors=True)

print("== Test 5: task memory lifecycle ==")
tmp = fresh_client()
TID = 999003
mem.add_task_memory(TID, "step 1 done", {"type": "progress"})
mem.add_task_memory(TID, "step 2 done", {"type": "progress"})
tcount = mem._get_or_create(mem._task_collection(TID)).count()
check(f"task memory recorded (got {tcount})", tcount == 2)
mem.delete_task_memory(TID)
client = mem._get_client()
names = [c.name for c in client.list_collections()]
check("task collection deleted after cleanup", mem._task_collection(TID) not in names)
shutil.rmtree(tmp, ignore_errors=True)

print("== Test 6: mem_ok reflects backend ==")
tmp = fresh_client()
check("mem_ok() is True with chromadb available", mem.mem_ok() is True)
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n== RESULT: {PASS} passed, {FAIL} failed ==")
sys.exit(1 if FAIL else 0)
