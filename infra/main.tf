data "google_project" "current" {
  project_id = var.project_id
}

resource "random_id" "bucket_suffix" {
  byte_length = 3
  keepers = {
    project = var.project_id
    region  = var.region
  }
}

locals {
  suffix = random_id.bucket_suffix.hex

  input_bucket_name  = "${var.project_id}-input-${local.suffix}"
  temp_bucket_name   = "${var.project_id}-temp-${local.suffix}"
  output_bucket_name = "${var.project_id}-output-${local.suffix}"
  source_bucket_name = var.source_bucket_name != "" ? var.source_bucket_name : "${var.project_id}-source-${local.suffix}"

  artifact_registry_repository_id = "gcf-artifacts"

  ocr_trigger_source_object  = "functions/${var.ocr_trigger_function_name}/function-source.zip"
  md_generator_source_object = "functions/${var.md_generator_function_name}/function-source.zip"

  md_generator_audience = "https://${var.region}-${var.project_id}.cloudfunctions.net/${var.md_generator_function_name}"

  documentai_service_agent_email = "service-${data.google_project.current.number}@gcp-sa-prod-dai-core.iam.gserviceaccount.com"

  runtime_sa_member  = "serviceAccount:${var.functions_runtime_service_account_email}"
  workflow_sa_member = "serviceAccount:${var.workflow_runner_service_account_email}"
}

#
# Buckets
#
resource "google_storage_bucket" "buckets" {
  for_each = {
    input  = local.input_bucket_name
    temp   = local.temp_bucket_name
    output = local.output_bucket_name
    source = local.source_bucket_name
  }

  name                        = each.value
  location                    = var.bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.required]
}

#
# Artifact Registry for Gen2 build artifacts
#
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.artifact_registry_location
  repository_id = local.artifact_registry_repository_id
  description   = "Artifacts for Cloud Functions Gen2"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

#
# Optional Firestore database creation
#
resource "google_firestore_database" "default" {
  count       = var.create_firestore_database ? 1 : 0
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required]
}

#
# Document AI processor
#
resource "google_document_ai_processor" "ocr" {
  location     = var.documentai_location
  display_name = var.documentai_processor_display_name
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.required]
}

#
# Source objects (dummy placeholders; actual code replaced by CI/CD)
#
resource "google_storage_bucket_object" "ocr_trigger_source" {
  name    = local.ocr_trigger_source_object
  bucket  = google_storage_bucket.buckets["source"].name
  content = "placeholder zip content for ocr-trigger"

  lifecycle {
    ignore_changes = [content]
  }
}

resource "google_storage_bucket_object" "md_generator_source" {
  name    = local.md_generator_source_object
  bucket  = google_storage_bucket.buckets["source"].name
  content = "placeholder zip content for md-generator"

  lifecycle {
    ignore_changes = [content]
  }
}

#
# IAM for runtime service account on buckets
#
resource "google_storage_bucket_iam_member" "runtime_input_viewer" {
  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectViewer"
  member = local.runtime_sa_member
}

resource "google_storage_bucket_iam_member" "runtime_temp_viewer" {
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectViewer"
  member = local.runtime_sa_member
}

resource "google_storage_bucket_iam_member" "runtime_output_admin" {
  bucket = google_storage_bucket.buckets["output"].name
  role   = "roles/storage.objectAdmin"
  member = local.runtime_sa_member
}

#
# IAM for workflow SA
#
resource "google_storage_bucket_iam_member" "workflow_temp_viewer" {
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectViewer"
  member = local.workflow_sa_member
}

resource "google_storage_bucket_iam_member" "workflow_output_admin" {
  bucket = google_storage_bucket.buckets["output"].name
  role   = "roles/storage.objectAdmin"
  member = local.workflow_sa_member
}

#
# IAM for Document AI service agent
# input read / temp write
#
resource "google_storage_bucket_iam_member" "docai_input_viewer" {
  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.documentai_service_agent_email}"
}

resource "google_storage_bucket_iam_member" "docai_temp_creator" {
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${local.documentai_service_agent_email}"
}

#
# Workflow service account can invoke md-generator
#
resource "google_cloudfunctions2_function_iam_member" "workflow_md_generator_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.md_generator.name
  role           = "roles/cloudfunctions.invoker"
  member         = local.workflow_sa_member
}

#
# Workflows definition
#
resource "google_workflows_workflow" "docai_monitor" {
  name            = var.workflow_name
  region          = var.region
  service_account = var.workflow_runner_service_account_email
  description     = "Monitor Document AI batch LRO and trigger markdown generation"

  source_contents = templatefile("${path.module}/workflows/docai_monitor.yaml", {
    project_id            = var.project_id
    jobs_collection       = var.firestore_jobs_collection
    md_generator_url      = google_cloudfunctions2_function.md_generator.service_config[0].uri
    md_generator_audience = local.md_generator_audience
  })

  depends_on = [
    google_project_service.required,
    google_cloudfunctions2_function.md_generator
  ]
}

#
# OCR trigger function
#
resource "google_cloudfunctions2_function" "ocr_trigger" {
  name     = var.ocr_trigger_function_name
  location = var.region

  build_config {
    runtime     = "python310"
    entry_point = "start_ocr"

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.ocr_trigger_source.name
      }
    }
  }

  service_config {
    available_memory      = var.ocr_trigger_available_memory
    timeout_seconds       = var.ocr_trigger_timeout_seconds
    max_instance_count    = var.ocr_trigger_max_instance_count
    min_instance_count    = var.ocr_trigger_min_instance_count
    ingress_settings      = "ALLOW_ALL"
    service_account_email = var.functions_runtime_service_account_email

    environment_variables = {
      APP_ENV                     = "gcp"
      GCP_PROJECT_ID              = var.project_id
      GCP_LOCATION                = var.gcp_location
      PROCESSOR_ID                = google_document_ai_processor.ocr.name
      PROCESSOR_LOCATION          = var.documentai_location
      INPUT_BUCKET                = google_storage_bucket.buckets["input"].name
      TEMP_BUCKET                 = "gs://${google_storage_bucket.buckets["temp"].name}"
      OUTPUT_BUCKET               = google_storage_bucket.buckets["output"].name
      FIRESTORE_JOBS_COLLECTION   = var.firestore_jobs_collection
      DOCAI_MONITOR_WORKFLOW_NAME = google_workflows_workflow.docai_monitor.name
      WORKFLOW_REGION             = var.region
      MD_GENERATOR_URL            = google_cloudfunctions2_function.md_generator.service_config[0].uri
      MD_GENERATOR_AUDIENCE       = local.md_generator_audience
      DOCAI_SUBMIT_TIMEOUT_SEC    = tostring(var.docai_submit_timeout_sec)
      LOG_EXECUTION_ID            = "true"
    }

    max_instance_request_concurrency = 1
  }

  event_trigger {
    event_type            = "google.cloud.storage.object.v1.finalized"
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = var.functions_runtime_service_account_email
    trigger_region        = var.region

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.runtime_input_viewer,
    google_storage_bucket_iam_member.docai_input_viewer,
    google_storage_bucket_iam_member.docai_temp_creator,
    google_storage_bucket_object.ocr_trigger_source,
    google_workflows_workflow.docai_monitor
  ]

  lifecycle {
    ignore_changes = [
      build_config[0].source[0].storage_source[0].object,
      build_config[0].source[0].storage_source[0].generation,
    ]
  }
}

#
# Markdown generator function (HTTP only)
#
resource "google_cloudfunctions2_function" "md_generator" {
  name     = var.md_generator_function_name
  location = var.region

  build_config {
    runtime     = "python310"
    entry_point = "generate_markdown"

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.md_generator_source.name
      }
    }
  }

  service_config {
    available_memory      = var.md_generator_available_memory
    timeout_seconds       = var.md_generator_timeout_seconds
    max_instance_count    = var.md_generator_max_instance_count
    min_instance_count    = var.md_generator_min_instance_count
    ingress_settings      = "ALLOW_ALL"
    service_account_email = var.functions_runtime_service_account_email

    environment_variables = {
      APP_ENV                   = "gcp"
      GCP_PROJECT_ID            = var.project_id
      GCP_LOCATION              = var.gcp_location
      TEMP_BUCKET               = google_storage_bucket.buckets["temp"].name
      OUTPUT_BUCKET             = google_storage_bucket.buckets["output"].name
      FIRESTORE_JOBS_COLLECTION = var.firestore_jobs_collection
      GEMINI_MODEL_NAME         = var.gemini_model_name
      LOG_EXECUTION_ID          = "true"
    }

    max_instance_request_concurrency = 1
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.runtime_temp_viewer,
    google_storage_bucket_iam_member.runtime_output_admin,
    google_storage_bucket_object.md_generator_source
  ]

  lifecycle {
    ignore_changes = [
      build_config[0].source[0].storage_source[0].object,
      build_config[0].source[0].storage_source[0].generation,
    ]
  }
}
