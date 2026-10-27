# Article packet: "Beyond RAG: Choosing Augmentation Patterns with vLLM on GKE"

Working outline for the series capstone article. Each section lists the
argument it must make, the repo artifacts that prove it, the figures/traces
to include, and the honesty caveat that must appear in print. Placeholders
that need the live cluster session are marked **[AWAITING LIVE RUN]** — no
number may be written into the article before its report exists. House
rules: no "best" / "most popular" claims, no unmeasured numbers, state
when task/corpus/model/prompt differ across methods.

## 1. Why augmentation ≠ RAG

**Argument**

- "Add knowledge to a model" is not one technique; decompose it into
  layers: parameters, prompt context, external data, runtime cache,
  conversational state.
- RAG owns exactly one layer (query-time document retrieval into context).
- The series implements one pattern per layer so the differences are
  visible in code, not just vocabulary.
- Set up the capstone question: which shape of state does *your* problem
  have?

**Repo artifacts**: `showcases/README.md` (taxonomy + demo contract),
`docs/augmented-generation-comparison.md` (framing + matrix).

**Figures**: the five-layers diagram (parameters / context / external data
/ cache / conversational state) with one pattern name per layer.

**Honesty caveat**: the four patterns are a curated architectural contrast,
not a ranking and not a complete survey (agentic RAG, GraphRAG, corrective
retrieval, tool use exist and were not built).

## 2. Acronym warning and taxonomy

**Argument**

- RAG/TAG/CAG/MAG/KAG are not a standardized family; the same letters are
  used for different things elsewhere.
- Definitions used in this series: RAG = Retrieval-; TAG = Table- (not
  Tool-); CAG = Cache- (not Context-); MAG = Memory- (no single canonical
  algorithm); KAG = Knowledge-Augmented Generation, specifically
  OpenSPG/KAG.
- The selection criterion is architectural contrast in the request path.

**Repo artifacts**: `showcases/README.md` (acronym disambiguation table).

**Figures**: the disambiguation table, trimmed for print.

**Honesty caveat**: always qualify MAG (application-level memory, not
MemOS) and KAG (OpenSPG framework, article-only here) on first use.

## 3. The reference stack

**Argument**

- Everything runs on one small GKE stack: tiered serving (CPU SLM + one L4
  GPU), semantic routing, scale-to-zero, ClusterIP-only.
- Constraints that shaped the demos: one GPU, cold starts measured in
  minutes, a system node near capacity.
- The RAG stack is the unchanged baseline with enforced quality gates.

**Repo artifacts**: `docs/semantic-routing-walkthrough.md`,
`docs/cost-checkpoint.md`, `retrieval/main.py`, `k8s/rag/README.md`,
`agent.md` (project constraints).

**Figures**: topology diagram from `docs/semantic-routing-walkthrough.md`;
idle/variable cost table from `docs/cost-checkpoint.md`.

**Honesty caveat**: measured timings (cold start ~3-4 min warm PVC, ~7.5
min cold PVC) are this cluster's measurements, cited from
`docs/cost-checkpoint.md`, not generic GKE numbers.

## 4. RAG chapter (baseline)

**Argument**

- Request path: embed → hybrid search (dense + BM25, RRF) → rerank →
  generate with citations.
- Retrieval quality gates exist and are enforced (hit@5 ≥ 0.90, MRR ≥
  0.75); before/after reports ship with every retrieval-affecting change.
- RAG's failure mode is upstream of the model: if the right chunk is not
  retrieved, no generation fixes it.

**Repo artifacts**: `retrieval/main.py`, `eval/run_eval.py`,
`eval/golden_questions.yaml`, `eval/reports/2026-09-30-hybrid-rerank.md`.

**Figures**: RAG request-path diagram; the measured gate table from
`eval/reports/2026-09-30-hybrid-rerank.md` (hit@5 1.00, MRR 0.95 — real
measurement, cite the date).

**Honesty caveat**: the RAG numbers are real but measure *this* corpus and
golden set only; they are not reused as a yardstick for the other methods
(different tasks and evidence types).

## 5. TAG chapter

**Argument**

- Request path: synthesize SQL → engine-level guard validates and executes
  → reason over rows (including semantic classification of free-text
  notes).
- The security boundary is the SQLite authorizer + budgets, not the
  prompt; the repair loop feeds guard errors back to the model and then
  fails closed.
- The flagship question mixes exact aggregation (top-3 cost days) with
  meaning (capacity vs configuration) — the combination plain text2SQL
  misses.

**Repo artifacts**: `showcases/tag/` (`sql_guard.py`, `pipeline.py`,
`app.py`, `data/seed.sql`), `eval/showcases/tag_questions.yaml`,
`eval/reports/2026-10-27-tag-local-fake.md`.

**Figures**: three-stage diagram; flagship trace JSON (validated SQL +
rows + `sql_attempts`); guard rejection example from the invalid eval
cases.

**Honesty caveat**: minimal three-stage pipeline — not the TAG paper's
LOTUS operators or TAG-Bench scores; demo data is synthetic, not real GCP
billing; the 17/17 report is a fake-model harness baseline. Live model
results **[AWAITING LIVE RUN]** (`eval/reports/2026-10-27-tag-live.md`).

## 6. CAG chapter

**Argument**

- Request path: build a byte-identical static prefix (manifest-pinned
  corpus) → single generation. No retrieval stage exists.
- The claim is narrow: prefix caching should skip re-prefilling a stable
  corpus — nothing about decode, nothing about pod startup.
- Budget discipline: corpus ≤ 12,000 tokens measured with the served
  model's tokenizer; over-budget requests fail before any model call.

**Repo artifacts**: `showcases/cag/` (`corpus.py`, `build_manifest.py`,
`benchmark.py`, `corpus/manifest.json`),
`eval/reports/2026-10-27-cag-local-fake.md`,
`eval/reports/2026-10-27-cag-live.md`.

**Figures**: prefix-build diagram; per-file token budget table from
`corpus/manifest.json` (7,628 / 12,000); counter table
**[AWAITING LIVE RUN]** (`vllm:prefix_cache_queries`/`_hits` before/after,
verdict VERIFIED/NOT VERIFIED from `benchmark.py`); TTFT samples table
**[AWAITING LIVE RUN]**.

**Honesty caveat**: the article must print **CACHE REUSE NOT VERIFIED**
until counter deltas are recorded; latency is never cache evidence; the
fake-model report is quality-only.

## 7. MAG chapter

**Argument**

- Request path: explicit `remember:`/API writes only; per-chat FTS5
  retrieval of user memories + bounded session turns → generate.
- Memory is untrusted data: delimited block, sanitization, secret guard,
  contract that memories never override.
- Isolation and lifecycle are the product: cross-session recall,
  cross-user invisibility, correction-as-supersede, soft delete, PVC
  persistence with explicit purge.

**Repo artifacts**: `showcases/mag/` (`memory_store.py`, `pipeline.py`,
`app.py`), `k8s/showcases/mag/pvc.yaml`, `eval/showcases/mag_scenarios.yaml`,
`eval/reports/2026-10-27-mag-local-fake.md`.

**Figures**: Alice/Bob transcript (remember → new session recall → Bob's
empty view → correction → deletion) with real response excerpts;
memory-lifecycle state diagram (active → superseded/deleted).

**Honesty caveat**: application-level memory — not MemOS, no parameter
change; `user_id` is not authentication; keyword retrieval only; the 5/5
report is a fake-model harness baseline. Live model results
**[AWAITING LIVE RUN]** (`eval/reports/2026-10-27-mag-live.md`).

## 8. KAG chapter (article within the article)

**Argument**

- The gap the four patterns leave: answers that live in typed
  relationships (what depends on what), multi-hop with provenance.
- What OpenSPG/KAG actually is (schemaful graph + logical-form-guided
  mutual indexing), and what it costs operationally.
- A concrete multi-hop troubleshooting question over this repo's own
  components, plus the go/no-go checklist for a future spike.

**Repo artifacts**: `docs/kag-architecture.md` (the whole chapter sources
from it), `retrieval/main.py` (the `/search` vs `/chat` dependency
example).

**Figures**: the dependency-mini-graph for the example question;
decision checklist table.

**Honesty caveat**: **article-first** — no code, no OpenSPG deployment, no
hand-rolled graph script anywhere in the repo; a hand-written traversal
must never be labelled KAG.

## 9. What was not built and why

**Argument**

- Persistent KV offload (LMCache): prove basic prefix-cache counters
  first.
- LOTUS/TAG-Bench reproduction: the demo shows the path, not the paper.
- MemOS/trainable memory and automatic memory extraction: application
  memory stays explicit and auditable.
- Generic GraphRAG: mislabeling risk; the KAG article documents the real
  gap instead.
- A `method`-switch mega-service and permanent demo branches: separate
  small services and short-lived branches keep request paths visible.

**Repo artifacts**: `docs/augmented-generation-comparison.md` (not-built
list), `showcases/demo.sh` (one-at-a-time model).

**Figures**: none needed; optionally a "road not taken" table.

**Honesty caveat**: absence is a decision with stated reasons, not an
oversight — each item says what would justify building it later.

## 10. Decision guide

**Argument**

- Pick by data shape first: documents → RAG; rows + free-text meaning →
  TAG; small static bounded corpus → CAG; per-user state → MAG; typed
  relations → (today) RAG-over-runbooks or the KAG spike checklist.
- Then filter: freshness, corpus size, session state, relationship
  complexity, evidence needs, latency budget, operational budget.
- Hybrids exist (RAG+MAG personalization; TAG over RAG-harvested tables)
  but are compositions with their own request paths and evals.

**Repo artifacts**: `docs/augmented-generation-comparison.md` (decision
matrix + guide), each `showcases/*/README.md`.

**Figures**: the decision matrix (trimmed); a one-line-per-shape "start
here" flowchart.

**Honesty caveat**: no universal winner; cross-method comparisons must
state task, corpus, model, and prompt; do not run one method's dataset
through another's pipeline to manufacture a loser.

## 11. Measured results and limitations

**Argument**

- Publish only what was measured: the RAG baseline numbers (dated, live
  stack) and the fake-model harness baselines, clearly labelled.
- The showcase live runs are **[AWAITING LIVE RUN]**: TAG live eval, CAG
  benchmark + eval, MAG scenarios against the real gateway.
- CAG's chapter cannot claim reuse until `vllm:prefix_cache_hits` deltas
  are in the report; the readiness/prime/warm phase separation must be
  explained so prefill is never confused with pod startup.
- Close on limits: synthetic data, single-node SQLite, one GPU, keyword
  retrieval, minimal pipelines — and the exact commands a reader runs to
  reproduce everything.

**Repo artifacts**: `eval/reports/` (all files), the three
`*-local-fake.md` baselines, the three `*-live.md` placeholders with exact
commands, `showcases/demo.sh`, `showcases/tests/`.

**Figures**: results-status table from
`docs/augmented-generation-comparison.md` §Measured results status;
**[AWAITING LIVE RUN]** the completed live tables (TAG eval pass rates,
CAG counter deltas + TTFT samples, MAG scenario results).

**Honesty caveat**: if a number is not in `eval/reports/`, it does not go
in the article; fake-model baselines prove harness mechanics, never model
quality.
