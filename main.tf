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
  for_each      = toset(["input", "temp", "output", "source"])
  name          = "${var.project_id}-${each.key}"
  location      = var.region
  force_destroy = true
}

# --- 2. 権限設定 (Code 7 の修正) ---
# Storage専用サービスアカウントを取得
data "google_storage_project_service_account" "gcs_account" {}

# StorageにPub/Subへの通知権限を与える
resource "google_project_iam_member" "gcs_pubsub_publishing" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# --- 3. Artifact Registry (Code 13 の修正) ---
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.region
  repository_id = "gcf-artifacts"
  format        = "DOCKER"
}

# --- 4. Document AI プロセッサ ---
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
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  # リポジトリ名は「あなたのユーザー名/リポジトリ名」に書き換えてください
  attribute_condition = "assertion.repository == 'yantzn/deep-book-ocr'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "github_sa" {
  account_id   = "github-actions-sa"
  display_name = "GitHub Actions Service Account"
}

resource "google_project_iam_member" "sa_roles" {
  for_each = toset(["roles/editor", "roles/iam.workloadIdentityUser"])
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.github_sa.email}"
}

output "wif_provider_name" {
  value = google_iam_workload_identity_pool_provider.provider.name
}
