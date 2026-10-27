import os

import app as mag_app
from fastapi.testclient import TestClient


def test_fake_model_env_is_active():
    assert os.environ["MAG_FAKE_MODEL"] == "1"
    assert mag_app.MAG_FAKE_MODEL == "1"


def test_healthz():
    with TestClient(mag_app.app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db_path"] == os.environ["MAG_DB_PATH"]
        assert "active_memories" in body


def test_full_alice_bob_flow():
    with TestClient(mag_app.app) as client:
        remember = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "session_id": "session-A",
                "question": "remember: I prefer concise answers",
            },
        )
        assert remember.status_code == 200
        body = remember.json()
        assert body["method"] == "memory-augmented-generation"
        memory_id = body["evidence"]["memory_ids"][0]
        assert f"memory #{memory_id}" in body["answer"]
        for key in ("answer", "evidence", "trace", "usage"):
            assert key in body

        recall = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "session_id": "session-B",
                "question": "How should you answer me?",
            },
        )
        assert recall.status_code == 200
        body = recall.json()
        assert f"Based on your stored memory [{memory_id}]" in body["answer"]
        assert body["evidence"]["memory_ids"] == [memory_id]
        assert body["evidence"]["session_turns_used"] == 0
        assert [s["name"] for s in body["trace"]["stages"]] == [
            "memory_retrieval",
            "prompt_build",
            "generate",
        ]

        bob_recall = client.post(
            "/chat",
            json={
                "user_id": "bob",
                "session_id": "session-B",
                "question": "How should you answer me?",
            },
        )
        bob_body = bob_recall.json()
        assert "no stored memories were relevant" in bob_body["answer"]
        assert bob_body["evidence"]["memory_ids"] == []

        bob_list = client.get("/memories", params={"user_id": "bob"})
        assert bob_list.json()["count"] == 0

        bob_correct = client.post(
            f"/memories/{memory_id}/correct",
            json={"user_id": "bob", "text": "hijacked"},
        )
        assert bob_correct.status_code == 404

        bob_delete = client.delete(
            f"/memories/{memory_id}", params={"user_id": "bob"}
        )
        assert bob_delete.status_code == 404

        alice_list = client.get("/memories", params={"user_id": "alice"})
        assert alice_list.json()["count"] == 1

        correct = client.post(
            f"/memories/{memory_id}/correct",
            json={"user_id": "alice", "text": "I prefer detailed answers with examples"},
        )
        assert correct.status_code == 200
        new_id = correct.json()["id"]
        assert correct.json()["superseded"] == memory_id

        recall2 = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "session_id": "session-C",
                "question": "How should you answer me?",
            },
        )
        body2 = recall2.json()
        assert f"Based on your stored memory [{new_id}]" in body2["answer"]
        assert "detailed answers" in body2["answer"]
        assert body2["evidence"]["memory_ids"] == [new_id]

        delete = client.delete(
            f"/memories/{new_id}", params={"user_id": "alice"}
        )
        assert delete.status_code == 200
        recall3 = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "session_id": "session-D",
                "question": "How should you answer me?",
            },
        )
        assert recall3.json()["evidence"]["memory_ids"] == []


def test_memory_write_endpoints_and_secret_rejection():
    with TestClient(mag_app.app) as client:
        created = client.post(
            "/memories",
            json={"user_id": "carol", "text": "runbooks live in the wiki", "category": "ops"},
        )
        assert created.status_code == 200
        memory_id = created.json()["id"]
        listed = client.get("/memories", params={"user_id": "carol"})
        assert listed.json()["memories"][0]["id"] == memory_id
        assert listed.json()["memories"][0]["category"] == "ops"

        rejected = client.post(
            "/memories",
            json={"user_id": "carol", "text": "password = hunter2"},
        )
        assert rejected.status_code == 422
        assert "password" in rejected.json()["detail"]
        assert client.get("/memories", params={"user_id": "carol"}).json()["count"] == 1

        delete_all = client.delete("/memories", params={"user_id": "carol"})
        assert delete_all.json() == {"deleted": 1}
        assert client.get("/memories", params={"user_id": "carol"}).json()["count"] == 0


def test_remember_secret_via_chat_not_stored():
    with TestClient(mag_app.app) as client:
        resp = client.post(
            "/chat",
            json={
                "user_id": "dave",
                "session_id": "s1",
                "question": "remember: api key sk-abcdefghijklmnop",
            },
        )
        assert "Not stored" in resp.json()["answer"]
        assert client.get("/memories", params={"user_id": "dave"}).json()["count"] == 0


def test_metrics_endpoint_exposes_demo_metrics():
    with TestClient(mag_app.app) as client:
        client.post(
            "/chat",
            json={"user_id": "erin", "session_id": "s1", "question": "hello there"},
        )
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "ag_demo_mag_" in resp.text
        assert "ag_demo_mag_stage_duration" in resp.text
        assert "gen_ai_client_operation_duration" in resp.text
