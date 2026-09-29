# RAG components

Retrieval-augmented generation on top of the existing vLLM stack. Design and
rationale: `docs/rag-architecture.md`. All components run in the `rag`
namespace on the dedicated `rag-pool` CPU nodes (`workload=rag` label),
ClusterIP only, nothing touches the GPU pool.

## Components

| Directory | Component | Purpose |
| --- | --- | --- |
| `qdrant/` | Qdrant vector database (Helm) | Stores chunk vectors for the versioned `docs-v1` collection (1024-dim, cosine) |
| `embeddings/` | TEI vs llama.cpp embedding servers | Candidates for the CPU embedding tier; the benchmark in `bench/` picks the winner and the loser is deleted |
| `ingest/` | Ingestion CronJob | GCS bucket -> parse (Docling) -> split -> embed -> upsert; idempotent |
| `retrieval/` | Retrieval API (FastAPI) | `/search` over Qdrant, `/chat` end-to-end through the Envoy gateway with citations |

## Qdrant deployment

Create the namespace and the API key secret (pick your own key, never commit
it):

```bash
kubectl create namespace rag
kubectl -n rag create secret generic qdrant-apikey --from-literal=api-key='YOUR_QDRANT_KEY'
```

Install via the official Helm chart:

```bash
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm upgrade --install qdrant qdrant/qdrant -n rag -f k8s/rag/qdrant/values.yaml
```

Validate:

```bash
kubectl -n rag get pods,pvc
kubectl -n rag rollout status statefulset/qdrant

kubectl -n rag port-forward svc/qdrant 6333:6333 &
export QDRANT_KEY=$(kubectl -n rag get secret qdrant-apikey -o jsonpath='{.data.api-key}' | base64 -d)
curl -H "api-key: $QDRANT_KEY" localhost:6333/collections   # expect empty list
curl localhost:6333/readyz                                  # expect ok
```

Create the versioned collection (embedding model is locked to it — changing
the model means a new collection and a full re-embed):

```bash
curl -X PUT -H "api-key: $QDRANT_KEY" -H 'Content-Type: application/json' \
  localhost:6333/collections/docs-v1 \
  -d '{"vectors": {"size": 1024, "distance": "Cosine"}}'
```

## Embedding servers

Both candidates need the shared API key secret:

```bash
kubectl -n rag create secret generic embed-apikey --from-literal=api-key='YOUR_EMBED_KEY'
kubectl apply -f k8s/rag/embeddings/tei-deployment.yaml
kubectl apply -f k8s/rag/embeddings/llamacpp-deployment.yaml
```

Benchmark both (see `bench/embed_bench.py` and `bench/similarity_sanity.py`),
record the results in `bench/results.md`, keep the winner and delete the loser
deployment. Update `EMBED_URL` in `ingest/cronjob.yaml` and
`retrieval/deployment.yaml` to point at the winner.

## Ingestion job

Build and push the image (needs an Artifact Registry repo named `rag`), then
fill in the placeholders in `ingest/cronjob.yaml` (GCP service account email,
image path, bucket name):

```bash
gcloud artifacts repositories create rag --repository-format=docker \
  --location=REGION --project=YOUR_PROJECT_ID
gcloud builds submit ingest --tag REGION-docker.pkg.dev/YOUR_PROJECT_ID/rag/ingest:latest
kubectl apply -f k8s/rag/ingest/cronjob.yaml
```

Manual runs go through the CronJob (idempotent, safe to re-run):

```bash
kubectl -n rag create job ingest-manual-1 --from=cronjob/ingest
kubectl -n rag logs -f job/ingest-manual-1
```

## Retrieval API

Build and push like the ingestion image, fill in the image placeholder in
`retrieval/deployment.yaml`, then:

```bash
kubectl apply -f k8s/rag/retrieval/deployment.yaml
kubectl -n rag port-forward svc/retrieval 8090:8090 &
curl localhost:8090/search -H 'Content-Type: application/json' \
  -d '{"query":"how does KEDA wake the GPU pool?"}'
```
