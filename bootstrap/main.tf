resource "random_id" "suffix" {
  byte_length = 2
}

locals {
  suffix          = random_id.suffix.hex
  wif_pool_id     = "github-actions-pool-${local.suffix}"
  wif_provider_id = "github-provider-${local.suffix}"
}

resource "google_service_account" "github_sa" {
  account_id   = var.service_account_id
  display_name = "GitHub Actions Service Account"
}

resource "google_iam_workload_identity_pool" "pool" {
  project                   = var.project_id
  workload_identity_pool_id = local.wif_pool_id
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = local.wif_provider_id
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

  # ここで “このrepoだけ” を許可
  attribute_condition = "assertion.repository == '${var.github_repo}'"
}

# GitHub OIDC からこのSAを使えるようにする
resource "google_service_account_iam_member" "wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repo}"
}

# （必要に応じて）Terraform実行に必要な権限：一旦Editor（あとで絞る）
resource "google_project_iam_member" "github_sa_editor" {
  project = var.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}
