terraform {
  required_version = ">= 1.0.0"
  backend "gcs" {}
}

module "network" {
  source     = "../../modules/network"
  project_id = var.project_id
  region     = "europe-west4"
}

module "vllm-cluster" {
  source       = "../../modules/vllm-cluster"
  project_id   = var.project_id
  network_name = module.network.network_name
  subnet_name  = module.network.subnet_name
  region       = "europe-west4"

  authorized_ip_ranges = [
    {
      cidr_block   = "${var.my_public_ip}/32"
      display_name = "My Local VSCode Machine"
    }
  ]
}
