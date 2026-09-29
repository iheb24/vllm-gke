# Embedding server benchmark — 2026-09-30

Model: Qwen3-Embedding-0.6B (1024-dim). Node: `rag-pool` e2-standard-4
(4 vCPU / 16 GB), us-central1-a. All pods pinned to `workload=rag`.

## Result: TEI (ONNX Runtime) wins

| Metric | TEI cpu-1.9.4 (ORT, fp32 ONNX) | llama.cpp server (Q8_0 GGUF) |
| --- | --- | --- |
| Starts on the node | yes, at 6Gi limit (2.3Gi real RSS) | yes, at 4Gi limit (~4Gi real) |
| Vector dim | 1024 | 1024 |
| Sanity (semantic > keyword pair) | PASS 0.582 > 0.393 | PASS 0.581 > 0.392 |
| Single short text, p50, in-cluster | ~110 ms | ~3 300 ms (via port-forward; in-cluster not measured — dominated by server, not network) |
| Single short text, p50, via port-forward | ~590 ms | ~3 350 ms |
| Batch of 100 chunks (~400 tok each) | 221 s | not run (batch of 32 took 166 s and repeatedly OOM-crashed before `--parallel 1`) |

Winner kept: `k8s/rag/embeddings/tei-deployment.yaml`, service `embed-tei`.
Loser deleted: `embed-llamacpp` (deployment and manifest).

## Why llama.cpp lost

~3.3 s for a 4-token embedding regardless of CPU quota (2 or 4 vCPUs, with and
without CPU limits) — a fixed per-request cost in the server path for this
GGUF, not resource starvation (node idle at 15% CPU). Batch requests fanned
out to 4 parallel slots and OOM-crashed until serialized with `--parallel 1`.

## TEI configuration lessons (the hard part)

| Attempt | Outcome |
| --- | --- |
| candle backend (`Qwen/Qwen3-Embedding-0.6B` safetensors, fp32) | OOMKilled during warmup at 2, 3, 4 and 6Gi — candle warmup allocates a full max-batch-tokens batch |
| ORT backend (`onnx-community/Qwen3-Embedding-0.6B-ONNX`), max-batch-tokens 4096 | OOMKilled during warmup at 3, 5 and 6Gi |
| ORT + `--pooling last-token` | required: the ONNX repo has no `1_Pooling/config.json` |
| ORT + `--max-batch-tokens 1024` | **works**, 2.3Gi RSS; warmup memory scales with this knob |
| batch of 100 | HTTP 422 until `--max-client-batch-size 128` (default 32) |

Every restart re-downloads ~1.2GB of weights (emptyDir cache) — a PVC for the
Hugging Face cache would make restarts faster; deferred.

## Budget check (from the execution plan)

- p50 single short text < 100 ms: in-cluster ~110 ms — marginally over; port-forward numbers (~590 ms) include internet RTT and are not representative. Accepted: query-path embedding adds ~0.1 s, invisible next to LLM latency.
- Batch of 100 chunks < 5 s: **not met** (221 s). This budget is unattainable for a 0.6B fp32 model on e2 CPUs (~180 tok/s). Ingestion is an async Job, so this is acceptable; revisit if ingestion windows matter.
- The original plan-sized e2-standard-2 pool could not host either server; the pool was resized to e2-standard-4 (~+$50/mo).
