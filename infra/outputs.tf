output "input_bucket_name" {
  value = google_storage_bucket.buckets["input"].name
}

output "temp_bucket_name" {
  value = google_storage_bucket.buckets["temp"].name
}

output "output_bucket_name" {
  value = google_storage_bucket.buckets["output"].name
}

output "source_bucket_name" {
  value = google_storage_bucket.buckets["source"].name
}

output "documentai_processor_name" {
  value = google_document_ai_processor.ocr.name
}

output "documentai_processor_id" {
  value = element(split("/", google_document_ai_processor.ocr.name), length(split("/", google_document_ai_processor.ocr.name)) - 1)
}

output "ocr_trigger_function_uri" {
  value = google_cloudfunctions2_function.ocr_trigger.service_config[0].uri
}

output "md_generator_function_uri" {
  value = google_cloudfunctions2_function.md_generator.service_config[0].uri
}

output "workflow_name" {
  value = google_workflows_workflow.docai_monitor.name
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.gcf_artifacts.repository_id
}

output "bucket_suffix" {
  value = local.suffix
}
