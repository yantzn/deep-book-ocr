variable "project_id" {
  description = "GCP project id"
  type        = string
}

variable "region" {
  description = "Primary region for Cloud Functions / Workflows / buckets"
  type        = string
  default     = "asia-northeast1"
}

variable "bucket_location" {
  description = "Bucket location"
  type        = string
  default     = "asia-northeast1"
}

variable "artifact_registry_location" {
  description = "Artifact Registry location"
  type        = string
  default     = "asia-northeast1"
}

variable "documentai_location" {
  description = "Document AI processor location"
  type        = string
  default     = "us"
}

variable "documentai_processor_display_name" {
  description = "Display name for Document AI processor"
  type        = string
  default     = "deep-book-ocr-processor"
}

variable "github_actions_service_account_email" {
  description = "Bootstrap-created GitHub Actions deployment service account"
  type        = string
}

variable "functions_runtime_service_account_email" {
  description = "Bootstrap-created Cloud Functions runtime service account"
  type        = string
}

variable "workflow_runner_service_account_email" {
  description = "Bootstrap-created Workflows runner service account"
  type        = string
}

variable "source_bucket_name" {
  description = "Optional pre-existing source bucket name. Leave empty to create one."
  type        = string
  default     = ""
}

variable "firestore_jobs_collection" {
  description = "Firestore collection name for OCR jobs"
  type        = string
  default     = "ocr_jobs"
}

variable "workflow_name" {
  description = "Workflow name"
  type        = string
  default     = "docai-monitor"
}

variable "ocr_trigger_function_name" {
  description = "Cloud Function name for OCR trigger"
  type        = string
  default     = "ocr-trigger"
}

variable "md_generator_function_name" {
  description = "Cloud Function name for markdown generator"
  type        = string
  default     = "md-generator"
}

variable "ocr_trigger_timeout_seconds" {
  description = "Timeout for ocr-trigger"
  type        = number
  default     = 300
}

variable "md_generator_timeout_seconds" {
  description = "Timeout for md-generator"
  type        = number
  default     = 540
}

variable "ocr_trigger_available_memory" {
  description = "Memory for ocr-trigger"
  type        = string
  default     = "512M"
}

variable "md_generator_available_memory" {
  description = "Memory for md-generator"
  type        = string
  default     = "1Gi"
}

variable "ocr_trigger_max_instance_count" {
  description = "Max instances for ocr-trigger"
  type        = number
  default     = 30
}

variable "md_generator_max_instance_count" {
  description = "Max instances for md-generator"
  type        = number
  default     = 10
}

variable "ocr_trigger_min_instance_count" {
  description = "Min instances for ocr-trigger"
  type        = number
  default     = 1
}

variable "md_generator_min_instance_count" {
  description = "Min instances for md-generator"
  type        = number
  default     = 1
}

variable "ocr_trigger_max_instance_request_concurrency" {
  description = "Max request concurrency for ocr-trigger"
  type        = number
  default     = 1
}

variable "md_generator_max_instance_request_concurrency" {
  description = "Max request concurrency for md-generator"
  type        = number
  default     = 1
}

variable "docai_submit_timeout_sec" {
  description = "Timeout for batch_process_documents submit call"
  type        = number
  default     = 60
}

variable "ocr_firestore_timeout_sec" {
  description = "Firestore timeout for ocr-trigger in seconds"
  type        = number
  default     = 20
}

variable "workflow_execute_timeout_sec" {
  description = "Workflows create_execution timeout for ocr-trigger in seconds"
  type        = number
  default     = 20
}

variable "gemini_model_name" {
  description = "Gemini model name for markdown polishing"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "gemini_api_secret_id" {
  description = "Secret Manager secret id for md-generator Gemini API key"
  type        = string
  default     = "gemini-api-key"
}

variable "enable_gemini_polish" {
  description = "Whether md-generator applies Gemini polish step"
  type        = bool
  default     = true
}

variable "gemini_max_input_chars" {
  description = "Max input characters per Gemini chunk request"
  type        = number
  default     = 120000
}

variable "gemini_timeout_sec" {
  description = "Gemini request timeout in seconds"
  type        = number
  default     = 60
}

variable "gemini_connect_timeout_sec" {
  description = "Gemini API connect timeout in seconds"
  type        = number
  default     = 10
}

variable "gemini_read_timeout_sec" {
  description = "Gemini API read timeout in seconds"
  type        = number
  default     = 60
}

variable "gemini_request_max_attempts" {
  description = "Max retry attempts for Gemini API requests"
  type        = number
  default     = 2
}

variable "gemini_retry_base_sleep_sec" {
  description = "Base backoff seconds for Gemini API retries"
  type        = number
  default     = 1
}

variable "gcs_download_timeout_sec" {
  description = "GCS download timeout for md-generator in seconds"
  type        = number
  default     = 30
}

variable "gcs_upload_timeout_sec" {
  description = "GCS upload timeout for md-generator in seconds"
  type        = number
  default     = 30
}

variable "gcs_exists_timeout_sec" {
  description = "GCS object exists timeout for md-generator in seconds"
  type        = number
  default     = 10
}

variable "gcs_download_max_attempts" {
  description = "Max retry attempts for md-generator JSON downloads"
  type        = number
  default     = 3
}

variable "gcs_download_base_sleep_sec" {
  description = "Base sleep seconds for md-generator download retry backoff"
  type        = number
  default     = 1
}

variable "md_firestore_timeout_sec" {
  description = "Firestore timeout for md-generator in seconds"
  type        = number
  default     = 20
}

variable "create_firestore_database" {
  description = "Whether to create Firestore database from infra too"
  type        = bool
  default     = false
}
