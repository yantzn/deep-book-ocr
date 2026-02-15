terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ------------------------------------------------------------
# 0. Required APIs (改善点: Cloud Resource Manager API を含め、初回で落ちる要因を排除)
# ------------------------------------------------------------
resource "google_project_service" "required" {
  for_each = toset([
    # IAM / Project IAM policy 読み書きに必要
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com",

    # 本プロジェクトの主要構成
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "eventarc.googleapis.com",

    # OCR / LLM
    "documentai.googleapis.com",
    "aiplatform.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ------------------------------------------------------------
# 1. Storage Buckets
# ------------------------------------------------------------
resource "google_storage_bucket" "buckets" {
  for_each = toset(["input", "temp", "output", "source"])

  name          = "${var.project_id}-${each.key}"
  location      = var.region
  force_destroy = true

  depends_on = [google_project_service.required]
}

# ------------------------------------------------------------
# 2. Permissions: GCS -> Pub/Sub publish (Cloud Functions Gen2 eventing)
# ------------------------------------------------------------
data "google_storage_project_service_account" "gcs_account" {}

resource "google_project_iam_member" "gcs_pubsub_publishing" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"

  depends_on = [google_project_service.required]
}

# ------------------------------------------------------------
# 3. Artifact Registry (Cloud Functions Gen2 build artifacts)
# ------------------------------------------------------------
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.region
  repository_id = "gcf-artifacts"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

# ------------------------------------------------------------
# 4. Document AI Processor
#    NOTE: Document AI location は region と別体系。現状 repo では us 固定。
# ------------------------------------------------------------
resource "google_document_ai_processor" "ocr_processor" {
  location     = "us"
  display_name = "book-ocr-processor"
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.required]
}

# ------------------------------------------------------------
# 5. Archive + Upload function source zips
# ------------------------------------------------------------
data "archive_file" "ocr_trigger_zip" {
  type        = "zip"
  source_dir  = "${path.module}/functions/ocr_trigger"
  output_path = "${path.module}/files/ocr_trigger.zip"
}

data "archive_file" "md_generator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/functions/md_generator"
  output_path = "${path.module}/files/md_generator.zip"
}

resource "google_storage_bucket_object" "ocr_trigger_code" {
  name   = "ocr_trigger.${data.archive_file.ocr_trigger_zip.output_md5}.zip"
  bucket = google_storage_bucket.buckets["source"].name
  source = data.archive_file.ocr_trigger_zip.output_path

  depends_on = [google_storage_bucket.buckets]
}

resource "google_storage_bucket_object" "md_generator_code" {
  name   = "md_generator.${data.archive_file.md_generator_zip.output_md5}.zip"
  bucket = google_storage_bucket.buckets["source"].name
  source = data.archive_file.md_generator_zip.output_path

  depends_on = [google_storage_bucket.buckets]
}

# ------------------------------------------------------------
# 6. Cloud Functions (Gen2)
# ------------------------------------------------------------
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
    max_instance_count = 1
    available_memory   = "256Mi"
    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      PROCESSOR_ID   = google_document_ai_processor.ocr_processor.name
      TEMP_BUCKET    = "gs://${google_storage_bucket.buckets["temp"].name}"
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.storage.object.v1.finalized"
    retry_policy   = "RETRY_POLICY_DO_NOT_RETRY"

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.gcs_pubsub_publishing,
    google_artifact_registry_repository.gcf_artifacts,
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
        object = google_storage_bucket_object.md_generator_code.name
      }
    }
  }

  service_config {
    max_instance_count = 3
    available_memory   = "1Gi"
    timeout_seconds    = 540
    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      OUTPUT_BUCKET  = google_storage_bucket.buckets["output"].name
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.storage.object.v1.finalized"
    retry_policy   = "RETRY_POLICY_DO_NOT_RETRY"

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["temp"].name
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.gcs_pubsub_publishing,
    google_artifact_registry_repository.gcf_artifacts,
  ]
}

# ------------------------------------------------------------
# 7. Workload Identity Federation for GitHub Actions
#    - project IAM に roles/iam.workloadIdentityUser を付けない
#    - principalSet に対して SA IAM で roles/iam.workloadIdentityUser + TokenCreator を付与
#    - Pool/Provider は v2 名称（衝突回避）
# ------------------------------------------------------------
resource "google_iam_workload_identity_pool" "pool" {
  workload_identity_pool_id = "github-actions-pool-v2"
  display_name              = "GitHub Actions Pool v2"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider-v2"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.actor"            = "assertion.actor"
    "attribute.ref"              = "assertion.ref"
  }

  # このリポジトリのみ許可
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "github_sa" {
  account_id   = "github-actions-sa"
  display_name = "GitHub Actions Service Account"

  depends_on = [google_project_service.required]
}

# Terraform を回すための権限（暫定：roles/editor）
# 最小権限化は可能だが、初期は editor で安定運用 → 後から絞るのが安全
resource "google_project_iam_member" "github_sa_project_roles" {
  for_each = toset([
    "roles/editor"
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.github_sa.email}"

  depends_on = [google_project_service.required]
}

# WIF principalSet に対して SA のなりすまし許可
locals {
  github_principal_set = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "github_wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principal_set
}

# access_token を発行するなら Token Creator
resource "google_service_account_iam_member" "github_wif_token_creator" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.github_principal_set
}

# ------------------------------------------------------------
# Outputs
# ------------------------------------------------------------
output "wif_provider_name" {
  value = google_iam_workload_identity_pool_provider.provider.name
}

output "github_actions_service_account" {
  value = google_service_account.github_sa.email
}
