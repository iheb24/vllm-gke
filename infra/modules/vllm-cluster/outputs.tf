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
