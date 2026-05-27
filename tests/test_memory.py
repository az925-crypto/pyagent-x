import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

import agent.memory
from agent.memory import add_memory, query_memories, get_memory_stats, get_all_memories


@pytest.fixture(autouse=True)
def temp_memory_file():
    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps({"patterns": []}))
    with patch.object(agent.memory, "MEMORY_FILE", tmp):
        with patch.object(agent.memory, "_cache", None):
            yield tmp
    if tmp.exists():
        tmp.unlink()


@pytest.mark.asyncio
async def test_add_memory():
    result = await add_memory("pattern", "test pattern", "high", ["test"])
    assert result["ok"] is True
    assert result["total"] == 1

    all_mem = await get_all_memories()
    assert len(all_mem) == 1
    assert all_mem[0]["category"] == "pattern"
    assert all_mem[0]["pattern"] == "test pattern"
    assert all_mem[0]["confidence"] == "high"
    assert all_mem[0]["tags"] == ["test"]


@pytest.mark.asyncio
async def test_add_multiple_memories():
    for i in range(3):
        await add_memory("profile", f"pattern {i}", "medium")
    all_mem = await get_all_memories()
    assert len(all_mem) == 3


@pytest.mark.asyncio
async def test_query_by_category():
    await add_memory("domain", "subdomain enumeration", "high")
    await add_memory("profile", "bio analysis", "low")
    results = await query_memories({"category": "profile", "limit": 10})
    assert len(results) == 1
    assert results[0]["pattern"] == "bio analysis"


@pytest.mark.asyncio
async def test_query_by_tags():
    await add_memory("domain", "dns scanning", "high", tags=["network", "recon"])
    await add_memory("profile", "username pattern", "low", tags=["social"])
    results = await query_memories({"tags": ["network"], "limit": 10})
    assert len(results) == 1
    assert results[0]["category"] == "domain"


@pytest.mark.asyncio
async def test_get_memory_stats():
    assert await get_memory_stats() == {"total": 0, "byCategory": {}, "byConfidence": {}}
    await add_memory("domain", "pattern a", "high")
    await add_memory("profile", "pattern b", "high")
    await add_memory("email", "pattern c", "low")
    stats = await get_memory_stats()
    assert stats["total"] == 3
    assert stats["byCategory"] == {"domain": 1, "profile": 1, "email": 1}
    assert stats["byConfidence"] == {"high": 2, "low": 1}


@pytest.mark.asyncio
async def test_query_memories_updates_use_count():
    await add_memory("test", "frequent pattern", "high")
    before = await get_all_memories()
    assert before[0]["useCount"] == 0
    await query_memories({"limit": 10})
    after = await get_all_memories()
    assert after[0]["useCount"] == 1


@pytest.mark.asyncio
async def test_empty_query_returns_all():
    await add_memory("a", "p1", "low")
    await add_memory("b", "p2", "low")
    results = await query_memories()
    assert len(results) == 2
