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
