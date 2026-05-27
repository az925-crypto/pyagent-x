import json
import os
import time
import asyncio
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "memory.json"
_cache = None
_lock = asyncio.Lock()
_mem_id_counter = 0


def _mem_uid():
    global _mem_id_counter
    _mem_id_counter += 1
    return f"mem-{int(time.time() * 1000)}-{_mem_id_counter}"


def _default_store():
    return {"patterns": []}


async def _load():
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = await asyncio.to_thread(MEMORY_FILE.read_text, encoding="utf-8")
        _cache = json.loads(raw)
        return _cache
    except Exception:
        _cache = _default_store()
        return _cache


async def _save():
    if _cache is None:
        return
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            MEMORY_FILE.write_text, json.dumps(_cache, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[Memory] save failed: {e}")


async def add_memory(
    category: str,
    pattern: str,
    confidence: str = "medium",
    tags: list[str] | None = None,
) -> dict:
    async with _lock:
        store = await _load()
        entry = {
            "id": _mem_uid(),
            "category": category,
            "pattern": pattern,
            "confidence": confidence,
            "tags": tags or [],
            "createdAt": int(time.time() * 1000),
            "lastUsed": int(time.time() * 1000),
            "useCount": 0,
        }
        store["patterns"].append(entry)
        await _save()
        return {"ok": True, "id": entry["id"], "total": len(store["patterns"])}


async def query_memories(query: dict | None = None) -> list[dict]:
    async with _lock:
        store = await _load()
        results = list(store["patterns"])

        q = query or {}
        if q.get("category"):
            results = [m for m in results if m["category"] == q["category"]]
        if q.get("tags"):
            tags = q["tags"]
            results = [m for m in results if any(t in m["tags"] for t in tags)]

        conf_score = {"high": 3, "medium": 2, "low": 1}
        results.sort(
            key=lambda m: m["useCount"] * 10 + conf_score.get(m["confidence"], 0),
            reverse=True,
        )

        limit = q.get("limit", 10)
        results = results[:limit]

        for r in results:
            r["lastUsed"] = int(time.time() * 1000)
            r["useCount"] += 1
        await _save()

        return results


async def get_all_memories() -> list[dict]:
    async with _lock:
        store = await _load()
        return store["patterns"]


async def get_memory_stats() -> dict:
    async with _lock:
        store = await _load()
        by_category = {}
        by_confidence = {}
        for m in store["patterns"]:
            by_category[m["category"]] = by_category.get(m["category"], 0) + 1
            by_confidence[m["confidence"]] = by_confidence.get(m["confidence"], 0) + 1
        return {
            "total": len(store["patterns"]),
            "byCategory": by_category,
            "byConfidence": by_confidence,
        }
