import pytest

from memory_store import MemoryStore, NotFound


@pytest.fixture()
def store(tmp_path):
    with MemoryStore(tmp_path / "store.db") as s:
        yield s


def test_fts5_detected(store):
    assert store.fts5 is True


def test_add_list_get(store):
    mid = store.add_memory("alice", "I prefer concise answers", "preference")
    assert store.memory_count("alice") == 1
    memories = store.list_memories("alice")
    assert [m["id"] for m in memories] == [mid]
    assert memories[0]["text"] == "I prefer concise answers"
    assert memories[0]["category"] == "preference"
    assert memories[0]["status"] == "active"
    assert store.get_memory("alice", mid)["id"] == mid
    with pytest.raises(NotFound):
        store.get_memory("alice", mid + 99)


def test_cross_user_isolation(store):
    alice_id = store.add_memory("alice", "Alice secret fact")
    store.add_memory("bob", "Bob fact")
    assert store.memory_count("alice") == 1
    assert store.memory_count("bob") == 1
    assert [m["text"] for m in store.list_memories("alice")] == ["Alice secret fact"]
    assert [m["text"] for m in store.search_memories("bob", "secret")] == ["Bob fact"]
    assert not any(
        m["text"] == "Alice secret fact" for m in store.search_memories("bob", "Alice secret")
    )
    with pytest.raises(NotFound):
        store.correct_memory("bob", alice_id, "hijacked")
    with pytest.raises(NotFound):
        store.delete_memory("bob", alice_id)
    assert store.memory_count("alice") == 1


def test_correct_supersedes(store):
    first = store.add_memory("alice", "The GPU pool has 1 node")
    store.add_memory("alice", "Unrelated note")
    new_id = store.correct_memory("alice", first, "The GPU pool has 2 nodes")
    active = store.list_memories("alice")
    assert [m["id"] for m in active] == sorted(m["id"] for m in active)
    texts = {m["id"]: m["text"] for m in active}
    assert texts[new_id] == "The GPU pool has 2 nodes"
    assert first not in texts
    everything = store.list_memories("alice", include_inactive=True)
    old = next(m for m in everything if m["id"] == first)
    assert old["status"] == "superseded"
    assert old["superseded_by"] == new_id
    assert not any(m["text"] == "The GPU pool has 1 node" for m in store.search_memories("alice", "GPU pool nodes"))
    assert any(m["text"] == "The GPU pool has 2 nodes" for m in store.search_memories("alice", "GPU pool nodes"))


def test_delete_and_delete_all(store):
    a = store.add_memory("alice", "fact one")
    b = store.add_memory("alice", "fact two")
    store.add_memory("bob", "bob fact")
    store.delete_memory("alice", a)
    assert store.memory_count("alice") == 1
    with pytest.raises(NotFound):
        store.delete_memory("alice", a)
    count = store.delete_all_memories("alice")
    assert count == 1
    assert store.memory_count("alice") == 0
    assert store.search_memories("alice", "fact") == []
    assert store.memory_count("bob") == 1
    assert b in [m["id"] for m in store.list_memories("alice", include_inactive=True)]
    statuses = {m["id"]: m["status"] for m in store.list_memories("alice", include_inactive=True)}
    assert statuses[a] == "deleted" and statuses[b] == "deleted"


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "persist.db"
    with MemoryStore(path) as s1:
        first = s1.add_memory("alice", "durable fact")
        dead = s1.add_memory("alice", "temporary fact")
        new_id = s1.correct_memory("alice", first, "durable fact v2")
        s1.delete_memory("alice", dead)
        s1.append_turn("alice", "s1", "user", "hello")
    with MemoryStore(path) as s2:
        assert [m["text"] for m in s2.list_memories("alice")] == ["durable fact v2"]
        everything = {m["id"]: m["status"] for m in s2.list_memories("alice", include_inactive=True)}
        assert everything[first] == "superseded"
        assert everything[dead] == "deleted"
        assert everything[new_id] == "active"
        assert s2.search_memories("alice", "durable")[0]["text"] == "durable fact v2"
        turns = s2.recent_turns("alice", "s1")
        assert [t["content"] for t in turns] == ["hello"]


def test_search_ranking_and_recency(store):
    store.add_memory("alice", "the cpu tier model is qwen3-4b-cpu")
    store.add_memory("alice", "the gpu tier runs the Qwen2.5-Coder-14B model on one L4 node")
    store.add_memory("alice", "unrelated lunch preference: soup")
    hits = store.search_memories("alice", "which gpu tier model")
    assert hits[0]["text"].startswith("the gpu tier")
    assert all("soup" not in h["text"] for h in hits[:1])
    recent = store.search_memories("alice", "")
    assert recent[0]["text"].startswith("unrelated")
    fallback = store.search_memories("alice", "zzzznothingmatches")
    assert fallback[0]["text"].startswith("unrelated")


def test_search_handles_fts_syntax_garbage(store):
    store.add_memory("alice", "plain fact about routers")
    for nasty in ('" OR ', "NEAR(", "*", "or and not", "((("):
        results = store.search_memories("alice", nasty)
        assert isinstance(results, list)


def test_session_turns_bounded_and_ordered(tmp_path):
    with MemoryStore(tmp_path / "turns.db", keep_turns=10) as s:
        for i in range(15):
            s.append_turn("alice", "s1", "user", f"turn {i}")
        turns = s.recent_turns("alice", "s1", limit=8)
        assert [t["content"] for t in turns] == [f"turn {i}" for i in range(7, 15)]
        all_turns = s.recent_turns("alice", "s1", limit=100)
        assert len(all_turns) == 10
        assert all_turns[0]["content"] == "turn 5"
        s.append_turn("alice", "s2", "user", "other session")
        assert [t["content"] for t in s.recent_turns("alice", "s2")] == ["other session"]
        assert s.recent_turns("bob", "s1") == []


def test_stats(store):
    store.add_memory("alice", "one")
    store.add_memory("bob", "two")
    store.append_turn("alice", "s1", "user", "hi")
    stats = store.stats()
    assert stats == {"active_memories": 2, "turns": 1}


def test_healthcheck(store):
    assert store.healthcheck() is True
