project_id                 = "deep-book-ocr"
region                     = "asia-northeast1"
bucket_location            = "asia-northeast1"
artifact_registry_location = "asia-northeast1"

documentai_location               = "us"
gcp_location                      = "us-central1"
documentai_processor_display_name = "deep-book-ocr-processor"

github_actions_service_account_email    = "github-actions-sa-0488@deep-book-ocr.iam.gserviceaccount.com"
functions_runtime_service_account_email = "functions-runtime-sa-0488@deep-book-ocr.iam.gserviceaccount.com"
workflow_runner_service_account_email   = "workflow-runner-sa-0488@deep-book-ocr.iam.gserviceaccount.com"

source_bucket_name         = ""
firestore_jobs_collection  = "ocr_jobs"
workflow_name              = "docai-monitor"
ocr_trigger_function_name  = "ocr-trigger"
md_generator_function_name = "md-generator"

ocr_trigger_timeout_seconds  = 300
md_generator_timeout_seconds = 540

ocr_trigger_available_memory  = "512M"
md_generator_available_memory = "1Gi"

ocr_trigger_max_instance_count  = 30
md_generator_max_instance_count = 10

ocr_trigger_min_instance_count  = 1
md_generator_min_instance_count = 1

ocr_trigger_max_instance_request_concurrency  = 1
md_generator_max_instance_request_concurrency = 1

docai_submit_timeout_sec = 60
gemini_model_name        = "gemini-1.5-pro"

create_firestore_database = false
