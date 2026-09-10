# Datadog Connection Walkthrough

Since the original European cluster was destroyed, the Datadog Agent was also deleted. You need to reinstall the agent on the new US cluster.

## 1. Reinstall the Datadog Agent
Your Datadog trial was created on the EU site (`datadoghq.eu`). You must export this variable before running the script so the agent sends data to the correct Datadog datacenter.

```bash
export DD_SITE="datadoghq.eu"
export DD_API_KEY="<YOUR_DATADOG_API_KEY>"
./k8s/install_datadog.sh
```
*Note: We previously updated `install_datadog.sh` to include `kubeStateMetricsCore` and `orchestratorExplorer` flags, so your Kubernetes overview dashboards will work perfectly out of the box.*

## 2. Restore the vLLM Dashboard
If you lost your custom vLLM AI Observability dashboard, you can import it again.

1. Open Datadog in your browser.
2. Go to **Dashboards** > **New Dashboard**.
3. Name it "vLLM Production Observability" and click **New Dashboard**.
4. Click the gear icon in the top right and select **Import dashboard JSON**.
5. Paste the contents of `vllm_datadog_dashboard.json` (which is located in your workspace artifacts).

## 3. Verify Metrics Collection
The Datadog Agent automatically uses Autodiscovery to scrape the `/metrics` endpoint of the `vllm-server` pod. 

**Critical Requirement:** Datadog will NOT show any `vllm.*` metrics until the vLLM pod has successfully scheduled, downloaded the HuggingFace model, and fully started its HTTP server. If the pod is scaled to 0 (or is `Pending` waiting for a GPU), the dashboard will be blank. 

Once `kubectl get pods -n vllm` shows `Running` (after the ~5-8 minute cold start), the Datadog dashboard will instantly populate.
