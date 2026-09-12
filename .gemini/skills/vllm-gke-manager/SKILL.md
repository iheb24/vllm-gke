---
name: vllm-gke-manager
description: Provides specialized workflows for deploying and managing the vLLM deployment on GKE via Terraform. Activates when dealing with GKE, vLLM, or Terraform code in this repository.
---

# vLLM GKE Manager Skill

This skill is designed to manage the specific infrastructure of the `vllm-gke` repository.

## 1. Context and Rules

When generating code or answering questions about this project, keep in mind:
- **Model:** Qwen 2.5 Coder 14B AWQ.
- **Node Pool Target:** `g2-standard-8` (1x L4 GPU) on Standard Instances (Spot is optional).
- **System Pool Target:** `e2-standard-2` to host KEDA and GKE system pods.
- **Location & Quotas:** Deployed as a **Zonal Cluster** in `europe-west4-b`.
- **Scale-to-Zero:** Relies on a Custom Go Proxy (`vllm-proxy`) and `kedacore/keda` with a Datadog trigger. The proxy intercepts and holds synchronous HTTP traffic while the GPU provisions.
- **Security:** Strict. Never commit `.tfstate` files, use Workload Identity (never static service accounts).
- **Learning Environment:** The user is actively learning. Always explain the code being added (e.g., *why* a specific Terraform resource is needed, or *how* Workload Identity solves a security problem).
- **No Comments in Code:** Do not add comments directly inside the generated output code. Instead, use markdown text to explain the code snippets.

## 2. Known Problems & Architecture Edge Cases

When assisting the user with observability or scaling, remember these critical constraints that were resolved during development:

1. **Synchronous HTTP constraints (Why Redis/HTTP Add-on failed):**
   Clients like Cline require a synchronously held HTTP connection. Asynchronous queues (Redis) drop the connection, and KEDA HTTP Add-on is often too heavy/complex. The solution is the custom `vllm-proxy` which holds the connection open while exposing an `active_requests` Prometheus gauge for Datadog.

2. **KEDA Datadog Authentication (403 Forbidden on EU Sites):**
   KEDA defaults to `datadoghq.com`. If the user is on the EU site (`datadoghq.eu`), KEDA will return `403 Forbidden` unless `datadogSite: datadoghq.eu` is explicitly mapped through the `TriggerAuthentication` Kubernetes Secret.

3. **Datadog OpenMetrics v2 Metric Renaming:**
   Datadog's automatic Prometheus scraper (`prometheus_pods`) modifies metric prefixes by replacing colons with underscores. A metric emitted by vLLM as `vllm:kv_cache_usage_perc` is ingested as `vllm_kv_cache_usage_perc`. Always use `vllm_` prefixes in Datadog Dashboard queries.

4. **vLLM Cold Start Metrics Quirk:**
   vLLM does *not* emit performance metrics (e.g., `vllm_time_to_first_token_seconds.sum`) until the *first* request has fully generated. During a cold start (scale 0 to 1), Datadog dashboards will legitimately show "no data" for these metrics until the GPU finishes loading the model (3-4 mins) and streams the response.

5. **GCP IAM for Custom Images:**
   To pull the custom proxy image from GCP Artifact Registry, the default GKE compute node service account MUST have the `roles/artifactregistry.reader` role.

## 3. Workflows

When the user asks you to perform one of these actions, follow these specific steps:

### A. Deploying the Infrastructure (`deploy-vllm`)
1. **Verify Security Checks:** Ask the user if `pre-commit` (with `gitleaks`, `trivy`, `tflint`) has passed on their local branch.
2. **Terraform Plan:** Run or prompt the user to run `terraform plan`.
3. **Review with User:** Do not automatically apply. Explain the planned changes to the user so they can learn what is happening.
4. **Apply:** Once approved, instruct the user to run `terraform apply` or execute it if given terminal permission.
5. **Kubernetes Context:** Make sure `gcloud container clusters get-credentials` is explained so the user understands how to access the new cluster.

### B. Destroying the Infrastructure (`destroy-cluster`)
1. **Warning:** Remind the user that destroying the cluster will remove all workloads.
2. **Terraform Destroy:** Use `terraform destroy` to tear down the environment. Explain the teardown process so the user understands how state is cleaned up.

### C. Creating New Components
1. If the user asks to add a new component (e.g., an Ingress, or a new IAM role), present the code first as a snippet.
2. Explain the snippet.
3. Wait for the user's approval before writing it to a file.
4. **Module Documentation:** Whenever a new Terraform module is created or edited, ensure it has a `README.md` that contains:
   - A two-line description of the module's purpose.
   - An inventory list of the resources it creates.
   - A small mermaid architecture diagram illustrating the component.

## 4. Remote State
Always ensure that Terraform blocks use the `gcs` backend. If a `backend "gcs"` block is missing, immediately prompt the user to add it to prevent local state files from being created and potentially leaked.
