#!/usr/bin/env python3
"""Latency/throughput benchmark for an OpenAI-compatible embedding server.

Usage: python bench/embed_bench.py --url http://localhost:8080 [--texts 100]

Budget (e2 CPU node): p50 single short text < 100 ms, batch of 100 chunks < 5 s.
Reads the API key from EMBED_API_KEY if set.
"""

import argparse
import json
import os
import statistics
import time
import urllib.request

SHORT_TEXT = "the pod keeps restarting with CrashLoopBackOff"
CHUNK = (
    "KEDA scales the GPU pool from zero when the HTTP interceptor observes "
    "pending requests for the vLLM backend. The cooldown period controls how "
    "long the pool stays warm after the last request finishes. "
) * 6


def embed(url, api_key, inputs):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": "qwen3-embedding", "input": inputs}
    req = urllib.request.Request(
        f"{url}/v1/embeddings", data=json.dumps(body).encode(), headers=headers
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    elapsed = time.perf_counter() - start
    vectors = [item["embedding"] for item in payload["data"]]
    return vectors, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--texts", type=int, default=100, help="batch size")
    parser.add_argument("--singles", type=int, default=50)
    args = parser.parse_args()
    api_key = os.environ.get("EMBED_API_KEY")

    latencies = []
    for _ in range(args.singles):
        vectors, elapsed = embed(args.url, api_key, SHORT_TEXT)
        latencies.append(elapsed)
    dim = len(vectors[0])
    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(0.95 * len(latencies)) - 1]

    print(f"vector dim:            {dim}")
    print(f"single short text p50: {p50 * 1000:.0f} ms  (budget < 100 ms)")
    print(f"single short text p95: {p95 * 1000:.0f} ms", flush=True)

    batch = [f"{CHUNK} chunk {i}" for i in range(args.texts)]
    vectors, batch_elapsed = embed(args.url, api_key, batch)

    print(
        f"batch of {args.texts} chunks:  {batch_elapsed:.2f} s total "
        f"(budget < 5 s), {len(vectors)} vectors"
    )

    ok = p50 < 0.1 and batch_elapsed < 5.0 and dim == 1024
    print("BUDGET:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
