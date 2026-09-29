variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "network_name" {
  type    = string
  default = "vllm-vpc"
}

variable "subnet_name" {
  type    = string
  default = "vllm-subnet"
}
