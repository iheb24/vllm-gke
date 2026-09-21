# Operator Guide

How to connect clients to the stack and how to verify behavior. Architecture
reference: `semantic-routing-walkthrough.md`.

## Prerequisites

- kubectl context pointing at the cluster
- The API key (secret `vllm-api-key` in namespace `vllm`)

## Open the gateway endpoint

All clients reach the stack through the Envoy gateway. Nothing is exposed
publicly; access is via port-forward.

```bash
kubectl port-forward -n envoy-gateway-system \
  svc/$(kubectl get svc -n envoy-gateway-system \
    --selector=gateway.envoyproxy.io/owning-gateway-name=semantic-router \
    -o jsonpath='{.items[0].metadata.name}') 8081:80
```

The endpoint is `http://localhost:8081/v1`. The port-forward must stay running
while clients are in use.

## Client: Cline IDE

Cline is pinned to the GPU model. Configuration (OpenAI Compatible provider):

| Field | Value |
|---|---|
| Base URL | `http://localhost:8081/v1` |
| API Key | the shared key |
| Model ID | `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` |

Notes:

- The Model ID is case-sensitive. `Qwen3-4b-cpu` vs `qwen3-4b-cpu` returns
  400 `specified_model_not_found`.
- The first request after an idle period waits 3-4 minutes while the GPU wakes.
  This is normal; the request is held, not failed.
- Plan and Act modes should both use the 14B model.

## Client: chat UI (three modes)

```bash
python3 chat-ui/serve.py
```

Open `http://localhost:8000`. Set the API key in the settings bar (persisted in
localStorage, or inject via URL: `http://localhost:8000/?key=KEY&model=auto`).

The model dropdown offers the three routing modes:

| UI option | Effect |
|---|---|
| auto | Router classifies each message |
| qwen3-4b-cpu | Forces the CPU tier |
| Qwen 14B | Forces the GPU tier |

Every answer is badged with the tier that served it, the backend model name,
and the response time.

`serve.py` serves the UI and proxies `/v1/*` to `localhost:8081`. Same-origin
serving avoids CORS preflights, which the router's ext_proc filter rejects.

## Client: scripts

```bash
curl -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <key>" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "..."}]}'
```

## Verification

Check which tier answered a request:

```bash
# response headers carry the routing decision
curl -s -i -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer <key>" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
  | grep x-vsr
```

```
x-vsr-selected-model: qwen3-4b-cpu
x-vsr-selected-decision: chat_casual
x-vsr-selected-confidence: 0.6228
```

```bash
# router decision log
kubectl logs -n vllm-semantic-router-system deploy/semantic-router -f | grep routing_decision

# GPU tier state
kubectl get deploy vllm-server -n vllm
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 400 `invalid inference request` | Model name not registered (case-sensitive) | Use exact names: `auto`, `qwen3-4b-cpu`, `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` |
| 404 from interceptor | Request host not in `HTTPScaledObject` hosts list | Add the presented hostname in `k8s/vllm-chart/templates/httpscaledobject.yaml` |
| 502 with `invalid_upstream_json` | Router decoding llama.cpp `timings` field | Requires `response_body_mode: NONE` and `allow_mode_override: false` in the EnvoyPatchPolicy |
| Stream ends with SSE error instead of `[DONE]` | Same as above (streaming variant) | Same as above |
| Gateway 404/503 for all requests | Invalid ext_proc body mode dropped the filter | Use `NONE`, not `SKIP`, for body modes |
| SLM pod Pending | Insufficient CPU on system node | SLM request must stay ≤ ~750m CPU on e2-standard-4 |
| First token takes minutes | GPU cold start (GPU path) or large system prompt on CPU tier (prompt eval ~20-30 tok/s) | Expected; subsequent messages reuse the prompt cache |
| Roo Code hangs with no request sent | Client-side issue; requests never leave the extension | Intercept locally: `mitmdump --mode reverse:http://localhost:8081 -p 8082`, point the client at 8082 |

## Local traffic interception

To see exactly what a client sends, insert a logging proxy between the client
and the port-forward:

```bash
mitmdump --mode reverse:http://localhost:8081 -p 8082
```

Point the client at `http://localhost:8082/v1`. Every request and response is
logged. This distinguishes "client never sent" from "server failed to answer".
