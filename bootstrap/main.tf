provider "google" {
  project = var.project_id
  region  = var.region
}

# API enable だけを担当（bootstrap state）
resource "google_project_service" "required" {
  for_each = toset([
    # IaCでIAM操作するための土台
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com",

    # 本プロジェクト構成
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

output "enabled_services_count" {
  value = length(google_project_service.required)
}
