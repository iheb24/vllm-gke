output "cluster_name" {
  value = module.vllm-cluster.cluster_name
}

output "cluster_endpoint" {
  value     = module.vllm-cluster.cluster_endpoint
  sensitive = true
}

output "vllm_service_account_email" {
  value = module.vllm-cluster.vllm_service_account_email
}

output "rag_docs_bucket_name" {
  value = module.vllm-cluster.rag_docs_bucket_name
}

output "rag_ingest_service_account_email" {
  value = module.vllm-cluster.rag_ingest_service_account_email
}
