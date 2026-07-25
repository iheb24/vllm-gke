# vLLM on GKE Deployment

Welcome to the `vllm-gke` project! 

This repository contains the infrastructure as code (Terraform) and Kubernetes manifests to deploy a vLLM instance on Google Kubernetes Engine (GKE).

## Architecture Highlights
- **Model:** Qwen 2.5 Coder 7B or 14B Instruct.
- **Hardware:** GCP `g2-standard-8` on Spot Instances (1x NVIDIA L4 GPU, 8 vCPUs, 32GB RAM) in `us-central1`.
- **Security:** Strict security utilizing Workload Identity and private network.

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
