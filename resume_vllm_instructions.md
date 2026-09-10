# Resuming vLLM Multi-Zone GPU Deployment

## Context & Architecture Mechanics
- The `vllm-server` deployment uses a PersistentVolumeClaim (`vllm-cache-pvc`) with the `standard-rwo` storage class.
- `standard-rwo` volumes in GKE are strictly zonal. By default, GKE uses `VolumeBindingWaitForFirstConsumer`. This means the PVC remains `Pending` until the pod schedules to a node.
- When the cluster autoscaler triggers a scale-up across multiple zones (`-a`, `-b`, `-c`), the pod binds to the first node that successfully provisions.
- Once the pod schedules, the PVC is permanently bound to that specific zone.
- **The Deadlock Risk**: If the pod schedules, the PVC binds to zone X. If the pod is later deleted (e.g., by KEDA scaling to 0) and the node is reclaimed, subsequent scale-ups *must* occur in zone X. If zone X is out of GCE resources, the autoscaler cannot try other zones because the PVC restricts scheduling to zone X. The only resolution is deleting and recreating the PVC to reset the binding.

## Step 1: Unpause KEDA
Remove the locking annotation to allow KEDA to scale based on HTTP traffic:
```bash
kubectl annotate httpscaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas-
```

## Step 2: Ensure a Clean PVC State
If the PVC is already bound to a zone from a previous failed attempt, it will block multi-zone scaling. Delete and recreate it before starting:
```bash
# Delete the existing PVC
kubectl delete pvc vllm-cache-pvc -n vllm

# Recreate the PVC via Helm
helm upgrade --install vllm-server ./k8s/vllm-chart -n vllm
```
Verify the PVC is in a `Pending` state (waiting for first consumer):
```bash
kubectl get pvc -n vllm
```

## Step 3: Trigger Scale-Up
Port-forward the KEDA HTTP interceptor:
```bash
kubectl port-forward svc/keda-add-ons-http-interceptor-proxy -n keda 8080:8080
```
In a new terminal, send the trigger payload.
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Host: localhost:8000" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    "messages": [{"role": "user", "content": "Write a python function to reverse a string."}]
  }'
```

## Step 4: Monitor Scheduling and Prevent Premature Scale-Down
While the curl command hangs, monitor the pod events:
```bash
kubectl describe pod -n vllm -l app=vllm-server
```
**Expected Timeline:**
1. `TriggeredScaleUp`: Autoscaler requests a node in `-a`, `-b`, or `-c`.
2. `Scheduled`: Pod assigned to the new node. PVC is now bound to this zone.
3. `Pulling image`: Downloading the Docker image (2-4 mins).
4. `Container started`: vLLM begins downloading the 14B model weights to the PVC (2-5 mins).

**Critical Step:** Because the model download exceeds KEDA's 5-minute timeout, if your curl request drops, KEDA will scale the pod to 0 and terminate the download. To prevent this during the initial cold start, freeze the replica count at 1 immediately after the pod appears:
```bash
kubectl annotate httpscaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas="1" --overwrite
```

## Step 5: Verify Metrics and Resume Autoscaling
Once `kubectl get pods -n vllm` shows `1/1 Running`:
1. Check your Datadog dashboard to verify `vllm.*` metrics are flowing.
2. Remove the freeze annotation to return control to KEDA:
```bash
kubectl annotate httpscaledobject vllm-http-scaledobject -n vllm autoscaling.keda.sh/paused-replicas-
```
