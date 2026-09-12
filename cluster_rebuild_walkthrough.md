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

## 5. Freeze Scale Down (Cold Start Lock)
Because the initial download of the 14B model takes longer than KEDA's 5-minute timeout window, you must lock the replica count to `1` so KEDA doesn't scale it back to `0` while downloading!
```bash
kubectl annotate scaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas="1" --overwrite
```
*(Remember to run the unfreeze command in Step 9 once the model finishes downloading!)*

## 6. Trigger vLLM with a Request
To securely test this from your local machine, you need to port-forward the KEDA HTTP Interceptor.

Open a second terminal window and run:
```bash
kubectl port-forward svc/keda-add-ons-http-interceptor-proxy -n keda 8080:8080
```
Now, in your first terminal, send this curl command.
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Host: localhost:8000" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-super-secret-key" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    "messages": [
      {
        "role": "user",
        "content": "Write a python function to reverse a string."
      }
    ]
  }'
```

## 7. Monitor the Cluster
Use these commands in another terminal to watch the GPU provisioning and booting sequence:

**Watch all events chronologically (Highly Recommended):**
```bash
kubectl get events -n vllm --sort-by='.metadata.creationTimestamp' -w
```

**Check Pod Status:**
```bash
kubectl get pods -n vllm -w
```

**Stream the vLLM Server Logs (Once the container is creating):**
```bash
kubectl logs -n vllm -l app=vllm-server -f
```

## 8. PVC Deletion (For Future Zone Changes)
**Important Mechanic:** The `vllm-cache-pvc` is zonal. Once the pod finds a GPU in a specific zone (e.g. `us-central1-c`), the physical disk is created in that zone. If the pod scales to 0, and later tries to scale back up but `-c` is out of GPUs, the autoscaler will be deadlocked because it cannot attach the disk to `-a` or `-f`.

If you ever see `GCE out of resources` and the pod is stuck, you must delete the locked disk to allow the autoscaler to hunt across all zones again:
```bash
kubectl delete pvc vllm-cache-pvc -n vllm
helm upgrade --install vllm-server ./k8s/vllm-chart -n vllm
```

## 9. Unfreeze KEDA (Resume Autoscaling)
Once your Datadog metrics are flowing and your `curl` requests are succeeding instantly, you must unfreeze KEDA so it can automatically scale the cluster back to `0` when idle to save money!

Run this command to remove the lock:
```bash
kubectl annotate scaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas-
```

## 10. Hibernate Mode (Force 0 Replicas)
If you are done for the day and want to ensure the pod stays scaled to `0` and **ignores all incoming HTTP traffic** (preventing any accidental GPU costs), you can freeze KEDA at `0` replicas:

```bash
kubectl annotate scaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas="0" --overwrite
```
*(To wake it back up and allow scaling based on traffic, run the unfreeze command in Step 9).*
