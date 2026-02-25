output "bucket_names" {
  value = { for k, b in google_storage_bucket.buckets : k => b.name }
}

output "ocr_processor_id" {
  value = element(reverse(split("/", google_document_ai_processor.ocr_processor.id)), 0)
}

output "input_bucket" {
  value = google_storage_bucket.buckets["input"].name
}

output "temp_bucket" {
  value = google_storage_bucket.buckets["temp"].name
}

output "output_bucket" {
  value = google_storage_bucket.buckets["output"].name
}

output "source_bucket" {
  value = google_storage_bucket.buckets["source"].name
}

output "documentai_service_agent_emails_effective" {
  value = local.documentai_service_agent_emails_effective
}

output "documentai_bucket_iam_enabled" {
  value = var.enable_documentai_bucket_iam
}
