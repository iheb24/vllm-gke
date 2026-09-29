#!/usr/bin/env python3
"""Sanity check: embeddings rank by meaning, not keywords.

sim("pod keeps restarting", "CrashLoopBackOff troubleshooting") must exceed
sim("pod keeps restarting", "monthly billing invoice"). Neither pair shares
keywords, so only semantic embeddings can rank them correctly.

Usage: python bench/similarity_sanity.py [--url http://localhost:8080]
"""

import argparse
import json
import math
import os
import urllib.request

QUERY = "pod keeps restarting"
SEMANTIC_MATCH = "CrashLoopBackOff troubleshooting"
UNRELATED = "monthly billing invoice"


def embed(url, api_key, texts):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": "qwen3-embedding", "input": texts}
    req = urllib.request.Request(
        f"{url}/v1/embeddings", data=json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    return [item["embedding"] for item in payload["data"]]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    api_key = os.environ.get("EMBED_API_KEY")

    q, sem, unrel = embed(args.url, api_key, [QUERY, SEMANTIC_MATCH, UNRELATED])
    sim_sem = cosine(q, sem)
    sim_unrel = cosine(q, unrel)

    print(f'sim("{QUERY}", "{SEMANTIC_MATCH}") = {sim_sem:.3f}')
    print(f'sim("{QUERY}", "{UNRELATED}") = {sim_unrel:.3f}')

    ok = sim_sem > sim_unrel
    print("SANITY:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
