import os

import app as tag_app
from fastapi.testclient import TestClient

FLAGSHIP = (
    "On the three most expensive GPU days, summarize whether the incident "
    "notes point mainly to capacity problems or configuration problems."
)


def test_fake_model_env_is_active():
    assert os.environ["TAG_FAKE_MODEL"] == "1"
    assert tag_app.TAG_FAKE_MODEL == "1"


def test_healthz():
    with TestClient(tag_app.app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db_path"] == os.environ["TAG_DB_PATH"]


def test_chat_response_contract():
    with TestClient(tag_app.app) as client:
        resp = client.post("/chat", json={"question": FLAGSHIP})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "table-augmented-generation"
        for key in ("answer", "evidence", "trace", "usage"):
            assert key in body
        assert "mainly to capacity" in body["answer"]
        assert body["evidence"]["row_count"] == 3
        assert body["trace"]["model"] == tag_app.GATEWAY_MODEL
        assert body["usage"]["total_tokens"] > 0


def test_metrics_endpoint_exposes_demo_metrics():
    with TestClient(tag_app.app) as client:
        client.post("/chat", json={"question": "How many incident notes are there?"})
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "ag_demo_tag_" in resp.text
        assert "ag_demo_tag_stage_duration" in resp.text
        assert "gen_ai_client_operation_duration" in resp.text
