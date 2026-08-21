#!/bin/bash

echo "🚀 Setting up KEDA and the KEDA HTTP Add-on via Helm"

# 1. Add KEDA Helm Repo
echo "📦 Adding KEDA Helm repository..."
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# 2. Install KEDA
echo "⚙️ Installing KEDA operator..."
helm install keda kedacore/keda \
    --namespace keda \
    --create-namespace \
    --wait

# 3. Install KEDA HTTP Add-on
echo "⚙️ Installing KEDA HTTP Add-on (for 0-to-1 routing)..."
helm install http-add-on kedacore/keda-add-ons-http \
    --namespace keda \
    --wait

echo "✅ KEDA installation complete!"
echo "Next step: Deploy your new vLLM Helm chart."
