# Cost Checkpoint — Semantic Routing Evolution

Baseline (pre-router, from README): ~$51.50/mo idle (zonal cluster, e2-standard-2
system pool, GPU at zero).

## New fixed costs

| Item | Monthly (est.) | Notes |
|---|---|---|
| System pool e2-standard-2 → e2-standard-4 | +~$49 | Router stack + CPU SLM tier live here |
| Envoy gateway LoadBalancer (34.91.66.105) | +~$18 | Public L4 LB created by the Gateway |
| 50 Gi standard PD (vllm-cache-pvc) | ~$2 | Unchanged, persists across GPU scale-downs |

New idle total: **~$120/mo** (was ~$51.50/mo). The trade: casual traffic no longer
wakes the GPU.

## GPU wake costs (variable)

- On-demand `g2-standard-8`: ~$0.75/hr while awake. **Spot is still commented
  out** in `infra/modules/vllm-cluster/main.tf` — enabling it cuts this ~3x.
- First wake with a cold PVC measured 7m31s; warm-PVC wakes match the documented
  3-4 min. Every wake carries a minimum ~10-15 min of node time (provision +
  300s scaledownPeriod + drain).

## Open cost actions

1. Uncomment `spot = true` on the GPU pool (interruptible is acceptable for a
   dev environment; the interceptor simply re-holds on retry).
2. Decide on the public LB: either accept it (needed if the chat UI is exposed),
   switch the Gateway's Envoy service to an internal LB, or remove it and use
   port-forward only.
3. After a representative week, compare GPU wake frequency against pre-router
   baselines using `routing_decision` events in the semantic-router logs
   (`router_replay` keeps them for 30 days). If the CPU tier doesn't measurably
   reduce wakes, revisit the decision config or the tier itself.

## Validation evidence (2026-09-18)

- Casual prompts (recipe, history, finance, travel) → `qwen3-4b-cpu`, GPU stayed
  at 0 replicas.
- Code/agentic prompts (async refactor, race-condition debug, schema design,
  framework migration) → `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ`, interceptor held
  the request during cold start, response streamed, scale-down to 0 after 300s
  idle confirmed.
- One misroute caught during tuning (billing schema → CPU via business domain);
  fixed by extending the `agentic` keyword signal. Escalation bias verified
  after the fix.
