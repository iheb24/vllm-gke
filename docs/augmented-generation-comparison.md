# Beyond RAG: Choosing Augmentation Patterns

Comparison capstone for the series *"Beyond RAG: Choosing Augmentation
Patterns with vLLM on GKE"*. Audience: you read the main README, you have a
question-answering problem, and you want to pick a pattern without
cargo-culting one.

## Framing: augmentation is not synonymous with RAG

"Augmentation" gets used as if it meant one technique. It helps to separate
the layers an answer can draw on: the **model parameters** (fixed at serving
time), the **prompt context** (whatever you put in front of the model this
request), **external data** (documents, rows, graphs you retrieve or inject),
the **runtime cache** (KV blocks the server may reuse across requests), and
**conversational state** (what the system remembers between requests and
sessions). Retrieval-Augmented Generation owns exactly one of these —
query-time retrieval of external documents into the prompt context. The
patterns in this repository each deliberately own a different one: TAG turns
natural language into structured queries over external relational data, CAG
makes a fixed prompt prefix cheap via the runtime cache, MAG owns per-user
conversational state, and KAG (article-only here) targets explicit typed
relations between facts. None of them changes model parameters.

## Decision matrix

| | RAG (baseline) | TAG | CAG | MAG | KAG (article only) |
| --- | --- | --- | --- | --- | --- |
| **Question shape** | "What do the repository documents say about X?" | "What do the rows say, and what does the free text in them mean?" | Repeated questions about one small, stable handbook | "Given what I told you before, what should I do?" | Multi-hop questions over typed relationships |
| **Data shape** | Unstructured document chunks | Relational rows in one schema | Bounded, versioned prompt prefix | Per-user memories + session turns | Typed graph nodes/edges + linked chunks |
| **Corpus size** | Large; grows by ingestion (versioned collection) | Small; one database (demo: 72 rows) | Hard-bounded (demo: 7,628 of 12,000 budgeted tokens) | Small per user; grows with use | Medium; graph + text units |
| **Freshness tolerance** | High — re-ingest updates the index | As fresh as the database | Low — an edit is a new corpus version (sha-pinned manifest) | Immediate — explicit writes only | Graph maintenance decides |
| **State lifetime** | Index lifetime (PVC) | Database lifetime | Process-local KV cache (dies with the pod) | User lifetime (PVC, survives restarts until purged) | Graph store lifetime |
| **Online stages per request** | embed → hybrid search (dense+BM25, RRF) → rerank → generate | synthesize SQL → validate + execute (guarded) → reason over rows | build static prefix → generate | retrieve memories + session turns → generate (plus an explicit `remember:` write path) | plan → graph+chunk mutual retrieval → iterative reasoning |
| **Infrastructure** | Qdrant + TEI embeddings + sparse BM25 (+ optional reranker) + ingestion CronJob | SQLite (single file) | Nothing beyond the gateway and the model server's prefix cache | SQLite on a PVC (single replica) | OpenSPG/KAG stack (graph store, builder, solver) — not deployed |
| **Evidence type** | Citations `[source#chunk_index]` | Validated SQL + returned rows | Corpus version + trace (`cache_verified: false` until proven) | Injected memory ids + per-stage trace | Logical forms + provenance paths |
| **Measured by** | hit@5, MRR on golden questions | Execution success + exact-answer accuracy + rubric mentions | Prefix-cache counter deltas + TTFT (live); rubric (quality) | Scenario lifecycle: recall, isolation, correction, deletion | Multi-hop evidence sets |
| **Best-fit use case** | Open-ended QA over large, changing document sets | Analytics over structured metrics/logs with free-text fields | Hot, repeated QA over a small stable corpus | Per-user preferences and continuity across sessions | Troubleshooting/diagnosis where answers live in relationships |
| **Main limitation** | Retrieval ceiling: if the right chunk is not retrieved, no model can answer | Schema-bounded; minimal three-stage pipeline, not the TAG paper's LOTUS operators | Prefill-only savings; block/prefix-dependent eviction; small stable corpora only | Keyword retrieval (FTS5); `user_id` is not authentication | Real operational cost (graph schema, builder, solver); unproven in this stack |

## The patterns in this repo

### RAG — Retrieval-Augmented Generation (baseline)

The existing stack is unchanged and remains the reference point: hybrid
retrieval (dense embeddings + BM25 with RRF fusion) over a versioned Qdrant
collection, reranking, then generation through the gateway with citations.
Request path and deployment: `retrieval/main.py`, `k8s/rag/README.md`. Its
quality is gated: hit@5 ≥ 0.90 and MRR ≥ 0.75 on the 46-question golden set
(`eval/run_eval.py`), and every retrieval-affecting change ships a
before/after report. The most recent recorded run
(`eval/reports/2026-09-30-hybrid-rerank.md`) measured hit@5 1.00, MRR 0.95 —
that is a real measurement on the live stack, unlike the showcase live runs
below.

### TAG — Table-Augmented Generation

What it is: the model writes one read-only SQL statement, an engine-level
guard (SQLite authorizer + opcode budget + row cap) decides what may run,
and the model answers strictly from the returned rows — including
classifying free-text incident notes by meaning. Request path:
`showcases/tag/` (`pipeline.py`, `sql_guard.py`, `app.py`). Flagship
question: "On the three most expensive GPU days, summarize whether the
incident notes point mainly to capacity problems or configuration
problems." Evidence you can inspect: `evidence.sql`, `evidence.rows`,
`trace.sql_attempts` (including the repair loop when the guard rejects).
Honesty label: this is a **minimal three-stage pipeline** — not a
reproduction of the TAG paper's LOTUS operator pipelines or TAG-Bench
results. Demo README: `showcases/tag/README.md`.

### CAG — Cache-Augmented Generation

What it is: the entire operations-handbook corpus (six verbatim extracts,
sha-pinned by a manifest, 7,628 tokens measured with the served model's
tokenizer) is a byte-identical system prefix on every request; the only
acceleration mechanism is vLLM automatic prefix caching. There is no
retrieval anywhere in the request path. Request path: `showcases/cag/`
(`corpus.py`, `app.py`, `benchmark.py`). Flagship property (not a question):
warm requests should skip re-prefilling the corpus. Evidence you can
inspect: `evidence.corpus_version`, `ag_demo_cag_prefix.tokens`, and — in
the live session — vLLM prefix-cache counter deltas from `benchmark.py`.
Honesty label: **CACHE REUSE NOT VERIFIED** until the live benchmark
records `vllm:prefix_cache_hits` deltas; latency is never used as cache
evidence. Demo README: `showcases/cag/README.md`.

### MAG — Memory-Augmented Generation

What it is: a cross-session assistant with transparent, explicit,
user-scoped memory. Writes are deliberate only (`remember:` or
`POST /memories`), retrieval is FTS5 keyword search, and injected memories
are untrusted data inside a sanitized, delimited block. Request path:
`showcases/mag/` (`memory_store.py`, `pipeline.py`, `app.py`). Flagship
flow: Alice stores a preference in session A and recalls it from session B,
while Bob can neither see nor modify it. Evidence you can inspect:
`evidence.memory_ids`, `trace.stages`, `GET /memories?user_id=...`.
Honesty label: **application-level** memory — not MemOS, not a trainable
memory architecture, not a change to model parameters; `user_id` is a
scoping label, not authentication. Demo README: `showcases/mag/README.md`.

### KAG — Knowledge-Augmented Generation (article only)

What it is: the OpenSPG/KAG framework — schemaful knowledge-graph
construction with logical-form-guided, mutual indexing between graph and
text. In this repository it exists as an architecture article
(`docs/kag-architecture.md`) with a concrete multi-hop troubleshooting use
case and a go/no-go spike checklist. There is **no code**: no OpenSPG
deployment, no hand-written graph script (a hand-rolled traversal would
not be KAG and is never labelled as such). Honesty label: **article-first**.

## What was deliberately not built

- **Persistent/distributed KV offloading** (e.g. LMCache): the CAG claim is
  scoped to stock vLLM automatic prefix caching; adding a cache tier before
  proving the basic counters move would be premature.
- **A LOTUS/TAG-Bench reproduction**: the TAG demo shows the request path
  (synthesize → guard → reason), not the paper's operator runtime or
  benchmark scores.
- **MemOS / trainable memory**: MAG is application-level state in SQLite;
  no parameter changes, no memory scheduling algorithms.
- **Automatic memory extraction**: letting the model decide what to
  remember is deferred on purpose — every stored memory stays user-authored
  and auditable.
- **Generic GraphRAG**: the graph-shaped gap is documented in the KAG
  article; building a bespoke traversal and calling it KAG would be
  mislabeling.
- **A `method`-switch mega-service**: the demos are separate small services
  so each request path stays visible; a merged service would hide the
  differences this series exists to teach.
- **Permanent demo branches**: showcase branches merge back to `main`; the
  one-at-a-time deployment model (`showcases/demo.sh`) handles concurrency
  at the cluster, not in git.

## Decision guide

Start from the **data shape**, not the acronym:

1. **Documents, large and changing** → RAG. You need ingestion, an index,
   and retrieval metrics (hit@5/MRR) before anything else.
2. **Rows in a known schema; questions mix aggregation and free-text
   meaning** → TAG. You need a query guard more than you need a bigger
   model.
3. **Small, bounded, stable corpus with hot repeated questions** → CAG —
   but only after prefix-cache reuse is verified with counters, and only
   while the corpus fits the context budget with margin.
4. **Per-user state that must cross sessions** → MAG. You need explicit
   writes, isolation, correction, and deletion more than you need
   embeddings.
5. **Answers that live in typed relationships** (what depends on what,
   multi-hop) → the KAG article's use case; today, answer those with RAG
   over runbooks and accept the limitation, or follow the spike checklist.

Then filter by: **freshness** (RAG/TAG/MAG update cheaply; CAG reissues a
corpus version), **corpus size** (CAG is the only hard-bounded one),
**session state** (only MAG owns it), **relationship complexity** (only
KAG targets it), **evidence needs** (citations vs SQL+rows vs cache
counters vs memory ids vs provenance paths), **latency budget** (RAG adds
retrieval stages; TAG adds synthesis+execution; CAG should be
prefill-cheap when warm — unproven here; MAG adds one small lookup), and
**operational budget** (Qdrant+TEI vs one SQLite file vs nothing new vs a
PVC vs an OpenSPG stack).

Hybrids are legitimate and sometimes the right answer: RAG + MAG gives
document grounding with per-user personalization; TAG can run over tables
harvested by a RAG ingestion pass. Treat these as compositions with their
own request paths and eval sets, not as free upgrades — each added stage is
another place to be wrong.

## Measured results status

| artifact | status |
| --- | --- |
| `eval/reports/2026-09-30*.md` (RAG baseline) | **Measured on the live stack** (latest: hit@5 1.00, MRR 0.95, gate PASS) |
| `eval/reports/2026-10-27-tag-local-fake.md` | Fake-model harness baseline (17/17). Validates the pipeline/guard/eval harness, **not model quality** |
| `eval/reports/2026-10-27-cag-local-fake.md` | Fake-model harness baseline (15/15), quality only; **no latency or cache claims** |
| `eval/reports/2026-10-27-mag-local-fake.md` | Fake-model harness baseline (5/5 scenarios) |
| `eval/reports/2026-10-27-tag-live.md` | **NOT RUN** — commands prepared for the live session |
| `eval/reports/2026-10-27-cag-live.md` | **NOT RUN** — includes the vLLM discovery checklist; the CAG reuse claim requires recorded `vllm:prefix_cache_*` counter deltas before any latency reading |
| `eval/reports/2026-10-27-mag-live.md` | **NOT RUN** |

Until the live runs exist, every showcase number in this repository is a
deterministic harness number, and the CAG demo carries its
`CACHE REUSE NOT VERIFIED` label in code (`trace.cache_verified: false`),
in its README, and here.

## Fair-comparison warning

Do not manufacture a winner. Forcing the TAG seed data through a RAG
pipeline (or the CAG corpus through TAG's guard) would compare a method
against data it was not designed for, and the outcome would say nothing.
The four demos intentionally use **different tasks, corpora, evidence
types, and eval sets**; where they share infrastructure (the gateway, the
served model), say so, and where prompts and models differ, say that too.
Any cross-method statement must name task, corpus, model, and prompt
alongside the number. There is no universal winner among these patterns —
there are only shapes of state and the questions that fit them.
