"""CAG demo API: static handbook prefix -> single generation, no retrieval.

POST /chat sends the entire versioned operations-handbook corpus as a
stable system prefix plus the question, through the existing gateway. There
are no embeddings, no vector database, and no reranking anywhere in this
request path; the only acceleration mechanism is the model server's prefix
cache, which should skip re-prefilling the corpus on warm requests. Until
the live benchmark records prefix-cache counter deltas, every response
carries cache_verified: false.

Observability: OpenTelemetry metrics in Prometheus exposition at /metrics,
following the GenAI semantic conventions (gen_ai.client.*) for model calls
plus ag_demo_cag_* instruments for prefix size and pipeline stages.
"""

import os
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import corpus as corpus_module
from corpus import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    BudgetExceeded,
    CorpusError,
    build_messages,
    default_token_counter,
)
from fake_model import make_fake_transport

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8081")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ")
CAG_MAX_OUTPUT_TOKENS = int(os.environ.get("CAG_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
CAG_CORPUS_DIR = os.environ.get("CAG_CORPUS_DIR", str(corpus_module.CORPUS_DIR))
CAG_FAKE_MODEL = os.environ.get("CAG_FAKE_MODEL", "")

WARMUP_QUESTION = "Confirm the operations handbook is loaded and ready."
WARMUP_NOTE = (
    "warm-up prefill primes the vLLM prefix cache for this corpus; it is "
    "separate from pod startup and scale-from-zero provisioning"
)

from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

DURATION_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
TOKEN_BUCKETS = [1, 10, 50, 100, 250, 500, 1000, 5000]
PREFIX_BUCKETS = [1000, 2500, 5000, 7500, 10000, 12500, 16000, 24000, 32000]

reader = PrometheusMetricReader()
provider = MeterProvider(
    metric_readers=[reader],
    views=[
        View(instrument_name="gen_ai.client.operation.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="ag_demo_cag_stage.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="gen_ai.client.token.usage",
             aggregation=ExplicitBucketHistogramAggregation(TOKEN_BUCKETS)),
        View(instrument_name="ag_demo_cag_prefix.tokens",
             aggregation=ExplicitBucketHistogramAggregation(PREFIX_BUCKETS)),
    ],
)
metrics.set_meter_provider(provider)
meter = metrics.get_meter("ag_demo.cag")

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
    "ag_demo_cag_stage.duration",
    unit="s",
    description="Duration of each CAG pipeline stage",
)
prefix_tokens = meter.create_histogram(
    "ag_demo_cag_prefix.tokens",
    unit="{token}",
    description="Corpus prefix tokens sent with each request",
)
request_count = meter.create_counter(
    "ag_demo_cag_requests",
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

    def chat(self, messages, temperature=0.0, max_tokens=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
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


gateway = None
token_counter = None


@asynccontextmanager
async def lifespan(app):
    global gateway, token_counter
    transport = make_fake_transport(CAG_CORPUS_DIR) if CAG_FAKE_MODEL else None
    gateway = GatewayClient(
        GATEWAY_URL, GATEWAY_API_KEY, GATEWAY_MODEL,
        transport=transport, on_response=record_model_call,
    )
    token_counter = default_token_counter()
    yield


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    question: str


def run_cag(question):
    stages = []

    def build():
        return build_messages(
            question,
            token_counter,
            corpus_dir=CAG_CORPUS_DIR,
            max_output_tokens=CAG_MAX_OUTPUT_TOKENS,
        )

    start = time.perf_counter()
    messages, info = build()
    stages.append({"name": "build_prefix", "duration_s": round(time.perf_counter() - start, 6)})

    start = time.perf_counter()
    answer, usage = gateway.chat(messages, max_tokens=CAG_MAX_OUTPUT_TOKENS)
    stages.append({"name": "generate", "duration_s": round(time.perf_counter() - start, 6)})

    for stage in stages:
        stage_duration.record(stage["duration_s"], {"cag.stage": stage["name"]})
    prefix_tokens.record(info["corpus_tokens"], {"cag.corpus_version": info["corpus_version"]})
    return {
        "method": "cache-augmented-generation",
        "answer": answer.strip(),
        "evidence": {
            "corpus_version": info["corpus_version"],
            "corpus_tokens": info["corpus_tokens"],
            "tokenizer": info["tokenizer"],
            "sources": info["sources"],
        },
        "trace": {
            "stages": stages,
            "model": GATEWAY_MODEL,
            "cache_verified": False,
            "question_tokens": info["question_tokens"],
            "required_tokens": info["required_tokens"],
            "context_limit": info["context_limit"],
        },
        "usage": usage,
    }


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        result = run_cag(req.question)
        request_count.add(1, {"http.route": "/chat", "outcome": "ok"})
        return result
    except BudgetExceeded as exc:
        request_count.add(1, {"http.route": "/chat", "outcome": "budget_exceeded"})
        raise HTTPException(status_code=422, detail=str(exc))
    except CorpusError as exc:
        request_count.add(1, {"http.route": "/chat", "outcome": "corpus_error"})
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        request_count.add(1, {"http.route": "/chat", "outcome": "error"})
        raise


@app.post("/warmup")
def warmup():
    start = time.perf_counter()
    try:
        result = run_cag(WARMUP_QUESTION)
        request_count.add(1, {"http.route": "/warmup", "outcome": "ok"})
    except BudgetExceeded as exc:
        request_count.add(1, {"http.route": "/warmup", "outcome": "budget_exceeded"})
        raise HTTPException(status_code=422, detail=str(exc))
    except CorpusError as exc:
        request_count.add(1, {"http.route": "/warmup", "outcome": "corpus_error"})
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "duration_s": round(time.perf_counter() - start, 6),
        "usage": result["usage"],
        "corpus_version": result["evidence"]["corpus_version"],
        "note": WARMUP_NOTE,
    }


@app.get("/healthz")
def healthz():
    try:
        manifest, docs = corpus_module.load_corpus(CAG_CORPUS_DIR)
    except CorpusError as exc:
        raise HTTPException(status_code=503, detail=f"corpus invalid: {exc}")
    return {
        "status": "ok",
        "corpus_version": manifest["corpus_sha256_short"],
        "corpus_tokens": manifest["total_tokens"],
    }


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
