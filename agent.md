# VLLM on GKE - Agent Instructions

Welcome to the vLLM on GKE project. When working on this repository as an AI agent, you must strictly follow these guidelines. The human developer is treating this project as a learning experience, so **do not generate entire blocks of infrastructure code unless explicitly instructed**. Prefer explaining concepts, asking questions, and taking a step-by-step approach.

## 1. Project Context
- **Objective:** Host a vLLM instance on Google Kubernetes Engine (GKE) to serve the **Qwen 2.5 Coder 14B AWQ** model, fronted by a semantic routing layer that tiers traffic.
- **Model Specs:** Loading in AWQ 4-bit quantization to fit within a single 24GB L4 GPU, reserving enough VRAM for a massive 32K context window.
- **Hardware Specs:** 
  - GPU Pool: Target GKE node pool is `g2-standard-8` (1x NVIDIA L4 GPU, 8 vCPUs, 32GB RAM).
  - System Pool: Must use `e2-standard-4` to fit KEDA, the HTTP interceptor, the Envoy Gateway / AI Gateway stack, the vLLM Semantic Router ExtProc, and the CPU SLM tier.
- **Tiered Routing:** vLLM Semantic Router (ModernBERT classifier, ExtProc behind Envoy AI Gateway) is the single entry point for all clients. Three routing modes via the `model` field: `auto` (classified), `qwen3-4b-cpu` (forced CPU tier), `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` (forced GPU tier). Client policy: Cline is pinned to the 14B for both Plan and Act; the chat UI (`chat-ui/`) exposes all three modes. Routing is biased toward escalation: unmatched or ambiguous requests default to the GPU tier. Both tiers enforce the same Bearer API key (`vllm-api-key` secret). The gateway data plane is ClusterIP-only (no public LB); clients use `kubectl port-forward`. See `docs/semantic-routing-walkthrough.md`.
- **Node Pool & Quotas:** The cluster is deployed as a **Zonal Cluster** (e.g., `us-central1-a`) to optimize costs and avoid the Regional $73/mo control plane fee.
- **Scale-to-Zero Architecture:** Uses `kedacore/keda` and `kedacore/keda-add-ons-http`. The vLLM Helm chart includes an `HTTPScaledObject` to intercept and hold requests while the GPU node provisions. The CPU tier does NOT scale to zero.
- **RAG Stack:** Retrieval-augmented generation lives in the `rag` namespace on a dedicated `rag-pool` (e2-standard-4, label `workload=rag`): Qdrant (Helm, PVC, API key in secret `qdrant-key`, versioned collection `docs-v2` (dense 1024-dim cosine + sparse BM25, RRF fusion)), TEI embedding server serving the ONNX export of Qwen3-Embedding-0.6B (see `bench/results.md` for the benchmark and its tuning constraints), an ingestion CronJob (GCS bucket `vllm-gke-rag-docs-*` via Workload Identity, idempotent `uuid5(gcs_uri#chunk)` point IDs), and a FastAPI retrieval API (`/search`, `/chat` through the gateway, pinned to the CPU tier). Deploy docs: `k8s/rag/README.md`. Retrieval quality is gated by `eval/run_eval.py` (hit@5 ≥ 0.90, MRR ≥ 0.75 on `eval/golden_questions.yaml`); every retrieval-affecting change must ship a before/after eval report.

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
