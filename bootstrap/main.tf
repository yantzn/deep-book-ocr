resource "random_id" "suffix" {
  byte_length = 2 # 例: 914e のような4hex
}

locals {
  suffix = random_id.suffix.hex

  workload_identity_pool_id     = "github-actions-pool-${local.suffix}"
  workload_identity_provider_id = "github-provider-${local.suffix}"

  github_actions_sa_account_id = "github-actions-sa" # 固定（ここが409になりやすい）
}

resource "google_service_account" "github_sa" {
  account_id   = local.github_actions_sa_account_id
  display_name = "GitHub Actions Service Account"
}

resource "google_iam_workload_identity_pool" "pool" {
  workload_identity_pool_id = local.workload_identity_pool_id
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = local.workload_identity_provider_id
  display_name                       = "GitHub Provider"

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

  # リポジトリ固定（あなたの repo だけ許可）
  attribute_condition = "assertion.repository == '${var.github_repo}'"
}

# GitHub ActionsからSAを「Workload Identity User」として使う
resource "google_service_account_iam_member" "wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repo}"
}

# 権限（最小化したい場合は roles/editor をやめて細かく付与）
resource "google_project_iam_member" "github_sa_editor" {
  project = var.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}
