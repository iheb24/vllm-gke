#!/bin/bash

# Ensure PROJECT_ID is set or extract from gcloud
PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Could not determine GCP Project ID."
    echo "Please set PROJECT_ID or run: gcloud config set project YOUR_PROJECT"
    exit 1
fi

REGION="us-central1"
REPO_NAME="vllm-repo"
IMAGE_NAME="vllm-proxy"
TAG="latest"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "🚀 Building Docker image: ${IMAGE_NAME}:${TAG}..."
docker build -t ${IMAGE_URI} .

echo "📦 Pushing image to Artifact Registry: ${IMAGE_URI}..."
docker push ${IMAGE_URI}

echo "✅ Build and push complete!"
echo "Update your Helm values.yaml to use image: ${IMAGE_URI}"
