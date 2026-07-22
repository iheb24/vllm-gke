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
