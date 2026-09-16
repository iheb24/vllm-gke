#!/bin/bash
set -e

export AIGW_VERSION=v1.0.0
export ENVOY_GATEWAY_VERSION=v1.8.1

echo "🚀 Setting up Envoy Gateway, Envoy AI Gateway, and vLLM Semantic Router"

echo "📡 Installing Envoy Gateway (brings compatible Gateway API CRDs)..."
helm upgrade -i eg oci://docker.io/envoyproxy/gateway-helm \
    --version "${ENVOY_GATEWAY_VERSION}" \
    --namespace envoy-gateway-system \
    --create-namespace \
    -f "https://raw.githubusercontent.com/envoyproxy/ai-gateway/${AIGW_VERSION}/manifests/envoy-gateway-values.yaml"
kubectl wait --timeout=2m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available

echo "🧠 Installing Envoy AI Gateway CRDs and controller..."
helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm \
    --version "${AIGW_VERSION}" \
    --namespace envoy-ai-gateway-system \
    --create-namespace
helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
    --version "${AIGW_VERSION}" \
    --namespace envoy-ai-gateway-system
kubectl wait --timeout=300s -n envoy-ai-gateway-system deployment/ai-gateway-controller --for=condition=Available

echo "🔀 Installing vLLM Semantic Router with local routing config..."
helm install semantic-router oci://ghcr.io/vllm-project/charts/semantic-router \
    --version 0.0.0-latest \
    --namespace vllm-semantic-router-system \
    --create-namespace \
    -f "$(dirname "$0")/semantic-router/values.yaml"
kubectl wait --for=condition=Available deployment/semantic-router -n vllm-semantic-router-system --timeout=600s

echo "🌉 Applying Gateway API resources (Gateway, backends, routes, ExtProc patch)..."
kubectl apply -f "$(dirname "$0")/semantic-router/gwapi-resources.yaml"

echo "✅ Semantic routing stack installed!"
echo "Next step: kubectl port-forward the Envoy gateway service in namespace vllm, then send model=auto requests."
