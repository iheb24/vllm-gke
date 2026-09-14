#!/bin/bash

# Extract project ID from gcloud
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Could not determine GCP Project ID."
    echo "Please set it by running: gcloud config set project YOUR_PROJECT"
    exit 1
fi

REGION="us-central1"
REPO_NAME="vllm-repo"
IMAGE_NAME="vllm-proxy"
TAG="latest"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "📦 Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories create ${REPO_NAME} \
    --repository-format=docker \
    --location=${REGION} \
    --description="Docker repository for vLLM proxy" \
    2>/dev/null || echo "Repository already exists."

echo "🚀 Building and pushing image using Google Cloud Build..."
echo "Target Image: ${IMAGE_URI}"
gcloud builds submit --tag ${IMAGE_URI} .

echo "✅ Cloud Build complete!"
