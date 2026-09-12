# vLLM on GKE Deployment

Welcome to the `vllm-gke` project! 

This repository contains the infrastructure as code (Terraform) and Kubernetes manifests to deploy a vLLM instance on Google Kubernetes Engine (GKE) with full scale-to-zero capabilities.

## Architecture Highlights
- **Model:** Qwen 2.5 Coder 14B AWQ.
- **Hardware:** GCP `g2-standard-8` (1x NVIDIA L4 GPU, 8 vCPUs, 32GB RAM) in `europe-west4-b`.
- **System Pool:** GCP `e2-standard-2` (dedicated to running KEDA and GKE system pods).
- **Security:** Strict security utilizing Workload Identity and private network.
- **Scale-to-Zero:** A Custom Go Proxy intercepts requests, emitting metrics to Datadog which triggers KEDA to scale the GPU node pool from 0 to 1, providing ~91% cost savings for idle periods.

### Datadog-Driven Scale-to-Zero Flow
```mermaid
sequenceDiagram
    participant Developer
    participant Proxy as Custom Go Proxy
    participant Datadog as Datadog Agent/API
    participant KEDA as KEDA Autoscaler
    participant GKE as GKE Cluster Autoscaler
    participant vLLM as vLLM Pod

    Developer->>Proxy: HTTP Request (Prompt)
    Proxy->>Proxy: active_requests++
    Datadog-->>Proxy: Scrapes metric
    KEDA-->>Datadog: Queries Datadog API
    KEDA->>GKE: Scale Deployment to 1
    GKE->>GKE: Provision L4 GPU Node (~2.5 mins)
    GKE->>vLLM: Attach 50GB PVC & Start Pod (~1 min)
    vLLM-->>Proxy: Health Check Passes
    Proxy->>vLLM: Forward HTTP Request
    vLLM-->>Developer: Stream LLM Response
    Proxy->>Proxy: active_requests-- (cooldown begins)
```

## Cost Optimization (Zonal vs Regional)
To make this viable for a personal developer environment, this project utilizes a **Zonal Cluster** instead of a Regional one.
- **Regional Cluster:** Highly available across 3 zones. Costs ~$73/mo just for the management fee.
- **Zonal Cluster:** Lives in a single zone (e.g., `europe-west4-b`). Management fee is **$0/mo** (Free Tier).
Total idle cost drops from ~$800/mo (always-on enterprise) to **~$51.50/mo** (Zonal + KEDA).

## Quick Start Deployment Guide

Follow these steps to deploy your own scale-to-zero vLLM cluster:

**1. Get your public IP address (for GKE authorized networks):**
```bash
curl ifconfig.me
```

**2. Set up your Terraform variables:**
Create a file at `infra/environments/dev/terraform.tfvars`:
```hcl
project_id   = "YOUR_GCP_PROJECT_ID"
my_public_ip = "YOUR_PUBLIC_IP"
```

**3. Deploy the Infrastructure:**
```bash
cd infra/environments/dev
terraform init
terraform apply
```

**4. Connect to your new cluster:**
```bash
gcloud container clusters get-credentials vllm-cluster --zone europe-west4-b --project YOUR_GCP_PROJECT_ID
```

**5. Install Datadog & KEDA:**
```bash
export DD_API_KEY="your-api-key"
export DD_APP_KEY="your-app-key"
export DD_SITE="datadoghq.eu"
cd ../../../k8s
./install_datadog.sh
./install_keda.sh
```

**6. Deploy vLLM with Datadog Keys:**
```bash
helm upgrade --install vllm ./vllm-chart --namespace vllm --create-namespace \
  --set datadog.apiKey=$DD_API_KEY \
  --set datadog.appKey=$DD_APP_KEY \
  --set datadog.site=$DD_SITE
```

**7. Inject the API Key (Security Secret):**
```bash
kubectl create secret generic vllm-api-key --from-literal=api-key="your-secure-password" -n vllm
```

**8. Fire a request to trigger a Cold Start!**
First, port-forward the Go Proxy (which holds the requests):
```bash
kubectl port-forward svc/vllm-proxy-service -n vllm 8080:8080
```
Then, in a new terminal window, fire your request. *(Note: The request will hang for ~4 minutes while the GPU boots up!)*
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secure-password" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    "messages": [{"role": "user", "content": "Write a hello world script in Python."}]
  }'
```

For advanced Datadog configurations and scale-to-zero tuning, see the `docs/` folder.

## Security and Pre-commit Hooks

This project enforces strict security checks to prevent secrets from being leaked to the public repository. We use `pre-commit` to manage these hooks.

### Installation

1. Install the required security scanning binaries (macOS):
   ```bash
   brew install terraform-linters/tap/tflint
   brew install aquasecurity/trivy/trivy
   ```
2. Install [pre-commit](https://pre-commit.com/) (using `pip` or `uv`):
   ```bash
   uv pip install pre-commit
   ```
3. Install the hooks in this repository:
   ```bash
   pre-commit install
   pre-commit install --hook-type commit-msg
   ```

The pre-commit hooks will automatically check for:
- Accidentally committed secrets (`gitleaks`).
- Terraform misconfigurations and security issues (`trivy`, `tflint`).
- Correctly formatted commit messages (`conventional-commits`).

## Developer Guidelines
Before contributing, please review the `agent.md` file for project-specific instructions and security guidelines.
