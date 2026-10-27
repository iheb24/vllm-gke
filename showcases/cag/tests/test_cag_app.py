import json
import os

import pytest

import app as cag_app
import build_manifest
import corpus
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def stub_token_counter(monkeypatch):
    monkeypatch.setattr(
        cag_app, "default_token_counter",
        lambda: ((lambda text: max(1, len(text) // 4)), "stub-chars//4"),
    )


def test_fake_model_env_is_active():
    assert os.environ["CAG_FAKE_MODEL"] == "1"
    assert cag_app.CAG_FAKE_MODEL == "1"


def test_healthz():
    with TestClient(cag_app.app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        manifest = corpus.load_manifest(cag_app.CAG_CORPUS_DIR)
        assert body["corpus_version"] == manifest["corpus_sha256_short"]
        assert body["corpus_tokens"] == manifest["total_tokens"]


def test_chat_response_contract():
    with TestClient(cag_app.app) as client:
        resp = client.post(
            "/chat",
            json={"question": "How long does a GPU cold start take with a warm PVC?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "cache-augmented-generation"
        for key in ("answer", "evidence", "trace", "usage"):
            assert key in body
        assert "(source:" in body["answer"]
        assert "routing-architecture.md" in body["answer"]
        evidence = body["evidence"]
        assert evidence["corpus_version"] == corpus.load_manifest(cag_app.CAG_CORPUS_DIR)["corpus_sha256_short"]
        assert evidence["corpus_tokens"] > 0
        assert evidence["tokenizer"] == "stub-chars//4"
        assert len(evidence["sources"]) == 6
        trace = body["trace"]
        assert [s["name"] for s in trace["stages"]] == ["build_prefix", "generate"]
        assert trace["cache_verified"] is False
        assert trace["model"] == cag_app.GATEWAY_MODEL
        assert body["usage"]["prompt_tokens"] > 0


def test_out_of_corpus_question_gets_fallback():
    with TestClient(cag_app.app) as client:
        resp = client.post("/chat", json={"question": "What is the capital of France?"})
        assert resp.status_code == 200
        assert "does not cover" in resp.json()["answer"]


def test_over_long_question_422_and_gateway_never_called():
    with TestClient(cag_app.app) as client:
        calls_before = cag_app.gateway.transport.calls
        resp = client.post("/chat", json={"question": "x" * 200000})
        assert resp.status_code == 422
        assert "context window" in resp.json()["detail"]
        assert cag_app.gateway.transport.calls == calls_before


def test_warmup_returns_timing_and_note():
    with TestClient(cag_app.app) as client:
        resp = client.post("/warmup")
        assert resp.status_code == 200
        body = resp.json()
        assert body["duration_s"] >= 0
        assert "usage" in body
        assert "not pod startup" in body["note"] or "separate from pod startup" in body["note"]
        assert body["corpus_version"]


def test_metrics_endpoint_exposes_demo_metrics():
    with TestClient(cag_app.app) as client:
        client.post("/chat", json={"question": "What is the idle cost per month?"})
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "ag_demo_cag_" in resp.text
        assert "ag_demo_cag_stage_duration" in resp.text
        assert "ag_demo_cag_prefix_tokens" in resp.text
        assert "gen_ai_client_operation_duration" in resp.text


@pytest.fixture()
def stale_corpus(tmp_path):
    (tmp_path / "doc.md").write_text("# Doc\n\nOriginal content.\n", encoding="utf-8")
    manifest = build_manifest.build_manifest(
        tmp_path, files=["doc.md"], token_counter=(lambda text: 10)
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest) + "\n")
    (tmp_path / "doc.md").write_text("# Doc\n\nEdited after manifest build.\n", encoding="utf-8")
    return tmp_path


def test_stale_corpus_reported_invalid(stale_corpus, monkeypatch):
    monkeypatch.setattr(cag_app, "CAG_CORPUS_DIR", str(stale_corpus))
    with TestClient(cag_app.app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 503
        assert "corpus invalid" in resp.json()["detail"]
        chat = client.post("/chat", json={"question": "anything"})
        assert chat.status_code == 503
        assert "re-run build_manifest" in chat.json()["detail"]
