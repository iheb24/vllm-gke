#!/usr/bin/env python3
"""Retrieval API: embed query -> Qdrant top-k -> rerank -> prompt -> gateway.

POST /search returns ranked passages. POST /chat answers end-to-end through
the Envoy gateway with citations. Everything stays in-cluster; the only
credentials are the Qdrant API key and the existing gateway Bearer key.

Observability: OpenTelemetry metrics in Prometheus exposition at /metrics,
following the GenAI semantic conventions (gen_ai.client.*) for model calls
plus rag.retrieval.* instruments for pipeline stages.
"""

import os
import time
from contextlib import contextmanager

import requests
from fastapi import FastAPI
from fastapi.responses import Response
from fastembed import SparseTextEmbedding
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "docs-v2")
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:8080")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "Qwen3-Embedding-0.6B")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8081")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "qwen3-4b-cpu")
TOP_K = int(os.environ.get("TOP_K", "5"))
RERANK_URL = os.environ.get("RERANK_URL", "")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "bge-reranker-base")
RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "50"))

from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

DURATION_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
TOKEN_BUCKETS = [1, 10, 50, 100, 250, 500, 1000, 5000]
SCORE_BUCKETS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

reader = PrometheusMetricReader()
provider = MeterProvider(
    metric_readers=[reader],
    views=[
        View(instrument_name="gen_ai.client.operation.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="rag.retrieval.stage.duration",
             aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS)),
        View(instrument_name="gen_ai.client.token.usage",
             aggregation=ExplicitBucketHistogramAggregation(TOKEN_BUCKETS)),
        View(instrument_name="rag.retrieval.top_score",
             aggregation=ExplicitBucketHistogramAggregation(SCORE_BUCKETS)),
    ],
)
metrics.set_meter_provider(provider)
meter = metrics.get_meter("rag.retrieval")

operation_duration = meter.create_histogram(
    "gen_ai.client.operation.duration",
    unit="s",
    description="Duration of GenAI operations (embed, rerank, chat)",
)
token_usage = meter.create_histogram(
    "gen_ai.client.token.usage",
    unit="{token}",
    description="Token usage reported by the gateway",
)
stage_duration = meter.create_histogram(
    "rag.retrieval.stage.duration",
    unit="s",
    description="Duration of each retrieval pipeline stage",
)
top_score = meter.create_histogram(
    "rag.retrieval.top_score",
    description="Top RRF score per search; separates in-scope from out-of-scope queries",
)
request_count = meter.create_counter(
    "rag.retrieval.requests",
    description="Requests per endpoint and outcome",
)

SYSTEM_PROMPT = """You answer questions using only the passages below.
Rules:
- Base every claim on the passages; never use outside knowledge.
- Cite each claim with [source#chunk_index] using the passage labels.
- If the passages do not answer the question, say it is not covered by the
  available documents. Do not guess.
"""

app = FastAPI()
qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
sparse_model = SparseTextEmbedding("Qdrant/bm25")


class SearchRequest(BaseModel):
    query: str
    k: int = TOP_K


class ChatRequest(BaseModel):
    query: str
    k: int = TOP_K


@contextmanager
def timed(stage, genai_attrs=None):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        stage_duration.record(elapsed, {"rag.stage": stage})
        if genai_attrs:
            operation_duration.record(elapsed, genai_attrs)


def embed(texts):
    headers = {"Content-Type": "application/json"}
    if EMBED_API_KEY:
        headers["Authorization"] = f"Bearer {EMBED_API_KEY}"
    with timed("embed", {
        "gen_ai.operation.name": "embeddings",
        "gen_ai.system": "tei",
        "gen_ai.request.model": EMBED_MODEL,
    }):
        resp = requests.post(
            f"{EMBED_URL}/v1/embeddings",
            json={"model": "qwen3-embedding", "input": texts},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def search_passages(query, k):
    dense = embed([query])[0]
    sparse_emb = list(sparse_model.embed([query]))[0]
    sparse = SparseVector(indices=sparse_emb.indices.tolist(), values=sparse_emb.values.tolist())
    candidate_count = RERANK_CANDIDATES if RERANK_URL else k
    with timed("qdrant"):
        hits = qdrant.query_points(
            collection_name=COLLECTION,
            prefetch=[
                Prefetch(query=dense, using="dense", limit=max(candidate_count, 20)),
                Prefetch(query=sparse, using="bm25", limit=max(candidate_count, 20)),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=candidate_count,
        ).points
    if hits:
        top_score.record(hits[0].score, {"rag.collection": COLLECTION})
    if RERANK_URL and len(hits) > k:
        hits = rerank(query, hits, k)
    return [
        {
            "source": hit.payload["source"],
            "heading_path": hit.payload.get("heading_path", ""),
            "chunk_index": hit.payload["chunk_index"],
            "score": hit.score,
            "text": hit.payload["text"],
        }
        for hit in hits
    ]


def rerank(query, hits, k):
    headers = {"Content-Type": "application/json"}
    if EMBED_API_KEY:
        headers["Authorization"] = f"Bearer {EMBED_API_KEY}"
    with timed("rerank", {
        "gen_ai.operation.name": "rerank",
        "gen_ai.system": "tei",
        "gen_ai.request.model": RERANK_MODEL,
    }):
        resp = requests.post(
            f"{RERANK_URL}/rerank",
            json={"query": query, "texts": [h.payload["text"] for h in hits]},
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
    order = sorted(resp.json(), key=lambda r: r["score"], reverse=True)
    return [hits[r["index"]] for r in order[:k]]


@app.post("/search")
def search(req: SearchRequest):
    try:
        results = search_passages(req.query, req.k)
        request_count.add(1, {"http.route": "/search", "outcome": "ok"})
        return {"results": results}
    except Exception:
        request_count.add(1, {"http.route": "/search", "outcome": "error"})
        raise


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        passages = search_passages(req.query, req.k)
        labelled = "\n\n".join(
            f"[{p['source']}#{p['chunk_index']}] ({p['heading_path']})\n{p['text']}"
            for p in passages
        )
        messages = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nPassages:\n{labelled}"},
            {"role": "user", "content": req.query},
        ]
        headers = {"Content-Type": "application/json"}
        if GATEWAY_API_KEY:
            headers["Authorization"] = f"Bearer {GATEWAY_API_KEY}"
        with timed("gateway", {
            "gen_ai.operation.name": "chat",
            "gen_ai.system": "envoy-gateway",
            "gen_ai.request.model": GATEWAY_MODEL,
        }):
            resp = requests.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                json={"model": GATEWAY_MODEL, "messages": messages},
                headers=headers,
                timeout=300,
            )
            resp.raise_for_status()
        body = resp.json()
        usage = body.get("usage", {})
        for token_type, value in (("input", usage.get("prompt_tokens")), ("output", usage.get("completion_tokens"))):
            if value is not None:
                token_usage.record(value, {
                    "gen_ai.request.model": GATEWAY_MODEL,
                    "gen_ai.token.type": token_type,
                })
        request_count.add(1, {"http.route": "/chat", "outcome": "ok"})
        return {
            "answer": body["choices"][0]["message"]["content"],
            "citations": [
                {
                    "source": p["source"],
                    "heading_path": p["heading_path"],
                    "chunk_index": p["chunk_index"],
                    "score": p["score"],
                }
                for p in passages
            ],
        }
    except Exception:
        request_count.add(1, {"http.route": "/chat", "outcome": "error"})
        raise


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
