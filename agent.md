# VLLM on GKE - Agent Instructions

Welcome to the vLLM on GKE project. When working on this repository as an AI agent, you must strictly follow these guidelines. The human developer is treating this project as a learning experience, so **do not generate entire blocks of infrastructure code unless explicitly instructed**. Prefer explaining concepts, asking questions, and taking a step-by-step approach.

## 1. Project Context
- **Objective:** Host a vLLM instance on Google Kubernetes Engine (GKE) to serve the **Qwen 2.5 Coder 14B AWQ** model.
- **Model Specs:** Loading in AWQ 4-bit quantization to fit within a single 24GB L4 GPU, reserving enough VRAM for a massive 32K context window.
- **Hardware Specs:** Target GKE node pool is `g2-standard-8` (1x NVIDIA L4 GPU, 8 vCPUs, 32GB RAM).
- **Node Pool & Quotas:** The cluster is deployed in `europe-west4`. To avoid triggering a 'GCE quota exceeded' error, the GPU node pool must be strictly Zonal (e.g., `europe-west4-a`) with `max_node_count = 1`. Spot instances are optional (defaults to standard).

## 2. Security & Secrets Management
- **Public Repository Rules:** This is a public repository. **NEVER** hardcode sensitive data, API keys, database passwords, or static Service Account credentials in any file.
- **Pre-commit Hooks:** We enforce a strict pre-commit baseline. This must include:
  - `gitleaks` (Secret scanning)
  - `trivy` (Terraform security and misconfiguration scanning)
  - `tflint` (Terraform best practices)
  - `commitlint` (for Conventional Commits)
- **Workload Identity:** All GKE pods requiring Google Cloud access must authenticate using Google Cloud Workload Identity. Do not generate or use static service account JSON keys for pods.

## 3. Terraform Best Practices
- **State Management:** Terraform state will use a remote GCS (`gcs`) backend. 
- **Git Ignore:** Ensure that `.gitignore` aggressively blocks all state files (`*.tfstate`, `*.tfstate.backup`, `.terraform/`) spanning all directories. No state file should ever be committed.
- **Modularity:** Keep Terraform configurations DRY by using modules or clear file separations.

## 4. Git & Commit Workflow
- Commit messages must strictly follow the **Conventional Commits** specification (e.g., `feat: ...`, `fix: ...`, `chore: ...`).
- Provide clear context in PRs/Commits about what is being changed.

## 5. Learning Objective (Critical)
The user is learning how this stack comes together. 
- When building the Terraform files or Kubernetes manifests, do it incrementally.
- Provide explanations of *why* certain resources (like `google_container_cluster`, Workload Identity bindings, or vLLM container args) are configured the way they are.
- **No Comments in Code:** Explain the code in markdown text, but do **not** add comments directly inside the generated output code.
