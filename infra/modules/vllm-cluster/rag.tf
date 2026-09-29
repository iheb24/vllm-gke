resource "google_container_node_pool" "rag_pool" {
  name     = "rag-pool"
  location = "${var.region}-b"
  cluster  = google_container_cluster.primary.name
  project  = var.project_id

  node_count = 1

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.rag_machine_type
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.vllm_sa.email

    labels = {
      workload = "rag"
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}

# trivy:ignore:gcp-0066
resource "google_storage_bucket" "rag_docs" {
  name     = var.rag_docs_bucket_name
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }
}

resource "google_service_account" "rag_ingest_sa" {
  account_id   = "rag-ingest-sa"
  display_name = "Service Account for RAG Ingestion Workload Identity"
  project      = var.project_id
}

resource "google_storage_bucket_iam_member" "rag_ingest_object_viewer" {
  bucket = google_storage_bucket.rag_docs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.rag_ingest_sa.email}"
}

resource "google_service_account_iam_binding" "rag_ingest_workload_identity_binding" {
  service_account_id = google_service_account.rag_ingest_sa.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "serviceAccount:${var.project_id}.svc.id.goog[rag/ingestion]"
  ]

  depends_on = [
    google_container_cluster.primary
  ]
}
