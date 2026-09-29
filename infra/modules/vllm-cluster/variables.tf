variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west4"
}

variable "cluster_name" {
  type    = string
  default = "vllm-cluster"
}

variable "network_name" {
  type = string
}

variable "subnet_name" {
  type = string
}

variable "authorized_ip_ranges" {
  type = list(object({
    cidr_block   = string
    display_name = string
  }))
  default = []
}

variable "system_machine_type" {
  description = "Machine type for the always-on system node pool"
  type        = string
  default     = "e2-standard-4"
}

variable "rag_machine_type" {
  description = "Machine type for the RAG node pool (Qdrant, embedding server, retrieval API)"
  type        = string
  default     = "e2-standard-2"
}

variable "rag_docs_bucket_name" {
  description = "Globally unique name for the GCS bucket holding RAG source documents"
  type        = string
}
