#!/bin/bash

# Ensure API Key is provided
if [ -z "$DD_API_KEY" ]; then
    echo "❌ Error: DD_API_KEY environment variable is not set."
    echo "Please run: export DD_API_KEY='your-api-key'"
    exit 1
fi

# Set default Datadog site (can be overridden, e.g., datadoghq.eu)
DD_SITE=${DD_SITE:-"datadoghq.com"}

echo "🚀 Setting up Datadog Agent via Helm..."

# 1. Add Datadog Helm Repo
echo "📦 Adding Datadog Helm repository..."
helm repo add datadog https://helm.datadoghq.com
helm repo update

# 2. Install Datadog
echo "⚙️ Installing Datadog Agent..."
helm upgrade --install datadog datadog/datadog \
    --namespace datadog \
    --create-namespace \
    --set datadog.apiKey=$DD_API_KEY \
    --set datadog.site=$DD_SITE \
    --set datadog.prometheusScrape.enabled=true \
    --set providers.gke.cos=true \
    --set datadog.systemProbe.enabled=false \
    --set datadog.clusterName="vllm-cluster" \
    --set datadog.kubeStateMetricsCore.enabled=true \
    --set datadog.orchestratorExplorer.enabled=true \
    --set agents.tolerations[0].operator=Exists \
    --wait

echo "✅ Datadog installation complete!"
echo "The agent will now automatically scrape metrics from pods annotated with ad.datadoghq.com (like our vLLM pod)."
