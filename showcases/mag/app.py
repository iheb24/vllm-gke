"""MAG demo API: cross-session operations assistant with explicit memory.

POST /chat answers with the user's keyword-retrieved memories and bounded
session history in the prompt; the /memories endpoints provide the explicit
write/correct/delete surface (there is no automatic memory extraction).
All state is per-user and lives in one SQLite file; `user_id` is a scoping
label for the demo, not authentication.

Observability: OpenTelemetry metrics in Prometheus exposition at /metrics,
following the GenAI semantic conventions (gen_ai.client.*) for model calls
plus ag_demo_mag_* instruments for pipeline stages and memory operations.
"""

import os
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from fake_model import make_fake_transport
from memory_store import MemoryStore, NotFound
from pipeline import MagConfig, MagPipeline, find_secret_like

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8081")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ")
MAG_DB_PATH = os.environ.get(
    "MAG_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mag.db"),
)
MAG_SESSION_TURN_LIMIT = int(os.environ.get("MAG_SESSION_TURN_LIMIT", "8"))
MAG_FAKE_MODEL = os.environ.get("MAG_FAKE_MODEL", "")

from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

DURATION_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
TOKEN_BUCKETS = [1, 10, 50, 100, 250, 500, 1000, 5000]
RETRIEVAL_BUCKETS = [0, 1, 2, 3, 5, 8, 13, 21]

reader = PrometheusMetricReader()
provider = MeterProvider(
    metric_readers=[reader],
    views=[
        View(instrument_name="gen_ai.client.operation.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="ag_demo_mag_stage.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="gen_ai.client.token.usage",
             aggregation=ExplicitBucketHistogramAggregation(TOKEN_BUCKETS)),
        View(instrument_name="ag_demo_mag_retrieval.memories",
             aggregation=ExplicitBucketHistogramAggregation(RETRIEVAL_BUCKETS)),
    ],
)
metrics.set_meter_provider(provider)
meter = metrics.get_meter("ag_demo.mag")

operation_duration = meter.create_histogram(
    "gen_ai.client.operation.duration",
    unit="s",
    description="Duration of GenAI chat operations through the gateway",
)
token_usage = meter.create_histogram(
    "gen_ai.client.token.usage",
    unit="{token}",
    description="Token usage reported by the gateway",
)
stage_duration = meter.create_histogram(
    "ag_demo_mag_stage.duration",
    unit="s",
    description="Duration of each MAG pipeline stage",
)
retrieved_memories = meter.create_histogram(
    "ag_demo_mag_retrieval.memories",
    unit="{memory}",
    description="Memories injected into the prompt per chat request",
)
memory_ops = meter.create_counter(
    "ag_demo_mag_memory_ops",
    description="Memory write operations per type",
)
request_count = meter.create_counter(
    "ag_demo_mag_requests",
    description="Requests per endpoint and outcome",
)


def record_model_call(duration, usage):
    operation_duration.record(duration, {
        "gen_ai.operation.name": "chat",
        "gen_ai.system": "envoy-gateway",
        "gen_ai.request.model": GATEWAY_MODEL,
    })
    for token_type, value in (("input", usage.get("prompt_tokens")), ("output", usage.get("completion_tokens"))):
        if value is not None:
            token_usage.record(value, {
                "gen_ai.request.model": GATEWAY_MODEL,
                "gen_ai.token.type": token_type,
            })


class GatewayClient:
    def __init__(self, base_url, api_key=None, model=GATEWAY_MODEL, transport=None, on_response=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._http_transport
        self.on_response = on_response

    def _http_transport(self, base_url, api_key, payload):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.post(
            f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120
        )
        resp.raise_for_status()
        return resp.json()

    def chat(self, messages, temperature=0.0):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        start = time.perf_counter()
        body = self.transport(self.base_url, self.api_key, payload)
        duration = time.perf_counter() - start
        raw_usage = body.get("usage") or {}
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens", 0),
            "completion_tokens": raw_usage.get("completion_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }
        if self.on_response:
            self.on_response(duration, usage)
        return body["choices"][0]["message"]["content"], usage


store = None
pipeline = None


@asynccontextmanager
async def lifespan(app):
    global store, pipeline
    store = MemoryStore(MAG_DB_PATH)
    transport = make_fake_transport() if MAG_FAKE_MODEL else None
    gateway = GatewayClient(
        GATEWAY_URL, GATEWAY_API_KEY, GATEWAY_MODEL,
        transport=transport, on_response=record_model_call,
    )
    pipeline = MagPipeline(
        store, gateway, MagConfig(turn_limit=MAG_SESSION_TURN_LIMIT)
    )
    yield
    store.close()


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    question: str


class MemoryCreate(BaseModel):
    user_id: str
    text: str
    category: str | None = None


class MemoryCorrect(BaseModel):
    user_id: str
    text: str


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        result = pipeline.chat(req.user_id, req.session_id, req.question)
        for stage in result["trace"]["stages"]:
            stage_duration.record(stage["duration_s"], {"mag.stage": stage["name"]})
        retrieved_memories.record(len(result["evidence"]["memory_ids"]))
        request_count.add(1, {"http.route": "/chat", "outcome": "ok"})
        return result
    except Exception:
        request_count.add(1, {"http.route": "/chat", "outcome": "error"})
        raise


@app.post("/memories")
def create_memory(req: MemoryCreate):
    reason = find_secret_like(req.text)
    if reason:
        request_count.add(1, {"http.route": "/memories", "outcome": "secret_rejected"})
        raise HTTPException(status_code=422, detail=reason)
    memory_id = store.add_memory(req.user_id, req.text, req.category)
    memory_ops.add(1, {"mag.op": "add"})
    request_count.add(1, {"http.route": "/memories", "outcome": "ok"})
    return {"id": memory_id}


@app.get("/memories")
def list_memories(user_id: str = Query(...)):
    memories = store.list_memories(user_id)
    return {
        "user_id": user_id,
        "memories": [
            {
                "id": m["id"],
                "text": m["text"],
                "category": m["category"],
                "created_at": m["created_at"],
                "updated_at": m["updated_at"],
            }
            for m in memories
        ],
        "count": len(memories),
    }


@app.post("/memories/{memory_id}/correct")
def correct_memory(memory_id: int, req: MemoryCorrect):
    reason = find_secret_like(req.text)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    try:
        new_id = store.correct_memory(req.user_id, memory_id, req.text)
    except NotFound:
        raise HTTPException(status_code=404, detail="memory not found")
    memory_ops.add(1, {"mag.op": "correct"})
    return {"id": new_id, "superseded": memory_id}


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, user_id: str = Query(...)):
    try:
        store.delete_memory(user_id, memory_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="memory not found")
    memory_ops.add(1, {"mag.op": "delete"})
    return {"deleted": memory_id}


@app.delete("/memories")
def delete_all_memories(user_id: str = Query(...)):
    count = store.delete_all_memories(user_id)
    memory_ops.add(1, {"mag.op": "delete_all"})
    return {"deleted": count}


@app.get("/healthz")
def healthz():
    try:
        store.healthcheck()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database not writable: {exc}")
    stats = store.stats()
    return {"status": "ok", "db_path": MAG_DB_PATH, "active_memories": stats["active_memories"]}


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
