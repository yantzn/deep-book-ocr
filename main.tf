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

# --- 1. ストレージバケット ---
resource "google_storage_bucket" "buckets" {
  for_each = toset(["input", "temp", "output", "source"])

  name          = "${var.project_id}-${each.key}"
  location      = var.region
  force_destroy = true
}

# --- 2. 権限設定: GCS -> Pub/Sub publish (Cloud Functions Gen2 のイベント通知に必要) ---
data "google_storage_project_service_account" "gcs_account" {}

resource "google_project_iam_member" "gcs_pubsub_publishing" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# --- 3. Artifact Registry (Cloud Functions Gen2 の build artifacts) ---
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.region
  repository_id = "gcf-artifacts"
  format        = "DOCKER"
}

# --- 4. Document AI プロセッサ ---
# Document AI のロケーションは region と別体系なので us を維持
resource "google_document_ai_processor" "ocr_processor" {
  location     = "us"
  display_name = "book-ocr-processor"
  type         = "OCR_PROCESSOR"
}

# --- 5. アーカイブとアップロード ---
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
}

resource "google_storage_bucket_object" "md_generator_code" {
  name   = "md_generator.${data.archive_file.md_generator_zip.output_md5}.zip"
  bucket = google_storage_bucket.buckets["source"].name
  source = data.archive_file.md_generator_zip.output_path
}

# --- 6. Cloud Functions (第2世代) ---
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
    google_project_iam_member.gcs_pubsub_publishing,
    google_artifact_registry_repository.gcf_artifacts
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
    google_project_iam_member.gcs_pubsub_publishing,
    google_artifact_registry_repository.gcf_artifacts
  ]
}

# --- 7. Workload Identity (GitHub Actions認証) ---
resource "google_iam_workload_identity_pool" "pool" {
  workload_identity_pool_id = "github-actions-pool-v2"
  display_name              = "GitHub Actions Pool-v2"
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

  # この repo からのトークンだけ許可
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "github_sa" {
  account_id   = "github-actions-sa"
  display_name = "GitHub Actions Service Account"
}

# ✅ Terraform を回すためのプロジェクト権限（最小化するなら要調整）
resource "google_project_iam_member" "github_sa_project_roles" {
  for_each = toset([
    "roles/editor"
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

# ✅ ここが最重要：WIF principalSet に対して、サービスアカウントの “なりすまし” を許可
# repository 属性で縛る（owner/repo）
locals {
  github_principal_set = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "github_wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principal_set
}

# access_token を発行するなら token creator も付ける（これが無いと getAccessToken で落ちやすい）
resource "google_service_account_iam_member" "github_wif_token_creator" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.github_principal_set
}

output "wif_provider_name" {
  value = google_iam_workload_identity_pool_provider.provider.name
}

output "github_actions_service_account" {
  value = google_service_account.github_sa.email
}
