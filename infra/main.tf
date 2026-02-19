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

# ---- Cloud Functions Gen2 用 ZIP ----
data "archive_file" "ocr_trigger_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/ocr_trigger"
  output_path = "${path.module}/../files/ocr_trigger.zip"
}

data "archive_file" "md_generator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/md_generator"
  output_path = "${path.module}/../files/md_generator.zip"
}

resource "google_storage_bucket_object" "ocr_trigger_code" {
  bucket = google_storage_bucket.buckets["source"].name
  name   = "ocr_trigger.${data.archive_file.ocr_trigger_zip.output_md5}.zip"
  source = data.archive_file.ocr_trigger_zip.output_path
}

resource "google_storage_bucket_object" "md_generator_code" {
  bucket = google_storage_bucket.buckets["source"].name
  name   = "md_generator.${data.archive_file.md_generator_zip.output_md5}.zip"
  source = data.archive_file.md_generator_zip.output_path
}

# OCR Trigger Function（input bucket finalized → OCR 実行）
resource "google_cloudfunctions2_function" "ocr_trigger" {
  name     = "ocr-trigger"
  location = var.region

  build_config {
    runtime           = "python310"
    entry_point       = "start_ocr"
    docker_repository = google_artifact_registry_repository.gcf_artifacts.id
    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.ocr_trigger_code.name
      }
    }
  }

  service_config {
    available_memory      = "256Mi"
    max_instance_count    = 1
    ingress_settings      = "ALLOW_ALL"
    service_account_email = var.functions_service_account_email

    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PROCESSOR_LOCATION = var.documentai_location
      PROCESSOR_ID       = split("/", google_document_ai_processor.ocr_processor.id)[length(split("/", google_document_ai_processor.ocr_processor.id)) - 1]
      TEMP_BUCKET        = google_storage_bucket.buckets["temp"].name
      OUTPUT_BUCKET      = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    event_type            = "google.cloud.storage.object.v1.finalized"
    trigger_region        = var.region
    retry_policy          = "RETRY_POLICY_DO_NOT_RETRY"
    service_account_email = var.functions_service_account_email

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }

  }

  depends_on = [
    google_project_service.required,
    google_pubsub_topic_iam_member.gcs_publish_input,
    google_artifact_registry_repository.gcf_artifacts,
  ]
}

# MD Generator Function（temp bucket finalized → Markdown 生成）
resource "google_cloudfunctions2_function" "md_generator" {
  name     = "md-generator"
  location = var.region

  build_config {
    runtime           = "python310"
    entry_point       = "generate_markdown"
    docker_repository = google_artifact_registry_repository.gcf_artifacts.id
    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.md_generator_code.name
      }
    }
  }

  service_config {
    available_memory      = "1Gi"
    max_instance_count    = 3
    timeout_seconds       = 540
    ingress_settings      = "ALLOW_ALL"
    service_account_email = var.functions_service_account_email

    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      OUTPUT_BUCKET  = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    event_type            = "google.cloud.storage.object.v1.finalized"
    trigger_region        = var.region
    retry_policy          = "RETRY_POLICY_DO_NOT_RETRY"
    service_account_email = var.functions_service_account_email

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["temp"].name
    }

  }

  depends_on = [
    google_project_service.required,
    google_pubsub_topic_iam_member.gcs_publish_temp,
    google_artifact_registry_repository.gcf_artifacts,
  ]
}
