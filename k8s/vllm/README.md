# vLLM Kubernetes Manifests

Deploys the vLLM OpenAI-compatible server configured for Qwen 2.5 Coder on GKE. It utilizes Workload Identity and a PVC to cache model weights across Spot instances.

## Resource Inventory
- `Namespace`: `vllm`
- `ServiceAccount`: `vllm-ksa` (Linked to GCP Workload Identity)
- `PersistentVolumeClaim`: `vllm-cache-pvc` (50Gi for HuggingFace caching)
- `Deployment`: `vllm-server` (Runs vLLM, requests 1 L4 GPU)
- `Service`: `vllm-service` (ClusterIP exposing port 8000)

## Architecture

```mermaid
graph TD
    subgraph "Kubernetes: vllm Namespace"
        SVC[Service: vllm-service<br/>Port 8000]
        
        subgraph "Deployment: vllm-server"
            Pod[vLLM Pod<br/>Qwen 2.5 Coder]
            KSA[ServiceAccount: vllm-ksa]
            Secret[Secret: vllm-api-key]
            
            Pod --- KSA
            Pod -. "Reads API Key" .-> Secret
        end
        
        PVC[(PVC: vllm-cache-pvc<br/>/root/.cache/huggingface)]
        
        SVC --> Pod
        Pod --> PVC
    end
```
