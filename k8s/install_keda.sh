#!/bin/bash

echo "🚀 Setting up KEDA via Helm"

# 1. Add KEDA Helm Repo
echo "📦 Adding KEDA Helm repository..."
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# 2. Install KEDA
echo "⚙️ Installing KEDA operator..."
helm upgrade --install keda kedacore/keda \
    --namespace keda \
    --create-namespace \
    --wait

echo "✅ KEDA installation complete!"
echo "Note: The KEDA HTTP Add-on was removed. We are using our custom proxy for scale-to-zero instead."
echo "Next step: Deploy your new vLLM Helm chart."
