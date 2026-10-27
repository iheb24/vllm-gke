"""TAG demo API: question -> synthesized SQL -> guarded execution -> answer.

POST /chat runs the Table-Augmented Generation pipeline against a synthetic
serving-analytics SQLite database. The model calls go through the existing
gateway Bearer-key convention; set TAG_FAKE_MODEL=1 to swap in a scripted
deterministic transport so the demo runs with no GPU and no network.

Observability: OpenTelemetry metrics in Prometheus exposition at /metrics,
following the GenAI semantic conventions (gen_ai.client.*) for model calls
plus ag_demo_tag_* instruments for pipeline stages and result sizes.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from db import DEFAULT_DB_PATH, ensure_database
from fake_model import make_fake_transport
from pipeline import GatewayClient, TagConfig, TagPipeline
from sql_guard import connect_readonly

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8081")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ")
TAG_DB_PATH = os.environ.get("TAG_DB_PATH", str(DEFAULT_DB_PATH))
TAG_ROW_CAP = int(os.environ.get("TAG_ROW_CAP", "200"))
TAG_FAKE_MODEL = os.environ.get("TAG_FAKE_MODEL", "")

from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

DURATION_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
TOKEN_BUCKETS = [1, 10, 50, 100, 250, 500, 1000, 5000]
ROW_BUCKETS = [0, 1, 5, 10, 25, 50, 100, 250, 500]

reader = PrometheusMetricReader()
provider = MeterProvider(
    metric_readers=[reader],
    views=[
        View(instrument_name="gen_ai.client.operation.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="ag_demo_tag_stage.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="gen_ai.client.token.usage",
             aggregation=ExplicitBucketHistogramAggregation(TOKEN_BUCKETS)),
        View(instrument_name="ag_demo_tag_result.rows",
             aggregation=ExplicitBucketHistogramAggregation(ROW_BUCKETS)),
    ],
)
metrics.set_meter_provider(provider)
meter = metrics.get_meter("ag_demo.tag")

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
    "ag_demo_tag_stage.duration",
    unit="s",
    description="Duration of each TAG pipeline stage",
)
result_rows = meter.create_histogram(
    "ag_demo_tag_result.rows",
    unit="{row}",
    description="Rows returned by the validated SQL per request",
)
request_count = meter.create_counter(
    "ag_demo_tag_requests",
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


def build_pipeline():
    transport = make_fake_transport(TAG_DB_PATH) if TAG_FAKE_MODEL else None
    gateway = GatewayClient(
        GATEWAY_URL, GATEWAY_API_KEY, GATEWAY_MODEL,
        transport=transport, on_response=record_model_call,
    )
    return TagPipeline(TagConfig(gateway=gateway, db_path=TAG_DB_PATH, row_cap=TAG_ROW_CAP))


pipeline = None


@asynccontextmanager
async def lifespan(app):
    global pipeline
    ensure_database(TAG_DB_PATH)
    pipeline = build_pipeline()
    yield


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    question: str


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        result = pipeline.answer(req.question)
        for stage in result["trace"]["stages"]:
            stage_duration.record(stage["duration_s"], {"tag.stage": stage["name"]})
        result_rows.record(result["evidence"]["row_count"], {"tag.method": "tag"})
        outcome = "ok" if result.get("answer") else "error"
        request_count.add(1, {"http.route": "/chat", "outcome": outcome})
        return result
    except Exception:
        request_count.add(1, {"http.route": "/chat", "outcome": "error"})
        raise


@app.get("/healthz")
def healthz():
    try:
        conn = connect_readonly(TAG_DB_PATH)
        try:
            conn.execute("SELECT count(*) FROM daily_serving_metrics").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database not readable: {exc}")
    return {"status": "ok", "db_path": TAG_DB_PATH}


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
