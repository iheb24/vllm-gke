# vLLM Helm Chart

Deploys the two model tiers and the GPU scale-to-zero wiring. Installed with:

```bash
helm upgrade --install vllm-release ./vllm-chart \
  --namespace vllm --create-namespace \
  --set serviceAccount.projectId="YOUR_GCP_PROJECT_ID"
kubectl create secret generic vllm-api-key --from-literal=api-key="<key>" -n vllm
```

## Resource Inventory

| Resource | Name | Purpose |
|---|---|---|
| Namespace | `vllm` | All chart resources |
| ServiceAccount | `vllm-ksa` | Workload Identity binding |
| PersistentVolumeClaim | `vllm-cache-pvc` (50Gi) | HuggingFace cache for the GPU model, survives scale-down |
| Deployment | `vllm-server` | GPU tier: Qwen2.5-Coder-14B-AWQ on 1x L4, scaled 0-1 |
| Service | `vllm-service:8000` | GPU tier ClusterIP |
| Deployment | `slm-server` | CPU tier: Qwen3-4B Q4_K_M on llama.cpp, 1 replica always warm |
| Service | `slm-service:8080` | CPU tier ClusterIP |
| HTTPScaledObject | `vllm-http-scaledobject` | KEDA HTTP add-on: holds requests, scales `vllm-server` 0-1, scale-down after 300s idle |

## Key values (`values.yaml`)

| Path | Default | Notes |
|---|---|---|
| `model.name` | `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` | GPU model; exact name required by clients (case-sensitive) |
| `scaling.*` | min 0, max 1, scaledownPeriod 300, targetPendingRequests 1 | GPU scale-to-zero behavior |
| `slm.enabled` | `true` | CPU tier on/off |
| `slm.hfRepo` / `slm.hfFile` | `Qwen/Qwen3-4B-GGUF` / `Qwen3-4B-Q4_K_M.gguf` | Downloaded at pod start |
| `slm.ctxSize` | `8192` | Context window; clients should not exceed it |
| `slm.resources` | 750m/4Gi req, 3/6Gi limits | Sized to fit the e2-standard-4 system node alongside KEDA, Envoy, and the router |

Both tiers enforce the Bearer token from the `vllm-api-key` secret (vLLM via
`VLLM_API_KEY`, llama.cpp via `LLAMA_API_KEY`).

The semantic router stack (Envoy Gateway, AI Gateway, classifier) is not part of
this chart; see `k8s/install_semantic_routing.sh` and
`docs/semantic-routing-walkthrough.md`.
