provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}

# ----------------------------
# 1) GitHub Actions用 Service Account
# ----------------------------
resource "google_service_account" "github_sa" {
  account_id   = var.service_account_id
  display_name = var.service_account_display_name
}

# ----------------------------
# 2) Workload Identity Pool / Provider
# ----------------------------
resource "google_iam_workload_identity_pool" "pool" {
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions Pool"
  description               = "OIDC federation for GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub Provider"
  description                        = "GitHub OIDC provider"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # GitHubのOIDCクレームをGoogleの属性へマッピング
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.actor"      = "assertion.actor"
    "attribute.ref"        = "assertion.ref"
  }

  # このリポジトリからのOIDCだけ許可（重要）
  attribute_condition = "attribute.repository == \"${var.github_owner}/${var.github_repo}\""
}

# ----------------------------
# 3) SAにWIF経由のなりすまし権限を付与
# ----------------------------
resource "google_service_account_iam_binding" "wif_impersonation" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"

  members = [
    "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_owner}/${var.github_repo}"
  ]
}

# ----------------------------
# 4) Terraformが必要とするプロジェクト権限をSAへ付与
#    ※最小権限に寄せるなら後で絞れます。まずは動かす構成。
# ----------------------------
resource "google_project_iam_member" "tf_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "tf_pubsub_admin" {
  project = var.project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "tf_documentai_admin" {
  project = var.project_id
  role    = "roles/documentai.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "tf_artifactregistry_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "tf_service_account_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

# IAMの付与操作もTerraformでやるため（最初はこれが無いと403が出やすい）
resource "google_project_iam_member" "tf_project_iam_admin" {
  project = var.project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

# ----------------------------
# Outputs（GitHub Secretsに入れる値）
# ----------------------------
output "wif_provider" {
  description = "Workload Identity Provider resource name to set as GitHub secret WIF_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.provider.name
}

output "wif_service_account" {
  description = "Service account email to set as GitHub secret WIF_SERVICE_ACCOUNT"
  value       = google_service_account.github_sa.email
}
