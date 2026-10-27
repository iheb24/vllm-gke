# Augmented-Generation Showcases

This directory evolves `vllm-gke` from a RAG-on-GKE example into a small, honest,
reproducible showcase of augmentation patterns. Each pattern solves a different
problem and exposes its mechanics, evidence, limitations, and measurements. This
is not a race to deploy every framework, and there is no universally best method.

## Acronym disambiguation

These acronyms are not a single, universally standardized family. Always use the
full names in READMEs, API responses, diagrams, and articles.

| Acronym | Meaning in this project | Status |
| --- | --- | --- |
| RAG | Retrieval-Augmented Generation | Implemented baseline (document QA). Unchanged. |
| TAG | **Table-Augmented Generation** (not Tool-Augmented Generation) | Showcase: structured serving analytics. |
| CAG | **Cache-Augmented Generation** (not Context-Augmented Generation) | Showcase: static corpus + vLLM prefix-cache reuse. |
| MAG | **Memory-Augmented Generation** (not Multi-Agent Generation) | Showcase: application-level persistent memory. Always qualify the name; there is no single canonical MAG algorithm. |
| KAG | **Knowledge-Augmented Generation**, specifically the OpenSPG/KAG framework | Article-first only (`docs/kag-architecture.md`). No code showcase. |

## Why these patterns

The selection is justified by architectural contrast, not acronym popularity.
Each method produces a visibly different request path:

- **RAG**: retrieve document chunks at query time (embed → hybrid search → rerank → generate with citations).
- **TAG**: synthesize and execute a structured SQL query, then reason semantically over the returned rows.
- **CAG**: reuse a stable, bounded corpus prefix and the model-side KV cache; no online retrieval at all.
- **MAG**: persist and retrieve user-scoped memory across sessions; state lives in an application store, not a document index.

Agentic RAG, GraphRAG, corrective/self-reflective retrieval, and tool use are
legitimate alternatives that were not built; the comparison document explains
the wider design space. Do not claim these four are "the most popular" choices.

## The showcases

| Demo | Question type | Local port | Directory |
| --- | --- | ---: | --- |
| RAG (baseline) | "What do the repository documents say about X?" | 8090 | `retrieval/`, `k8s/rag/` |
| TAG | "On the three most expensive GPU days, do incident notes point to capacity or configuration problems?" | 8091 | `showcases/tag/` |
| CAG | "What does the operations handbook say about X?" (no retrieval) | 8092 | `showcases/cag/` |
| MAG | "Given what I told you last session, which tier should I use?" | 8093 | `showcases/mag/` |
| KAG | Multi-hop troubleshooting over a component graph | — | `docs/kag-architecture.md` (article only) |

### RAG regression baseline

The existing RAG stack is the baseline and must stay intact. Recorded baseline:

- API: `POST /search`, `POST /chat`, `GET /healthz`, `GET /metrics` (`retrieval/main.py`).
- Eval: `python eval/run_eval.py [--url http://localhost:8090] [--questions eval/golden_questions.yaml] [--report eval/reports/<date>.md]`
- Quality gates: hit@5 ≥ 0.90 and MRR ≥ 0.75 on the in-scope questions of
  `eval/golden_questions.yaml` (46-question set; out-of-scope questions reported separately).
- Every retrieval-affecting change must ship a before/after eval report under `eval/reports/`.

Showcase phases must not change RAG behavior, APIs, the collection, or these
gates. Do not reimplement RAG under `showcases/`; link to `docs/rag-architecture.md`,
`docs/rag-implementation.md`, and `k8s/rag/README.md` instead.

## Demo contract

Each deployable demo (`tag`, `cag`, `mag`) has:

- Its own README with purpose, request path, exact demo script, limitations, and cleanup.
- `GET /healthz` and `GET /metrics`.
- A small FastAPI API using the existing gateway Bearer-key convention
  (`GATEWAY_URL`, `GATEWAY_API_KEY`; same `vllm-api-key` secret in-cluster).
- A consistent top-level response shape where practical:
  `method`, `answer`, `evidence`, `trace`, `usage`. The method-specific `trace`
  shows what actually happened (validated SQL and rows for TAG; corpus version
  and cache status for CAG; injected memory IDs for MAG).
- Metrics prefixed `ag_demo_<method>_*`, keeping the existing GenAI client
  conventions (`gen_ai.client.*`) where practical. Do not overload `rag.retrieval.*`.
- Unit tests with a fake model transport: the default test run needs no GPU,
  no gateway, and no network.
- Optional live integration tests enabled only by explicit environment variables.
- ClusterIP-only manifests, resource requests/limits, no public ingress.
- No change to Terraform, the base vLLM release, the semantic router, or the
  RAG stack for normal demo startup.

## Deployment model: one at a time

The cluster has one GPU and limited CPU. Showcases are deployed **one at a
time** with `showcases/demo.sh <up|down|status|port-forward|purge> <tag|cag|mag>`:
`up` refuses to start a second showcase unless `--force` is given (detected via
the `ag-showcase` label on the Deployments under `k8s/showcases/`), and prints
the active method, the port-forward command, and the cleanup command. MAG
teardown retains its PVC by default; only an explicit `purge mag` (with
confirmation) deletes memories. Each demo's README has a Kubernetes deployment
section with build/push commands; each image is built from its own
`showcases/<method>/Dockerfile`.

Showcase branches are short-lived and merge back to `main`; there are no
permanent divergent demo branches.

## Testing policy

- Default: `python -m pytest showcases/<method>/tests` — pure local, fake model
  transport, temporary SQLite/files, no network. Install dev dependencies from
  `showcases/requirements-dev.txt`. Run suites one showcase at a time (the flat
  `app.py` module names cannot coexist in one pytest process).
- Cross-cutting deployment checks: `python -m pytest showcases/tests` —
  manifest contract, `demo.sh` behavior against a stubbed `kubectl`, and
  container-less image-layout boot proofs. No app-module imports, no cluster
  needed (kubectl dry-run checks self-skip without one).
- Live tests: opt-in via environment variables (e.g. `AG_LIVE=1` plus gateway
  configuration) and only ever run with explicit human approval, per `agent.md`.
- Evaluations live under `eval/showcases/` (questions/scenarios) with runners
  following the `eval/run_eval.py` conventions and reports under `eval/reports/`.
- No invented benchmark results. If a live cluster or model was not used, the
  report says `NOT RUN` instead of presenting sample numbers as measurements.
- Each method has its own success evidence; do not reuse hit@5/MRR where it
  does not measure the method, and do not set cross-method "X% faster" gates
  before a reviewed baseline exists.

## CAG discovery checklist (for the live session)

The chart pins `vllm/vllm-openai:latest`, so the actual version must be captured
when a cluster is available — do not assume `latest` behaves identically over time.

1. Record the resolved image digest and vLLM version
   (`kubectl get pod -n vllm -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'`
   and the `/version` endpoint or server logs).
2. Verify automatic prefix caching is enabled for that version (default-on in
   recent vLLM V1; confirm via startup logs / engine args).
3. Capture the exact prefix-cache metric names exposed on `/metrics`
   (e.g. `vllm:prefix_cache_queries`, `vllm:prefix_cache_hits` on recent versions)
   and configure the benchmark accordingly.
4. Record model name, image, cache configuration, and `maxModelLen` in the CAG report.
5. Only after the above: run warm-up, cold/warm measurements, and the optional
   pod-restart lifecycle test.

## Target tree

```text
showcases/
  README.md          # this file
  demo.sh            # one-at-a-time manager: up/down/status/port-forward/purge
  requirements-dev.txt
  tests/  (test_manifests.py, test_demo_sh.py, test_image_layout.py)
  tag/  (app.py, pipeline.py, sql_guard.py, db.py, data/, tests/, Dockerfile, requirements.txt, README.md)
  cag/  (app.py, corpus.py, benchmark.py, corpus/, tests/, Dockerfile, requirements.txt, README.md)
  mag/  (app.py, pipeline.py, memory_store.py, tests/, Dockerfile, requirements.txt, README.md)
k8s/showcases/
  tag/deployment.yaml
  cag/deployment.yaml
  mag/deployment.yaml, pvc.yaml
eval/
  showcases/ (tag_questions.yaml, cag_questions.yaml, mag_scenarios.yaml)
  reports/
docs/
  augmented-generation-comparison.md
  kag-architecture.md
```

Small duplication between demos is acceptable; do not extract a shared framework
until all three APIs work, and then only in a separate refactor PR with
regression tests.

## Honesty policy

- Synthetic demo data is clearly labelled; TAG numbers are not real GCP billing
  or production telemetry.
- CAG is not "completed" until live prefix-cache counter movement is observed;
  until then it is labelled `CACHE REUSE NOT VERIFIED`.
- MAG is application-level Memory-Augmented Generation — not MemOS, not a
  trainable memory architecture, not a change to model parameters.
- KAG is article-first. A hand-written graph traversal must never be labelled KAG.
- No universal winner: comparisons state when task, corpus, model, and prompt differ.

## References

- TAG: [Text2SQL is Not Enough: Unifying AI and Databases with TAG](https://arxiv.org/abs/2408.14717), [TAG-Bench](https://github.com/TAG-Research/TAG-Bench)
- CAG: [Don't Do RAG: When Cache-Augmented Generation is All You Need for Knowledge Tasks](https://arxiv.org/abs/2412.15605), [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/), [vLLM metrics](https://docs.vllm.ai/en/stable/design/metrics/)
- MAG background: [MemOS](https://arxiv.org/abs/2505.22101), [Mem0](https://arxiv.org/abs/2504.19413)
- KAG: [KAG paper](https://arxiv.org/abs/2409.13731), [OpenSPG/KAG](https://github.com/OpenSPG/KAG)
