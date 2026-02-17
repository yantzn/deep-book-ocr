output "bucket_names" {
  value = { for k, b in google_storage_bucket.buckets : k => b.name }
}

output "ocr_processor_id" {
  value = google_document_ai_processor.ocr_processor.id
}
