# Retrieval eval — 2026-09-30

questions: 42 in-scope, 4 out-of-scope

| metric | value | gate |
| --- | --- | --- |
| hit@1 | 0.90 | — |
| hit@5 | 1.00 | >= 0.9 |
| MRR | 0.94 | >= 0.75 |

GATE: PASS

## Misses

- rank=2 expected `docs/implementation-guide.md`: If the KEDA interceptor answers every request with a 404, which file should you edit and what needs to be added to it?
- rank=2 expected `docs/cost-checkpoint.md`: Adding the semantic routing tier raised the baseline idle spend; from what previous monthly figure to what new total?
- rank=3 expected `docs/cost-checkpoint.md`: Why does the cost model insist on keeping the Envoy gateway as ClusterIP instead of giving it a public load balancer?
- rank=3 expected `docs/rag-architecture.md`: What chunking strategy is planned for ingestion, including the splitter, the target passage size, and the overlap?

## Out-of-scope top scores (should be low)

- 0.153: How do I export detailed GCP billing data to BigQuery and query it through the Cloud Billing API?
- 0.058: What changes would be needed to run this stack on AWS EKS with Karpenter instead of GKE?
- 0.084: How can I fine-tune the Qwen model with LoRA adapters on this cluster?
- 0.550: What is the recommended procedure for upgrading the GKE cluster to a newer Kubernetes version?
