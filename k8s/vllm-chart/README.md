# vLLM Helm Chart

This Helm chart deploys the vLLM Inference Server, the custom Go Proxy (for scale-to-zero), and the KEDA Datadog ScaledObject.

## Datadog Prerequisites
Before deploying this chart, you must install the Datadog Agent using `install_datadog.sh`.
The vLLM Proxy emits the metric `vllm_proxy_active_requests` which Datadog ingests.

## Configuration

In your `values.yaml`, provide your Datadog credentials so KEDA can authenticate and query the active requests metric:

```yaml
datadog:
  apiKey: "your-api-key"
  appKey: "your-app-key"
  site: "datadoghq.eu" # Defaults to datadoghq.com if not specified
```

## Scaling Logic
The `ScaledObject` natively queries `max:vllm_proxy.vllm_proxy_active_requests{*}`. 
If it is > 0, vLLM scales to 1.
If it is 0 for `scaledownPeriod` (default 300s), vLLM scales to 0.

*Note: For users in the EU region, KEDA strictly requires `datadogSite` to be passed as an authentication parameter via a Kubernetes Secret (see `triggerauthentication.yaml`), otherwise it will return a 403 Forbidden.*
