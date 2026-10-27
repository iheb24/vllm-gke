<!-- source: docs/semantic-routing-walkthrough.md — Integration details (verbatim extract) -->

## Integration details

### Interceptor host matching

The KEDA interceptor matches requests against the `HTTPScaledObject` `hosts`
list and returns 404 for unmatched hosts. Envoy rewrites the upstream
`:authority` to the backend FQDN, so the list must contain:

- `keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local` (router-forwarded)
- `localhost`, `localhost:8000`, `localhost:8080` (port-forwarded clients)
- `vllm-service.vllm.svc.cluster.local` (in-cluster direct)

### ExtProc processing mode

The EnvoyPatchPolicy inserts the semantic-router filter as the first HTTP
filter with:

- `request_body_mode: BUFFERED` (classification needs the full prompt)
- `response_body_mode: NONE` and `allow_mode_override: false`

Response bodies must not reach the router. llama.cpp appends a non-standard
`timings` field to responses and final stream chunks, which the router's strict
decoder rejects (`invalid_upstream_json`, surfaced as 502 for non-streaming or
a terminal SSE error event instead of `[DONE]` for streaming). With overrides
allowed, the router opts back into response bodies per request; both settings
are required. Side effect: response-side router features (semantic cache,
stream reconstruction) are disabled. Request-side classification is unaffected.

Note: `SKIP` is not a valid value for body modes (headers only). An invalid
value silently drops the ext_proc filter from the listener; all requests then
fall through to the gateway catch-all direct response.

### Authentication

Both backends enforce the same Bearer token from the `vllm-api-key` secret:
vLLM via `VLLM_API_KEY`, llama.cpp via `LLAMA_API_KEY`. The gateway passes the
client `Authorization` header through unchanged. Unauthenticated requests get
401 from the backends.

### Network exposure

The Envoy data plane Service is `type: ClusterIP` (set on the `EnvoyProxy`
resource). Envoy Gateway defaults to `LoadBalancer`, which on GKE provisions a
public L4 load balancer; this is overridden. All access is via
`kubectl port-forward`.

### CPU tier scheduling

The system node (e2-standard-4) reserves ~3 CPU for KEDA, the Envoy stack, and
the router. The SLM Deployment requests 750m CPU / 4Gi and limits 3 CPU / 6Gi.
Higher requests leave the pod unschedulable (`Insufficient cpu`), and the
autoscaler then attempts GPU-pool scale-up for a CPU pod. Do not raise the SLM
CPU request without resizing the system pool.
