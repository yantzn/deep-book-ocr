locals {
  bucket_keys = toset(["input", "output", "source", "temp"])
}

resource "random_id" "bucket_suffix" {
  byte_length = 3 # 6 hex

  keepers = {
    rotation = var.bucket_rotation_key
    project  = var.project_id
  }
}

locals {
  suffix = random_id.bucket_suffix.hex
  bucket_name = {
    for k in local.bucket_keys : k => "${var.project_id}-${k}-${local.suffix}"
  }
}

resource "google_storage_bucket" "buckets" {
  for_each = local.bucket_name

  name          = each.value
  location      = var.bucket_location
  storage_class = "STANDARD"
  force_destroy = true

  depends_on = [google_project_service.required]
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  gcs_service_agent = "service-${data.google_project.current.number}@gs-project-accounts.iam.gserviceaccount.com"
}

resource "google_pubsub_topic" "gcs_input_finalized" {
  name    = "gcs-input-finalized-${local.suffix}"
  project = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "gcs_temp_finalized" {
  name    = "gcs-temp-finalized-${local.suffix}"
  project = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic_iam_member" "gcs_publish_input" {
  project = var.project_id
  topic   = google_pubsub_topic.gcs_input_finalized.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.gcs_service_agent}"
}

resource "google_pubsub_topic_iam_member" "gcs_publish_temp" {
  project = var.project_id
  topic   = google_pubsub_topic.gcs_temp_finalized.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.gcs_service_agent}"
}

# Artifact Registry（Cloud Functions Gen2 build 用）
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.region
  repository_id = "gcf-artifacts"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

# Document AI OCR Processor
resource "google_document_ai_processor" "ocr_processor" {
  display_name = "book-ocr-processor"
  location     = var.documentai_location
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.required]
}
