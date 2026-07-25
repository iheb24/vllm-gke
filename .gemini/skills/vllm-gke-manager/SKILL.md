---
name: vllm-gke-manager
description: Provides specialized workflows for deploying and managing the vLLM deployment on GKE via Terraform. Activates when dealing with GKE, vLLM, or Terraform code in this repository.
---

# vLLM GKE Manager Skill

This skill is designed to manage the specific infrastructure of the `vllm-gke` repository.

## 1. Context and Rules

When generating code or answering questions about this project, keep in mind:
- **Model:** Qwen 2.5 Coder 7B or 14B Instruct.
- **Node Pool Target:** `g2-standard-8` (1x L4 GPU) on Spot.
- **Location & Quotas:** Deployed in `us-central1`. The node pool must be Zonal with `max_node_count=1` to prevent the GKE autoscaler from failing pre-flight quota checks due to global GPU quota constraints.
- **Security:** Strict. Never commit `.tfstate` files, use Workload Identity (never static service accounts).
- **Learning Environment:** The user is actively learning. Always explain the code being added (e.g., *why* a specific Terraform resource is needed, or *how* Workload Identity solves a security problem).
- **No Comments in Code:** Do not add comments directly inside the generated output code. Instead, use markdown text to explain the code snippets.

## 2. Workflows

When the user asks you to perform one of these actions, follow these specific steps:

### A. Deploying the Infrastructure (`deploy-vllm`)
1. **Verify Security Checks:** Ask the user if `pre-commit` (with `gitleaks`, `tfsec`) has passed on their local branch.
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

## 3. Remote State
Always ensure that Terraform blocks use the `gcs` backend. If a `backend "gcs"` block is missing, immediately prompt the user to add it to prevent local state files from being created and potentially leaked.
