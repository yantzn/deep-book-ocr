# Service Usage API は他の enable に必要になるので先に有効化
resource "google_project_service" "serviceusage" {
  project            = var.project_id
  service            = "serviceusage.googleapis.com"
  disable_on_destroy = false
}

locals {
  required_services = toset([
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "eventarc.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "documentai.googleapis.com",
    "aiplatform.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each           = local.required_services
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false

  depends_on = [google_project_service.serviceusage]
}
