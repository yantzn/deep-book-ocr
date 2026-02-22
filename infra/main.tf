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
  gcs_service_agent               = "service-${data.google_project.current.number}@gs-project-accounts.iam.gserviceaccount.com"
  functions_build_service_account = "projects/${var.project_id}/serviceAccounts/${var.functions_service_account_email}"
  documentai_service_agent_email  = "service-${data.google_project.current.number}@gcp-sa-prod-dai-core.iam.gserviceaccount.com"
  documentai_service_agent_emails_effective = var.documentai_service_agent_email_override != "" ? [
    var.documentai_service_agent_email_override,
    ] : distinct(concat(
      [local.documentai_service_agent_email],
      var.documentai_service_agent_emails_additional,
  ))
}

resource "google_storage_bucket_iam_member" "documentai_input_bucket_object_viewer" {
  for_each = var.enable_documentai_bucket_iam ? toset(local.documentai_service_agent_emails_effective) : toset([])

  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.key}"
}

resource "google_storage_bucket_iam_member" "documentai_temp_bucket_object_creator" {
  for_each = var.enable_documentai_bucket_iam ? toset(local.documentai_service_agent_emails_effective) : toset([])

  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${each.key}"
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

data "archive_file" "ocr_source_zip" {
  type = "zip"
  source {
    filename = "main.py"
    content  = <<-EOT
def start_ocr(cloud_event):
    return None
EOT
  }
  output_path = "${path.module}/../files/ocr-trigger.zip"
}

data "archive_file" "md_source_zip" {
  type = "zip"
  source {
    filename = "main.py"
    content  = <<-EOT
def generate_markdown(cloud_event):
    return None
EOT
  }
  output_path = "${path.module}/../files/md-generator.zip"
}

resource "google_storage_bucket_object" "ocr_zip" {
  name   = "ocr-trigger.zip"
  bucket = google_storage_bucket.buckets["source"].name
  source = data.archive_file.ocr_source_zip.output_path
}

resource "google_storage_bucket_object" "md_zip" {
  name   = "md-generator.zip"
  bucket = google_storage_bucket.buckets["source"].name
  source = data.archive_file.md_source_zip.output_path
}

resource "google_cloudfunctions2_function" "ocr_trigger" {
  name     = "ocr-trigger"
  location = var.region

  build_config {
    runtime     = "python310"
    entry_point = "start_ocr"

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.ocr_zip.name
      }
    }

    docker_repository = google_artifact_registry_repository.gcf_artifacts.id
    service_account   = local.functions_build_service_account
  }

  service_config {
    available_memory      = "256M"
    max_instance_count    = 1
    service_account_email = var.functions_service_account_email
    environment_variables = {
      GCP_PROJECT_ID     = var.project_id
      PROCESSOR_LOCATION = var.documentai_location
      PROCESSOR_ID       = google_document_ai_processor.ocr_processor.id
      TEMP_BUCKET        = google_storage_bucket.buckets["temp"].name
      OUTPUT_BUCKET      = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.storage.object.v1.finalized"
    service_account_email = var.functions_service_account_email
    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }
    retry_policy = "RETRY_POLICY_RETRY"
  }

  lifecycle {
    ignore_changes = [
      build_config[0].source,
    ]
  }

  depends_on = [
    google_project_service.required,
    google_artifact_registry_repository.gcf_artifacts,
    google_storage_bucket_object.ocr_zip,
  ]
}

resource "google_cloudfunctions2_function" "md_generator" {
  name     = "md-generator"
  location = var.region

  build_config {
    runtime     = "python310"
    entry_point = "generate_markdown"

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.md_zip.name
      }
    }

    docker_repository = google_artifact_registry_repository.gcf_artifacts.id
    service_account   = local.functions_build_service_account
  }

  service_config {
    available_memory      = "1G"
    timeout_seconds       = 540
    max_instance_count    = 3
    service_account_email = var.functions_service_account_email
    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      OUTPUT_BUCKET  = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.storage.object.v1.finalized"
    service_account_email = var.functions_service_account_email
    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["temp"].name
    }
    retry_policy = "RETRY_POLICY_RETRY"
  }

  lifecycle {
    ignore_changes = [
      build_config[0].source,
    ]
  }

  depends_on = [
    google_project_service.required,
    google_artifact_registry_repository.gcf_artifacts,
    google_storage_bucket_object.md_zip,
  ]
}
