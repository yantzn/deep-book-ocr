output "input_bucket_name" {
  description = "Input bucket name for uploaded PDFs"
  value       = google_storage_bucket.buckets["input"].name
}

output "temp_bucket_name" {
  description = "Temporary bucket name for Document AI JSON output"
  value       = google_storage_bucket.buckets["temp"].name
}

output "output_bucket_name" {
  description = "Output bucket name for generated Markdown files"
  value       = google_storage_bucket.buckets["output"].name
}

output "source_bucket_name" {
  description = "Source bucket name for Cloud Functions source ZIPs"
  value       = google_storage_bucket.buckets["source"].name
}

output "documentai_processor_name" {
  description = "Full resource name of the Document AI OCR processor"
  value       = google_document_ai_processor.ocr.name
}

output "documentai_processor_id" {
  description = "Short ID of the Document AI OCR processor"
  value = element(
    split("/", google_document_ai_processor.ocr.name),
    length(split("/", google_document_ai_processor.ocr.name)) - 1
  )
}

output "documentai_service_agent_email" {
  description = "Document AI service agent email"
  value       = local.documentai_service_agent_email
}

output "ocr_trigger_function_name" {
  description = "Name of the OCR trigger Cloud Function"
  value       = google_cloudfunctions2_function.ocr_trigger.name
}

output "ocr_trigger_function_uri" {
  description = "HTTP URI of the OCR trigger Cloud Function"
  value       = google_cloudfunctions2_function.ocr_trigger.service_config[0].uri
}

output "md_generator_function_name" {
  description = "Name of the Markdown generator Cloud Function"
  value       = google_cloudfunctions2_function.md_generator.name
}

output "md_generator_function_uri" {
  description = "HTTP URI of the Markdown generator Cloud Function"
  value       = google_cloudfunctions2_function.md_generator.service_config[0].uri
}

output "md_generator_audience" {
  description = "OIDC audience used by Workflows when invoking md-generator"
  value       = google_cloudfunctions2_function.md_generator.service_config[0].uri
}

output "workflow_name" {
  description = "Workflows name for Document AI monitoring"
  value       = google_workflows_workflow.docai_monitor.name
}

output "workflow_region" {
  description = "Workflows region"
  value       = var.region
}

output "firestore_jobs_collection" {
  description = "Firestore collection name used for OCR job tracking"
  value       = var.firestore_jobs_collection
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository ID for Cloud Functions Gen2 builds"
  value       = google_artifact_registry_repository.gcf_artifacts.repository_id
}

output "artifact_registry_location" {
  description = "Artifact Registry location"
  value       = var.artifact_registry_location
}

output "bucket_suffix" {
  description = "Random suffix appended to bucket names"
  value       = local.suffix
}

output "functions_runtime_service_account_email" {
  description = "Runtime service account email used by Cloud Functions"
  value       = var.functions_runtime_service_account_email
}

output "workflow_runner_service_account_email" {
  description = "Runner service account email used by Workflows"
  value       = var.workflow_runner_service_account_email
}

output "github_actions_service_account_email" {
  description = "GitHub Actions deployment service account email"
  value       = var.github_actions_service_account_email
}
