locals {
  # ランダムsuffix（rotation_keyを変えると新規に切り替わる）
  # → 409 already exists を根本回避
  suffix_keepers = {
    project  = var.project_id
    repo     = var.github_repository
    rotation = var.rotation_key
  }
}

resource "random_id" "suffix" {
  byte_length = 2 # 4 hex
  keepers     = local.suffix_keepers
}

locals {
  suffix = random_id.suffix.hex

  # ---- tfstate bucket ----
  tfstate_bucket_name = "${var.project_id}-tfstate-${local.suffix}"

  # ---- WIF/SA ----
  sa_account_id = "github-actions-sa-${local.suffix}"

  wif_pool_id     = "github-actions-pool-${local.suffix}"
  wif_provider_id = "github-provider-${local.suffix}"
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  # Document AI 管理サービスエージェント
  documentai_service_agent_email = "service-${data.google_project.current.number}@gcp-sa-prod-dai-core.iam.gserviceaccount.com"
}

# -------------------------
# 1) Terraform state bucket (GCS backend 用)
# -------------------------
resource "google_storage_bucket" "tfstate" {
  name          = local.tfstate_bucket_name
  location      = var.tfstate_location
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }

  # bootstrap は基本「消さない」方が安全
  force_destroy = false
}

# -------------------------
# 2) GitHub Actions 用 Service Account
# -------------------------
resource "google_service_account" "github_sa" {
  account_id   = local.sa_account_id
  display_name = "GitHub Actions Service Account (${local.suffix})"
}

# 必要最低限の権限にするのが理想だが、
# まず動かす段階では Editor でもOK（後で絞る）
resource "google_project_iam_member" "github_sa_editor" {
  project = var.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

resource "google_project_iam_member" "github_sa_pubsub_admin" {
  project = var.project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.github_sa.email}"
}

# -------------------------
# 3) Workload Identity Pool / Provider
# -------------------------
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

  # GitHub OIDC の属性マッピング
  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  # このリポジトリだけ許可（最重要）
  attribute_condition = "assertion.repository == '${var.github_repository}'"
}

# SA へ WIF を許可
resource "google_service_account_iam_member" "wif_workload_identity_user" {
  service_account_id = google_service_account.github_sa.name
  role               = "roles/iam.workloadIdentityUser"

  member = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}
