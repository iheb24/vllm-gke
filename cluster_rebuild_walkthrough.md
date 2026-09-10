# Cluster Rebuild & Deployment Walkthrough

Because we destroyed the European cluster and built a fresh cluster in the US (`us-central1`), you will need to re-authenticate and reinstall the base tools. Follow these steps in order.

## 1. Re-authenticate to the New Cluster
The new cluster requires you to pull fresh kubeconfig credentials:
```bash
gcloud container clusters get-credentials vllm-cluster --region us-central1-b --project project-c4f86d90-75ff-4766-8cd
```

## 2. Reinstall KEDA
KEDA manages our 0-to-1 scaling based on HTTP traffic.
```bash
./k8s/install_keda.sh
```

## 3. Inject the API Key Secret
The vLLM server requires an API key secret to exist before it can boot.
```bash
kubectl create namespace vllm
kubectl create secret generic vllm-api-key -n vllm --from-literal=api-key="my-super-secret-key"
```

## 4. Deploy vLLM
Install the vLLM helm chart. Because this is a fresh cluster, the PVC (`vllm-cache-pvc`) does not exist yet and will be created clean.
```bash
helm upgrade --install vllm-server ./k8s/vllm-chart -n vllm
```

## 5. PVC Deletion (For Future Zone Changes)
**Important Mechanic:** The `vllm-cache-pvc` is zonal. Once the pod finds a GPU in a specific zone (e.g. `us-central1-c`), the physical disk is created in that zone. If the pod scales to 0, and later tries to scale back up but `-c` is out of GPUs, the autoscaler will be deadlocked because it cannot attach the disk to `-a` or `-f`.

If you ever see `GCE out of resources` and the pod is stuck, you must delete the locked disk to allow the autoscaler to hunt across all zones again:
```bash
kubectl delete pvc vllm-cache-pvc -n vllm
helm upgrade --install vllm-server ./k8s/vllm-chart -n vllm
```
