# CAG eval — 2026-10-27

> FAKE-MODEL HARNESS BASELINE: the model side is the scripted deterministic extractive transport (CAG_FAKE_MODEL=1), not a real LLM. This run validates the API, corpus pinning, and eval harness end-to-end; it is NOT a model-quality measurement. CACHE REUSE NOT VERIFIED.

url: http://localhost:8092  
questions: 15 (corpus 12/12, out_of_corpus 3/3)

| type | passed | total |
| --- | --- | --- |
| corpus | 12 | 12 |
| out_of_corpus | 3 | 3 |

Quality report only: no latency claims. `corpus` failures fail the run because the corpus is fixed and the expected mentions are deterministic.

## Per-question results

- [PASS] (corpus) `routing-model-modes`: Which model value forces the CPU tier, and which forces the GPU tier?
  - [x] source: routing-architecture.md
  - [x] mention: qwen3-4b-cpu
  - [x] mention: Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
- [PASS] (corpus) `cold-start-timings`: How long does a GPU cold start take with a warm PVC and with a cold PVC?
  - [x] source: routing-architecture.md
  - [x] mention: 3-4
  - [x] mention: 7.5
  - [x] mention: 300
- [PASS] (corpus) `timings-field-breakage`: What breaks when llama.cpp's timings field reaches the semantic router?
  - [x] source: gateway-integration.md
  - [x] mention: timings
  - [x] mention: invalid_upstream_json
- [PASS] (corpus) `backend-authentication`: How do the vLLM and llama.cpp backends authenticate client requests?
  - [x] source: gateway-integration.md
  - [x] mention: Bearer
  - [x] mention: vllm-api-key
  - [x] mention: 401
- [PASS] (corpus) `expose-gateway`: How do you expose the gateway to local clients?
  - [x] source: operator-guide.md
  - [x] mention: port-forward
  - [x] mention: 8081
- [PASS] (corpus) `invalid-inference-request`: What does a 400 invalid inference request mean and how do you fix it?
  - [x] source: operator-guide.md
  - [x] mention: case-sensitive
  - [x] mention: exact names
- [PASS] (corpus) `idle-monthly-cost`: What is the idle monthly cost of the stack?
  - [x] source: cost-model.md
  - [x] mention: $100
  - [x] mention: e2-standard-4
- [PASS] (corpus) `minimum-gpu-wake-budget`: What is the minimum billed time to budget per GPU wake?
  - [x] source: cost-model.md
  - [x] mention: 10-15
  - [x] mention: 300
- [PASS] (corpus) `false-positives-accepted`: Why does the routing stack accept false positives?
  - [x] source: routing-behavior.md
  - [x] mention: false negative
  - [x] mention: small model
- [PASS] (corpus) `observe-routing-decisions`: Which response headers and log events show the router's decision?
  - [x] source: routing-behavior.md
  - [x] mention: x-vsr
  - [x] mention: routing_decision
- [PASS] (corpus) `rag-pool-reason`: Why was a dedicated rag-pool introduced?
  - [x] source: rag-design.md
  - [x] mention: TEI
  - [x] mention: OOM
  - [x] mention: e2-standard-4
- [PASS] (corpus) `rag-answering-tier`: Which tier answers RAG questions and why?
  - [x] source: rag-design.md
  - [x] mention: qwen3-4b-cpu
  - [x] mention: GPU wake
- [PASS] (out_of_corpus) `oos-capital-of-france`: What is the capital of France?
- [PASS] (out_of_corpus) `oos-gmail-password`: How do I reset my Gmail password?
- [PASS] (out_of_corpus) `oos-hamlet`: Explain the plot of Hamlet.
