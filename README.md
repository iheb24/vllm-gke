# vLLM on GKE Deployment


Welcome to the `vllm-gke` project! 

This repository contains the infrastructure as code (Terraform) and Kubernetes manifests to deploy a vLLM instance on Google Kubernetes Engine (GKE) with full scale-to-zero capabilities.

## Architecture Highlights
- **Model:** Qwen 2.5 Coder 14B AWQ (GPU tier) + Qwen3-4B Q4_K_M on llama.cpp (CPU tier).
- **Hardware:** GCP `g2-standard-8` (1x NVIDIA L4 GPU, 8 vCPUs, 32GB RAM) in `europe-west4-b`.
- **System Pool:** GCP `e2-standard-4` (KEDA, HTTP interceptor, semantic router stack, CPU SLM tier).
- **Routing:** vLLM Semantic Router (ModernBERT classifier) behind Envoy Gateway / AI Gateway sends casual traffic to the CPU tier and complex/agentic traffic to the GPU tier, biased toward escalation.
- **Security:** Strict security utilizing Workload Identity and private network.
- **Scale-to-Zero:** KEDA HTTP Add-on intercepts requests and scales the GPU node pool from 0 to 1, providing ~91% cost savings for idle periods.

### Tiered Routing Topology
```mermaid
flowchart LR
    subgraph Clients
        ChatUI[Browser Chat UI<br/>model: auto]
        Cline[Cline IDE<br/>pinned model]
    end

    subgraph SystemPool["System Pool (e2-standard-4, always on)"]
        Envoy[Envoy Gateway +<br/>Semantic Router ExtProc]
        SLM[slm-server<br/>Qwen3-4B, llama.cpp]
        Interceptor[KEDA HTTP Interceptor]
    end

    subgraph GPUPool["GPU Pool (spot L4, scales to zero)"]
        VLLM[vLLM 14B AWQ]
    end

    Cline -->|pinned model, direct| Interceptor
    ChatUI --> Envoy
    Envoy -->|casual| SLM
    Envoy -->|complex / agentic| Interceptor
    Interceptor -->|holds request, 0-1 scale| VLLM
```

See [docs/semantic-routing-walkthrough.md](docs/semantic-routing-walkthrough.md) for the full design rationale and request lifecycle.

### Scale-to-Zero Flow
```mermaid
sequenceDiagram
    participant Developer
    participant KEDA_Proxy as KEDA HTTP Interceptor
    participant HPA as KEDA Scaler (HPA)
    participant GKE as GKE Autoscaler
    participant vLLM as vLLM Pod

    Developer->>KEDA_Proxy: HTTP Request (Prompt)
    KEDA_Proxy->>KEDA_Proxy: Hold Request in Queue
    KEDA_Proxy->>HPA: Metric: Pending Requests > 0
    HPA->>GKE: Scale Deployment to 1
    GKE->>GKE: Provision L4 GPU Node (~2.5 mins)
    GKE->>vLLM: Attach 50GB PVC & Start Pod (~1 min)
    vLLM-->>KEDA_Proxy: Health Check Passes
    KEDA_Proxy->>vLLM: Forward HTTP Request
    vLLM-->>Developer: Stream LLM Response
```

## Cost Optimization (Zonal vs Regional)
To make this viable for a personal developer environment, this project utilizes a **Zonal Cluster** instead of a Regional one.
- **Regional Cluster:** Highly available across 3 zones. Costs ~$73/mo just for the management fee.
- **Zonal Cluster:** Lives in a single zone (e.g., `europe-west4-b`). Management fee is **$0/mo** (Free Tier).
Total idle cost drops from ~$800/mo (always-on enterprise) to **~$100/mo** (Zonal + KEDA + always-on system pool sized for the CPU tier and router).

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

**5. Install KEDA & vLLM:**
```bash
cd ../../../k8s
./install_keda.sh
helm upgrade --install vllm-release ./vllm-chart --namespace vllm --create-namespace
```

**6. Inject the API Key (Security Secret):**
```bash
kubectl create secret generic vllm-api-key --from-literal=api-key="your-secure-password" -n vllm
```

**7. Install the semantic routing stack (optional but recommended):**
```bash
./install_semantic_routing.sh
```

**8. Fire a request to trigger a Cold Start!**

*Agentic client (Cline IDE, pinned model — bypasses the router):*

First, port-forward the KEDA interceptor proxy (which holds the requests):
```bash
kubectl port-forward svc/vllm-http-interceptor-proxy -n keda 8080:8080
```
Then, in a new terminal window, fire your request. *(Note: The request will hang for ~4 minutes while the GPU boots up!)*
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secure-password" \
  -H "Host: localhost:8000" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    "messages": [{"role": "user", "content": "Write a hello world script in Python."}]
  }'
```

*Chat client (unpinned, routed by the semantic router):*

Port-forward the Envoy gateway service:
```bash
export ENVOY_SERVICE=$(kubectl get svc -n vllm \
  --selector=gateway.envoyproxy.io/owning-gateway-name=semantic-router \
  -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n vllm svc/$ENVOY_SERVICE 8081:80
```
Then send a request with `model: "auto"` — the router picks the tier:
```bash
curl -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secure-password" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Tell me a fun fact about octopuses."}]
  }'
```
Casual prompts are answered by the CPU tier without waking the GPU.

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
