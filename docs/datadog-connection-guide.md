# Datadog Connection & Configuration Guide

This document outlines how the GKE cluster connects to Datadog, how variables are mapped, and known edge cases encountered during setup.

## 1. Cluster-Side Connection (Datadog Agent)
The cluster connects to Datadog using the **Datadog Helm Chart**. 
- The installation is scripted in `k8s/install_datadog.sh`.
- The cluster authenticates using the `DD_API_KEY` (32 characters).
- The Datadog agent runs as a DaemonSet to collect node/pod logs, and a cluster-agent collects Kubernetes state metrics (KSM).

## 2. KEDA Autoscaler Connection (TriggerAuthentication)
While the Datadog Agent pushes metrics *to* Datadog, the KEDA operator needs to pull metrics *from* Datadog to make scaling decisions.
- KEDA authenticates using **both** a `DD_API_KEY` and a `DD_APP_KEY` (40 characters).
- These are securely mapped via Kubernetes Secrets and a `TriggerAuthentication` CRD:
```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: keda-datadog-trigger-auth
spec:
  secretTargetRef:
    - parameter: apiKey
      name: datadog-keda-auth
      key: apiKey
    - parameter: appKey
      name: datadog-keda-auth
      key: appKey
    - parameter: datadogSite
      name: datadog-keda-auth
      key: datadogSite
```

## 3. Custom Variables & Metric Ingestion

### Metric Emitting (Proxy)
Our custom reverse proxy (`vllm-proxy`) exposes a Prometheus gauge metric: `vllm_proxy_active_requests`.

### Autodiscovery (Annotations)
We tell the Datadog Agent to scrape the proxy by annotating the pod in `proxy-deployment.yaml`:
```yaml
ad.datadoghq.com/proxy.checks: |
  {
    "openmetrics": {
      "instances": [{
        "openmetrics_endpoint": "http://%%host%%:8080/metrics",
        "namespace": "vllm_proxy",
        "metrics": [".*"]
      }]
    }
  }
```

## ⚠️ Known Problems & Edge Cases Resolved

### Problem 1: Datadog EU Site `403 Forbidden` in KEDA
**Issue:** KEDA defaults to `datadoghq.com` (US1). If your Datadog account is in Europe, KEDA will return `403 Forbidden` because the App/API keys are invalid on the US site.
**Solution:** The `datadogSite` parameter must be explicitly passed into the KEDA scaler. In KEDA v2.20+, this is treated as an `authParams` and MUST be injected via the `TriggerAuthentication` secret mapping, *not* just hardcoded in the ScaledObject metadata.

### Problem 2: OpenMetrics Auto-Scraper Prefix Alteration
**Issue:** When switching to Datadog's automatic Prometheus scraping (`prometheus_pods`), Datadog's parser alters metric names. It replaces colons (`:`) with underscores (`_`). 
For example, vLLM's native metric `vllm:kv_cache_usage_perc` is ingested as `vllm_kv_cache_usage_perc`.
**Solution:** Ensure all Datadog Dashboards and KEDA Queries use the `vllm_` prefix instead of the old `vllm.` dot syntax.
