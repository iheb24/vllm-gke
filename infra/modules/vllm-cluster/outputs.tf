output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  value     = google_container_cluster.primary.endpoint
  sensitive = true
}

output "vllm_service_account_email" {
  value = google_service_account.vllm_sa.email
}

output "rag_docs_bucket_name" {
  value = google_storage_bucket.rag_docs.name
}

output "rag_ingest_service_account_email" {
  value = google_service_account.rag_ingest_sa.email
}
