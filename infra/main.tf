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

# Cloud Functions Gen2 のイベント通知に必要（GCS -> Pub/Sub publish）
data "google_storage_project_service_account" "gcs_account" {}

# ====== ここから（解決策B：Project IAM をやめて Topic IAM にする）======

# GCS通知用の Pub/Sub Topic（input用 / temp用）
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

# GCS サービスアカウントに、各 Topic への publish 権限を付与（Topic IAM）
resource "google_pubsub_topic_iam_member" "gcs_publish_input" {
  project = var.project_id
  topic   = google_pubsub_topic.gcs_input_finalized.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic_iam_member" "gcs_publish_temp" {
  project = var.project_id
  topic   = google_pubsub_topic.gcs_temp_finalized.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"

  depends_on = [google_project_service.required]
}

# ====== ここまで（解決策B）======


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
    runtime     = "python310"
    entry_point = "start_ocr"
    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.ocr_trigger_code.name
      }
    }
  }

  service_config {
    available_memory   = "256Mi"
    max_instance_count = 1
    ingress_settings   = "ALLOW_ALL"

    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PROCESSOR_LOCATION = var.documentai_location
      PROCESSOR_ID       = google_document_ai_processor.ocr_processor.id
      TEMP_BUCKET        = google_storage_bucket.buckets["temp"].name
      OUTPUT_BUCKET      = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    event_type     = "google.cloud.storage.object.v1.finalized"
    trigger_region = var.region
    retry_policy   = "RETRY_POLICY_DO_NOT_RETRY"

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }

    # ★ 追加：明示的に topic を指定（Topic IAM の publish 先）
    pubsub_topic = google_pubsub_topic.gcs_input_finalized.id
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
    runtime     = "python310"
    entry_point = "generate_markdown"
    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.md_generator_code.name
      }
    }
  }

  service_config {
    available_memory   = "1Gi"
    max_instance_count = 3
    timeout_seconds    = 540
    ingress_settings   = "ALLOW_ALL"

    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      OUTPUT_BUCKET  = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    event_type     = "google.cloud.storage.object.v1.finalized"
    trigger_region = var.region
    retry_policy   = "RETRY_POLICY_DO_NOT_RETRY"

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["temp"].name
    }

    # ★ 追加：明示的に topic を指定（Topic IAM の publish 先）
    pubsub_topic = google_pubsub_topic.gcs_temp_finalized.id
  }

  depends_on = [
    google_project_service.required,
    google_pubsub_topic_iam_member.gcs_publish_temp,
    google_artifact_registry_repository.gcf_artifacts,
  ]
}
