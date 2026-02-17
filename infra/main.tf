provider "google" {
  project = var.project_id
  region  = var.region
}

# 変更したい時は bucket_seed を変えるだけで suffix が変わる（=バケット名を作り直せる）
resource "random_id" "bucket_suffix" {
  byte_length = 3 # 6 hex chars
  keepers = {
    seed = var.bucket_seed
  }
}

locals {
  suffix = random_id.bucket_suffix.hex

  buckets = {
    input  = "deep-book-ocr-input-${local.suffix}"
    source = "deep-book-ocr-source-${local.suffix}"
    temp   = "deep-book-ocr-temp-${local.suffix}"
    output = "deep-book-ocr-output-${local.suffix}"
  }
}

resource "google_storage_bucket" "buckets" {
  for_each = local.buckets

  name     = each.value
  location = var.bucket_location

  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# （例）Pub/Sub topic（通知などに使うなら）
resource "google_pubsub_topic" "ocr_events" {
  name = "deep-book-ocr-events-${local.suffix}"
}

output "bucket_names" {
  value = local.buckets
}

output "bucket_suffix" {
  value = local.suffix
}
