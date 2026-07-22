variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west4"
}

variable "network_name" {
  type    = string
  default = "vllm-vpc"
}

variable "subnet_name" {
  type    = string
  default = "vllm-subnet"
}
