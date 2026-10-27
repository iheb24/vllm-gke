import pytest

import db
from fake_model import make_fake_transport
from pipeline import OUT_OF_SCOPE_ANSWER, GatewayClient, TagConfig, TagPipeline

FLAGSHIP = (
    "On the three most expensive GPU days, summarize whether the incident "
    "notes point mainly to capacity problems or configuration problems."
)


def always_bad_transport(base_url, api_key, payload):
    messages = payload["messages"]
    last_user = messages[-1]["content"]
    if "Rows (JSON):" in last_user:
        content = "unreachable: the pipeline must fail closed before generation"
    else:
        content = "DELETE FROM incident_notes"
    prompt = sum(len(m["content"]) for m in messages) // 4
    completion = len(content) // 4
    return {
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


@pytest.fixture()
def pipeline(tmp_path):
    path = db.ensure_database(tmp_path / "pipe.db")
    gateway = GatewayClient(
        "http://fake", None, "fake-model", transport=make_fake_transport(str(path))
    )
    return TagPipeline(TagConfig(gateway=gateway, db_path=str(path)))


def test_flagship_end_to_end(pipeline):
    result = pipeline.answer(FLAGSHIP)
    assert result["method"] == "table-augmented-generation"
    answer = result["answer"]
    for expected in ("2026-09-08", "28.40", "2026-09-17", "25.10", "2026-09-24", "22.75"):
        assert expected in answer
    assert "mainly to capacity" in answer
    assert "configuration" in answer
    assert result["evidence"]["row_count"] == 3
    assert "JOIN incident_notes" in result["evidence"]["sql"]
    stage_names = [s["name"] for s in result["trace"]["stages"]]
    assert stage_names == ["query_synthesis", "sql_execution", "answer_generation"]
    assert result["trace"]["sql_attempts"] == [
        {"attempt": 1, "sql": result["evidence"]["sql"], "outcome": "ok"}
    ]
    assert result["usage"]["total_tokens"] > 0
    assert result["usage"]["prompt_tokens"] >= result["usage"]["completion_tokens"] > 0
    assert "error" not in result


def test_retry_recovers_from_invalid_sql(pipeline):
    result = pipeline.answer("What is the daily GPU cost per request in September?")
    assert result["answer"] is not None
    attempts = result["trace"]["sql_attempts"]
    assert len(attempts) == 2
    assert attempts[0]["outcome"] == "rejected"
    assert "est_cost" in attempts[0]["error"]
    assert attempts[1]["outcome"] == "ok"
    assert "est_cost_usd" in attempts[1]["sql"]
    assert "cost_per_request" in result["evidence"]["columns"]


def test_fails_closed_when_sql_never_valid(tmp_path):
    path = db.ensure_database(tmp_path / "bad.db")
    gateway = GatewayClient("http://fake", None, "fake-model", transport=always_bad_transport)
    pipe = TagPipeline(TagConfig(gateway=gateway, db_path=str(path)))
    result = pipe.answer("Summarize the incident notes.")
    assert result["answer"] is None
    assert result["error"]["type"] == "sql_rejected"
    assert "could not produce a valid read-only query" in result["error"]["message"]
    assert result["evidence"]["rows"] == []
    assert result["evidence"]["sql"] is None
    attempts = result["trace"]["sql_attempts"]
    assert [a["outcome"] for a in attempts] == ["rejected", "rejected"]
    stage_names = [s["name"] for s in result["trace"]["stages"]]
    assert "answer_generation" not in stage_names


def test_out_of_scope_never_executes_sql(pipeline):
    result = pipeline.answer("What is the capital of France?")
    assert result["answer"] == OUT_OF_SCOPE_ANSWER
    assert result["evidence"]["sql"] is None
    assert result["evidence"]["rows"] == []
    assert result["trace"]["sql_attempts"] == [
        {"attempt": 1, "sql": None, "outcome": "out_of_scope"}
    ]
    stage_names = [s["name"] for s in result["trace"]["stages"]]
    assert stage_names == ["query_synthesis"]


def test_model_and_db_path_in_trace(pipeline):
    result = pipeline.answer("How many incident notes are there?")
    assert result["trace"]["model"] == "fake-model"
    assert result["trace"]["db_path"].endswith("pipe.db")
    assert "12" in result["answer"]
