# KAG — Knowledge-Augmented Generation (article-first)

**Status: article only.** There is no KAG code in this repository, no OpenSPG
deployment, and no custom graph script. This document explains what
Knowledge-Augmented Generation (specifically the OpenSPG/KAG framework) would
add over the four implemented patterns, what it costs, and the exact conditions
under which a future spike would be justified. A spike happens only after
explicit human approval, in a separate ADR and follow-up plan.

## 1. The gap the four patterns leave open

Each implemented pattern owns a different state shape:

| Pattern | State it exploits | What it cannot do |
| --- | --- | --- |
| RAG | Document chunks in a vector/lexical index | Reason over explicit typed relationships; chain facts across documents with provenance |
| TAG | Rows in one relational schema | Anything outside that schema |
| CAG | A bounded, static prompt prefix | Fresh or large corpora; relationship queries |
| MAG | Per-user memories | Shared, structured system knowledge |

None of them maintains a **typed graph of the system itself**: which component
runs on which node pool, which route fronts which model, which deployment reads
which secret key, which symptom maps to which runbook. Questions whose answers
live in the *relationships* — not in any single document, table, or memory —
are where Knowledge-Augmented Generation aims.

## 2. The proposed use case: multi-hop troubleshooting

**Example question:** "After reinstalling the semantic routing stack, why can
the retrieval `/chat` endpoint fail while `/search` still works, and which
gateway URL and secret must be checked?"

This is a real property of this repository, not a contrived example:

- `retrieval/main.py` implements `/search` using only the embedding server and
  Qdrant — both inside the `rag` namespace. No gateway involvement.
- `/chat` additionally POSTs to `{GATEWAY_URL}/v1/chat/completions` with a
  Bearer token from the `vllm-api-key` secret (key `api-key`).
- The deployed `GATEWAY_URL` points at an Envoy service whose name carries a
  generated hash suffix (`envoy-vllm-semantic-router-34deec5c...`). Reinstalling
  the routing stack can recreate that service under a **new** name.
- Result: `/search` stays green, `/chat` breaks — and the fix is a chain:
  discover the new service name in `envoy-gateway-system` → update the
  `GATEWAY_URL` env in the retrieval deployment → confirm the `vllm-api-key`
  secret still exists in the `rag` namespace with the expected key.

Answering that question requires traversing:

```text
retrieval-api ──depends-on──▶ Envoy service (current name!) ──fronts──▶ GPU/CPU tiers
      │                              │
      └──reads env GATEWAY_URL       └──requires Bearer──▶ secret vllm-api-key (key: api-key)
      │
      └──/search path bypasses the gateway entirely
```

A vector index over the docs retrieves *descriptions* of routing, but the
answer needs the **current instance state** (the live service name) joined with
the **dependency structure** (who calls what, with which credential). That is
schema-constrained, relation-heavy, provenance-demanding work.

A plausible schema for the troubleshooting graph:

- **Entities:** `Component` (retrieval-api, envoy-gateway, keda-interceptor…),
  `NodePool` (system, gpu, rag), `Model`, `Secret` + `SecretKey`, `Namespace`,
  `Route`, `ErrorSymptom`, `Runbook`, `ConfigValue` (env vars, helm values).
- **Relations:** `runs_on`, `fronts`, `routes_to`, `reads_secret`,
  `configured_by`, `has_symptom`, `mitigated_by`, `depends_on`.
- **Constraints:** every relation instance links to its source chunk (a doc
  paragraph, a manifest line) — provenance is mandatory.

## 3. What KAG (OpenSPG/KAG) actually is

KAG is not "a graph plus a prompt". Per the paper and the official
implementation, it is four cooperating mechanisms:

1. **Schema-constrained construction.** Extraction is driven by a declared SPG
   schema (entity/relation types, constraints), so the graph stays typed and
   queryable instead of becoming free-form trivia.
2. **Knowledge alignment.** Entities are linked and disambiguated across
   documents ("envoy gateway", "the router", "semantic-router" → one node),
   typically with more model calls.
3. **Knowledge/chunk mutual indexing.** Graph nodes point at their source
   chunks and chunks point back at their entities, so retrieval can move in
   both directions and every assertion keeps provenance.
4. **Logical-form-guided hybrid reasoning.** A question is planned into logical
   forms that drive *both* graph traversal and chunk retrieval, iterated until
   the evidence supports an answer — multiple model calls per question.

The official stack is the OpenSPG graph engine plus the KAG builder (indexing)
and solver (reasoning), with their own dependencies (a graph store, relational
store, and object storage appear in official deployment docs depending on the
release), plus the LLM and embedding endpoints.

### How it differs from lookalikes

- **vs RAG (ours):** RAG retrieves chunks by similarity; KAG plans over a typed
  graph and *also* uses chunks. Single-hop factoid questions favor RAG;
  multi-hop dependency questions favor KAG.
- **vs GraphRAG:** GraphRAG builds an entity graph and summarizes communities
  for global sensemaking ("what are the main themes?"). KAG targets precise
  multi-hop question answering with schema constraints and logical forms. They
  share construction costs but answer different question classes.
- **vs "NetworkX + one prompt":** a hand-rolled graph with a single generation
  call has no schema enforcement, no entity alignment, no mutual indexing, no
  logical-form planning. It can be a fine *graph-guided retrieval* demo — but
  calling it KAG would be dishonest, and this repository will not do that.

## 4. Cost and operational reality

- **Construction cost:** extraction and alignment are LLM calls per chunk;
  building even a small graph is slower and pricier than embedding a corpus.
  Schema design and maintenance are ongoing human work — the schema above is a
  draft, not a one-time task.
- **Query cost and latency:** planning, retrieval, and reasoning mean several
  sequential model calls per question, multiplying latency and token spend
  relative to the single-call patterns (CAG, MAG) or the single-generation RAG
  path.
- **Operational footprint:** the official stack is a separate, heavier
  deployment (graph engine plus its stores) that does not fit this repository's
  one-L4, scale-to-zero, cost-audited profile, and would compete with the demos
  it is meant to explain.
- **Evaluation burden:** multi-hop goldens must include the expected evidence
  *sets* (which nodes/edges/chunks justify the answer), not just answer text —
  a meaningfully harder eval than hit@k or rubric checks.

## 5. Decision: article-first

The troubleshooting corpus here is small, and the four implemented patterns
already cover its question classes. KAG's advantages show on large,
relation-heavy, evolving domains with dedicated platform teams. It is therefore
the highest-effort, highest-risk item in the design space and stays out of the
deployable main line. This article is the deliverable.

## 6. Go/no-go checklist for a future spike

Promote KAG to a code showcase only if **all** of these pass, recorded in a
separate ADR:

1. A pinned official OpenSPG/KAG release works against this repository's
   OpenAI-compatible model and embedding endpoints (versions recorded).
2. The complete dependency stack reproduces in an isolated environment
   (its own venv/compose profile — never in the `rag` namespace by default).
3. Resource use is measured (memory, build time, per-query model calls) and a
   separate deployment profile is justified against the cost model.
4. A small schema-constrained, multi-hop evaluation (including the §2 example)
   demonstrates the unique KAG request path with evidence/provenance — not just
   plausible answers.
5. The result is maintainable without weakening the existing RAG and
   scale-to-zero demos or their quality gates.

Spike rules if approved: time-boxed; faithful blocker records; no custom
substitute built to force a pass; if any condition fails, the outcome is
documentation, not code.

## 7. What to do instead today

- Keep runbooks chunked well for RAG and let the retrieval eval gate quality.
- Use metadata (namespace, component, doc type) in retrieval filters before
  reaching for a graph.
- Put inventory-shaped questions ("which deployments read secret X?") in a
  table and ask them through the TAG showcase pattern.
- If a graph-shaped demo is ever wanted, build an honestly-named
  *graph-guided retrieval* prototype — small, labeled, and never marketed as
  KAG.

## References

- [KAG: Boosting LLMs in Professional Domains via Knowledge Augmented Generation](https://arxiv.org/abs/2409.13731)
- [OpenSPG/KAG — official implementation](https://github.com/OpenSPG/KAG)
- Repository context: `docs/semantic-routing-walkthrough.md`, `k8s/rag/README.md`, `retrieval/main.py`
