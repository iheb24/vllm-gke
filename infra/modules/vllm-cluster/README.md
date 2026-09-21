# vLLM Cluster Module

This module provisions a VPC-native private GKE cluster and a dedicated L4 GPU node pool for running vLLM. It sets up Workload Identity so pods can securely authenticate with Google Cloud services.

## Resource Inventory
- `google_container_cluster.primary`: The private GKE cluster with Workload Identity enabled.
- `google_container_node_pool.system_pool`: A single `e2-standard-4` node (machine type configurable via `system_machine_type`) running KEDA, the HTTP interceptor, the Envoy Gateway stack, the semantic router, and the CPU SLM tier.
- `google_container_node_pool.gpu_pool`: The autoscaling `g2-standard-8` node pool with NVIDIA L4 GPUs (configured as a Zonal pool with max size 1 to respect quota limits).
- `google_service_account.vllm_sa`: The GCP service account for the vLLM workload.
- `google_service_account_iam_binding.workload_identity_binding`: The IAM binding linking the Kubernetes service account to the GCP service account.

## Architecture

```mermaid
graph TD
    subgraph "GCP Project"
        subgraph "GKE Cluster (Private)"
            CP[Control Plane / API Server]

            subgraph "Node Pool: system-pool (e2-standard-4)"
                KEDA[KEDA + HTTP Interceptor]
                GW[Envoy Gateway +<br/>Semantic Router]
                SLM[slm-server<br/>Qwen3-4B CPU tier]
            end

            subgraph "Node Pool: gpu-pool (g2-standard-8, 0-1 nodes)"
                L4[NVIDIA L4 GPU]
                Pod[vLLM Pod<br/>Qwen 14B GPU tier]
                KSA[K8s Service Account: vllm-ksa]

                Pod --- L4
                Pod --- KSA
            end

            GW -->|simple / casual| SLM
            GW -->|complex / agentic| KEDA
            KEDA -->|holds request, 0-1 scale| Pod
            CP --- Pod
        end

        GSA[GCP Service Account: vllm-sa]
        KSA -. "Workload Identity" .-> GSA
    end

    Local[Local VSCode]
    Local -. "kubectl port-forward<br/>(Master Authorized Network)" .> CP
```
