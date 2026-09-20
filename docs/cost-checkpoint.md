# Cost Model

## Fixed monthly costs

| Item | Monthly (est.) | Notes |
|---|---|---|
| Zonal control plane | $0 | Free tier (zonal cluster) |
| System pool e2-standard-4 | ~$98 | Runs KEDA, interceptor, Envoy stack, router, CPU tier |
| 50 Gi standard PD (vllm-cache-pvc) | ~$2 | Model cache, persists across GPU scale-downs |
| Envoy gateway LB | $0 | ClusterIP; no load balancer provisioned |
| **Total idle** | **~$100** | GPU at zero |

Before the routing tier the idle cost was ~$51.50/mo (e2-standard-2). The
increase of ~$49/mo is the system pool resize required to host the router stack
and the CPU model.

## Variable costs (GPU awake)

| Item | Rate | Notes |
|---|---|---|
| g2-standard-8 on-demand | ~$0.75/h | Billed while the GPU node exists |
| g2-standard-8 spot | ~$0.22/h | Not enabled; `spot = true` is commented out in `infra/modules/vllm-cluster/main.tf` |

Each GPU wake carries a minimum node lifetime: provision time (~2.5 min) +
workload + 300 s `scaledownPeriod` + drain. Budget ~10-15 min minimum per wake
even for one prompt.

## Measured timings

| Event | Duration |
|---|---|
| GPU wake, cold PVC (first model download) | 7m31s |
| GPU wake, warm PVC | 2m56s |
| CPU tier answer, short prompt | 1-3 s |
| CPU tier prompt ingestion | ~20-30 tok/s (shared 4 vCPU node) |

## Cost controls

1. Enable spot on the GPU pool: uncomment `spot = true` in
   `infra/modules/vllm-cluster/main.tf`. Spot preemption is acceptable here;
   the interceptor re-holds interrupted requests.
2. Keep the gateway on ClusterIP. A public LB adds ~$18/mo and exposes the
   endpoints.
3. Routing effectiveness is measurable: `routing_decision` events in the
   router logs (retained 30 days by `router_replay`) show how many requests
   the CPU tier absorbed. Compare GPU wake frequency against pre-router
   baselines after a representative period. If the CPU tier does not
   measurably reduce wakes, revisit the decision rules in
   `k8s/semantic-router/values.yaml`.
