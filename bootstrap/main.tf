locals {
  # これらの値が変わると random_id が再生成され、
  # バケット名/SA名/WIF ID の suffix が切り替わる。
  # 既存資源を維持したい場合は不用意に変更しないこと。
  suffix_keepers = {
    project  = var.project_id
    repo     = var.github_repository
    rotation = var.rotation_key
  }
}

resource "random_id" "suffix" {
  # 2 bytes = 4 hex（例: 0488）
  # 各IDの長さ制約を超えにくく、衝突確率も十分低いサイズ。
  byte_length = 2
  keepers     = local.suffix_keepers
}

locals {
  suffix = random_id.suffix.hex

  tfstate_bucket_name     = "${var.project_id}-tfstate-${local.suffix}"
  github_sa_account_id    = "github-actions-sa-${local.suffix}"
  runtime_sa_account_id   = "functions-runtime-sa-${local.suffix}"
  workflows_sa_account_id = "workflow-runner-sa-${local.suffix}"
  wif_pool_id             = "github-actions-pool-${local.suffix}"
  wif_provider_id         = "github-provider-${local.suffix}"
}

data "google_project" "current" {
  project_id = var.project_id
}

# Firestore データベース作成前に API を有効化する。
# すでに有効な場合は no-op。
resource "google_project_service" "firestore_api" {
  project            = var.project_id
  service            = "firestore.googleapis.com"
  disable_on_destroy = false
}

#
# 1. Terraform state bucket
#
resource "google_storage_bucket" "tfstate" {
  name = local.tfstate_bucket_name
  # 例: ASIA-NORTHEAST1 / US など。backend と同じリージョン設計を推奨。
  location                    = var.tfstate_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  # tfstate バケット誤削除防止。destroy 時もバケットは残す。
  force_destroy = false

  versioning {
    enabled = true
  }
}

#
# 2. Service accounts
#
resource "google_service_account" "github_sa" {
  account_id   = local.github_sa_account_id
  display_name = "GitHub Actions Service Account (${local.suffix})"
}

resource "google_service_account" "functions_runtime_sa" {
  account_id   = local.runtime_sa_account_id
  display_name = "Cloud Functions Runtime Service Account (${local.suffix})"
}

resource "google_service_account" "workflow_runner_sa" {
  account_id   = local.workflows_sa_account_id
  display_name = "Workflows Runner Service Account (${local.suffix})"
}

#
# 3. GitHub Actions SA roles
#    roles/editor は避け、用途別に分解
#
resource "google_project_iam_member" "github_sa_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_cloudfunctions_admin" {
  project = var.project_id
  role    = "roles/cloudfunctions.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_eventarc_admin" {
  project = var.project_id
  role    = "roles/eventarc.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_pubsub_admin" {
  project = var.project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_artifactregistry_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_documentai_editor" {
  # infra で google_document_ai_processor を作成/参照/更新するために必要。
  project = var.project_id
  role    = "roles/documentai.editor"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_serviceusage_consumer" {
  project = var.project_id
  # GitHub Actions から API 呼び出し時の quota 消費に必要。
  role   = "roles/serviceusage.serviceUsageConsumer"
  member = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_serviceusage_admin" {
  # infra/apis.tf で google_project_service.required を適用するために必要。
  # (serviceusage.services.enable 権限)
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageAdmin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_iam_service_account_user" {
  project = var.project_id
  # デプロイ時に target SA を指定して Cloud Functions / Run を作成するために必要。
  role   = "roles/iam.serviceAccountUser"
  member = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_workflows_admin" {
  project = var.project_id
  role    = "roles/workflows.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

#
# 4. Functions runtime SA roles
#
resource "google_project_iam_member" "functions_runtime_sa_documentai_api_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

resource "google_project_iam_member" "functions_runtime_sa_eventarc_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

resource "google_project_iam_member" "functions_runtime_sa_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

resource "google_project_iam_member" "functions_runtime_sa_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

resource "google_project_iam_member" "functions_runtime_sa_workflows_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

resource "google_project_iam_member" "functions_runtime_sa_aiplatform_user" {
  project = var.project_id
  # Gemini 呼び出し（aiplatform.endpoints.predict）に必要。
  role   = "roles/aiplatform.user"
  member = "serviceAccount:${google_service_account.functions_runtime_sa.email}"
}

#
# 5. Workflow runner SA roles
#
resource "google_project_iam_member" "workflow_runner_sa_documentai_api_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.workflow_runner_sa.email}"
}

resource "google_project_iam_member" "workflow_runner_sa_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.workflow_runner_sa.email}"
}

resource "google_project_iam_member" "workflow_runner_sa_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.workflow_runner_sa.email}"
}

#
# 6. Workload Identity Federation
#
resource "google_iam_workload_identity_pool" "pool" {
  workload_identity_pool_id = local.wif_pool_id
  display_name              = "GitHub Actions Pool (${local.suffix})"
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = local.wif_provider_id
  display_name                       = "GitHub Provider (${local.suffix})"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  # 連携先 GitHub リポジトリを固定（最重要）。
  # フォークや別repoからのトークンを拒否するための境界。
  attribute_condition = "assertion.repository == '${var.github_repository}'"
}

resource "google_service_account_iam_member" "wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}

#
# 7. Firestore (optional, but recommended for deep-book-ocr job store)
#
resource "google_firestore_database" "default" {
  # 既存 Firestore があるプロジェクトでは二重作成を避けるため false 推奨。
  # 新規環境でジョブ管理を行う場合のみ true にする。
  count   = var.enable_firestore ? 1 : 0
  project = var.project_id
  name    = "(default)"
  # Firestore は作成後リージョン変更不可のため、最初に固定しておく。
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.firestore_api]
}
