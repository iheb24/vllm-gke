#!/usr/bin/env python3
"""Retrieval API: embed query -> Qdrant top-k -> prompt -> gateway.

POST /search returns ranked passages. POST /chat answers end-to-end through
the Envoy gateway with citations. Everything stays in-cluster; the only
credentials are the Qdrant API key and the existing gateway Bearer key.
"""

import os

import requests
from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "docs-v1")
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:8080")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8081")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "auto")
TOP_K = int(os.environ.get("TOP_K", "5"))

SYSTEM_PROMPT = """You answer questions using only the passages below.
Rules:
- Base every claim on the passages; never use outside knowledge.
- Cite each claim with [source#chunk_index] using the passage labels.
- If the passages do not answer the question, say it is not covered by the
  available documents. Do not guess.
"""

app = FastAPI()
qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


class SearchRequest(BaseModel):
    query: str
    k: int = TOP_K


class ChatRequest(BaseModel):
    query: str
    k: int = TOP_K


def embed(texts):
    headers = {"Content-Type": "application/json"}
    if EMBED_API_KEY:
        headers["Authorization"] = f"Bearer {EMBED_API_KEY}"
    resp = requests.post(
        f"{EMBED_URL}/v1/embeddings",
        json={"model": "qwen3-embedding", "input": texts},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def search_passages(query, k):
    vector = embed([query])[0]
    hits = qdrant.query_points(collection_name=COLLECTION, query=vector, limit=k).points
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


@app.post("/search")
def search(req: SearchRequest):
    return {"results": search_passages(req.query, req.k)}


@app.post("/chat")
def chat(req: ChatRequest):
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
    resp = requests.post(
        f"{GATEWAY_URL}/v1/chat/completions",
        json={"model": GATEWAY_MODEL, "messages": messages},
        headers=headers,
        timeout=300,
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"]
    return {
        "answer": answer,
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


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
