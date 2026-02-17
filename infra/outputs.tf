output "bucket_names" {
  value = { for k, b in google_storage_bucket.buckets : k => b.name }
}

output "ocr_processor_id" {
  value = google_document_ai_processor.ocr_processor.id
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
