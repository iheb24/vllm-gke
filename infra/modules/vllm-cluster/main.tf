terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0.0"
    }
  }
}

# trivy:ignore:gcp-0051
# trivy:ignore:gcp-0056
resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  network    = var.network_name
  subnetwork = var.subnet_name

  deletion_protection      = false
  remove_default_node_pool = true
  initial_node_count       = 1

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.authorized_ip_ranges
      content {
        cidr_block   = cidr_blocks.value.cidr_block
        display_name = cidr_blocks.value.display_name
      }
    }
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "gke-pods"
    services_secondary_range_name = "gke-services"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "gpu_pool" {
  name           = "gpu-pool"
  location       = var.region
  cluster        = google_container_cluster.primary.name
  project        = var.project_id
  node_locations = ["${var.region}-a"]

  autoscaling {
    min_node_count = 0
    max_node_count = 1
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  # trivy:ignore:gcp-0048
  # trivy:ignore:gcp-0050
  # trivy:ignore:gcp-0054
  node_config {
    machine_type = "g2-standard-8"
    spot         = true

    guest_accelerator {
      type  = "nvidia-l4"
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "DEFAULT"
      }
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}

resource "google_service_account" "vllm_sa" {
  account_id   = "vllm-sa"
  display_name = "Service Account for vLLM Workload Identity"
  project      = var.project_id
}

resource "google_service_account_iam_binding" "workload_identity_binding" {
  service_account_id = google_service_account.vllm_sa.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "serviceAccount:${var.project_id}.svc.id.goog[default/vllm-ksa]"
  ]

  depends_on = [
    google_container_cluster.primary
  ]
}
