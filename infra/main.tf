data "google_project" "current" {
  # Document AI サービスエージェントの導出に project number が必要。
  project_id = var.project_id
}

resource "random_id" "bucket_suffix" {
  # バケット名衝突を避けるための短いランダムsuffix。
  byte_length = 3

  keepers = {
    project = var.project_id
    region  = var.region
  }
}

locals {
  # 本モジュールで共通利用する命名規約・principal文字列を集約する。
  suffix = random_id.bucket_suffix.hex

  input_bucket_name  = "${var.project_id}-input-${local.suffix}"
  temp_bucket_name   = "${var.project_id}-temp-${local.suffix}"
  output_bucket_name = "${var.project_id}-output-${local.suffix}"
  source_bucket_name = var.source_bucket_name != "" ? var.source_bucket_name : "${var.project_id}-source-${local.suffix}"

  artifact_registry_repository_id = "gcf-artifacts"

  ocr_trigger_source_object  = "functions/${var.ocr_trigger_function_name}/function-source.zip"
  md_generator_source_object = "functions/${var.md_generator_function_name}/function-source.zip"

  documentai_service_agent_email = "service-${data.google_project.current.number}@gcp-sa-prod-dai-core.iam.gserviceaccount.com"

  runtime_sa_member  = "serviceAccount:${var.functions_runtime_service_account_email}"
  workflow_sa_member = "serviceAccount:${var.workflow_runner_service_account_email}"

  github_actions_service_account_resource = "projects/${var.project_id}/serviceAccounts/${var.github_actions_service_account_email}"

  # md-generator を Pub/Sub で非同期起動するためのトピック名。
  md_generator_topic_name = "${var.project_id}-md-generator-jobs-${local.suffix}"
}

#
# Buckets
#
resource "google_storage_bucket" "buckets" {
  # input/temp/output/source を同一定義でまとめて作成する。
  for_each = {
    input  = local.input_bucket_name
    temp   = local.temp_bucket_name
    output = local.output_bucket_name
    source = local.source_bucket_name
  }

  name     = each.value
  location = var.bucket_location

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.required]
}

#
# Artifact Registry for Gen2 build artifacts
#
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.artifact_registry_location
  repository_id = local.artifact_registry_repository_id
  description   = "Artifacts for Cloud Functions Gen2"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

#
# Optional Firestore database creation
#
resource "google_firestore_database" "default" {
  count = var.create_firestore_database ? 1 : 0

  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required]
}

#
# Document AI processor
#
resource "google_document_ai_processor" "ocr" {
  location     = var.documentai_location
  display_name = var.documentai_processor_display_name
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.required]
}

#
# Source archives and objects (functions ディレクトリから毎回生成)
#
data "archive_file" "ocr_trigger_source_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/ocr_trigger"
  output_path = "${path.module}/.terraform/ocr-trigger-source.zip"

  excludes = [
    ".env",
    ".venv/**",
    "__pycache__/**",
    "tests/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "*.pyc",
  ]
}

data "archive_file" "md_generator_source_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/md_generator"
  output_path = "${path.module}/.terraform/md-generator-source.zip"

  excludes = [
    ".env",
    ".venv/**",
    "__pycache__/**",
    "tests/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "*.pyc",
  ]
}

resource "google_storage_bucket_object" "ocr_trigger_source" {
  # Functions Gen2 build_config.source で参照される ZIP オブジェクト。
  name         = local.ocr_trigger_source_object
  bucket       = google_storage_bucket.buckets["source"].name
  source       = data.archive_file.ocr_trigger_source_zip.output_path
  content_type = "application/zip"
}

resource "google_storage_bucket_object" "md_generator_source" {
  # Functions Gen2 build_config.source で参照される ZIP オブジェクト。
  name         = local.md_generator_source_object
  bucket       = google_storage_bucket.buckets["source"].name
  source       = data.archive_file.md_generator_source_zip.output_path
  content_type = "application/zip"
}

#
# IAM for runtime service account on buckets
#
resource "google_storage_bucket_iam_member" "runtime_input_viewer" {
  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectViewer"
  member = local.runtime_sa_member
}

resource "google_storage_bucket_iam_member" "runtime_temp_viewer" {
  # md-generator が temp 配下JSONを読み取り・削除できるよう objectUser を付与する。
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectUser"
  member = local.runtime_sa_member
}

resource "google_storage_bucket_iam_member" "runtime_output_admin" {
  bucket = google_storage_bucket.buckets["output"].name
  role   = "roles/storage.objectAdmin"
  member = local.runtime_sa_member
}

resource "google_secret_manager_secret_iam_member" "runtime_gemini_api_key_accessor" {
  # md-generator 実行SAが Secret Manager の GEMINI_API_KEY を参照するための権限。
  project   = var.project_id
  secret_id = var.gemini_api_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.runtime_sa_member

  depends_on = [google_project_service.required]
}

#
# IAM for workflow SA on buckets
#
resource "google_storage_bucket_iam_member" "workflow_temp_viewer" {
  # Workflow が temp 配下の JSON 一覧を取得するための参照権限。
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectViewer"
  member = local.workflow_sa_member
}

resource "google_storage_bucket_iam_member" "workflow_temp_object_user" {
  # Workflow が temp 配下 JSON を削除するための更新権限。
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectUser"
  member = local.workflow_sa_member
}

resource "google_storage_bucket_iam_member" "workflow_input_object_user" {
  # Workflow が入力PDFを削除するための更新権限。
  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectUser"
  member = local.workflow_sa_member
}

resource "google_storage_bucket_iam_member" "workflow_output_admin" {
  bucket = google_storage_bucket.buckets["output"].name
  role   = "roles/storage.objectAdmin"
  member = local.workflow_sa_member
}

#
# IAM for Document AI service agent
# input read / temp write
#
resource "google_storage_bucket_iam_member" "docai_input_viewer" {
  bucket = google_storage_bucket.buckets["input"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.documentai_service_agent_email}"
}

resource "google_storage_bucket_iam_member" "docai_temp_creator" {
  # Document AI は OCR 結果JSONを temp バケットに書き込む。
  bucket = google_storage_bucket.buckets["temp"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${local.documentai_service_agent_email}"
}

#
# Markdown generator function
#
resource "google_cloudfunctions2_function" "md_generator" {
  # Workflows が投入した Pub/Sub メッセージを処理し、Markdownを生成するConsumer。
  name     = var.md_generator_function_name
  location = var.region

  build_config {
    runtime         = "python311"
    entry_point     = "generate_markdown"
    service_account = local.github_actions_service_account_resource

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.md_generator_source.name
      }
    }
  }

  service_config {
    available_memory                 = var.md_generator_available_memory
    timeout_seconds                  = var.md_generator_timeout_seconds
    max_instance_count               = var.md_generator_max_instance_count
    min_instance_count               = var.md_generator_min_instance_count
    max_instance_request_concurrency = var.md_generator_max_instance_request_concurrency
    # Pub/Sub trigger のため公開HTTP受信は不要。内部到達のみに制限する。
    ingress_settings      = "ALLOW_INTERNAL_ONLY"
    service_account_email = var.functions_runtime_service_account_email

    environment_variables = {
      # 生成処理に必要な入出力バケットとジョブ管理情報。
      APP_ENV                   = "gcp"
      GCP_PROJECT_ID            = var.project_id
      TEMP_BUCKET               = google_storage_bucket.buckets["temp"].name
      OUTPUT_BUCKET             = google_storage_bucket.buckets["output"].name
      FIRESTORE_JOBS_COLLECTION = var.firestore_jobs_collection

      GEMINI_MODEL_NAME           = var.gemini_model_name
      ENABLE_GEMINI_POLISH        = tostring(var.enable_gemini_polish)
      GEMINI_MAX_INPUT_CHARS      = tostring(var.gemini_max_input_chars)
      GEMINI_CONNECT_TIMEOUT_SEC  = tostring(var.gemini_connect_timeout_sec)
      GEMINI_READ_TIMEOUT_SEC     = tostring(var.gemini_read_timeout_sec)
      GEMINI_REQUEST_MAX_ATTEMPTS = tostring(var.gemini_request_max_attempts)
      GEMINI_RETRY_BASE_SLEEP_SEC = tostring(var.gemini_retry_base_sleep_sec)

      GCS_DOWNLOAD_TIMEOUT_SEC    = tostring(var.gcs_download_timeout_sec)
      GCS_UPLOAD_TIMEOUT_SEC      = tostring(var.gcs_upload_timeout_sec)
      GCS_EXISTS_TIMEOUT_SEC      = tostring(var.gcs_exists_timeout_sec)
      GCS_DOWNLOAD_MAX_ATTEMPTS   = tostring(var.gcs_download_max_attempts)
      GCS_DOWNLOAD_BASE_SLEEP_SEC = tostring(var.gcs_download_base_sleep_sec)
      # 並列ダウンロード数は固定値（将来は変数化も可能）。
      GCS_PARALLEL_DOWNLOAD_WORKERS = "8"

      FIRESTORE_TIMEOUT_SEC = tostring(var.md_firestore_timeout_sec)
      LOG_EXECUTION_ID      = "true"
      LOG_LEVEL             = "INFO"
    }

    secret_environment_variables {
      key        = "GEMINI_API_KEY"
      project_id = var.project_id
      secret     = var.gemini_api_secret_id
      version    = "latest"
    }
  }

  event_trigger {
    # Workflow は直接HTTP呼び出しせず、Pub/Subへ投入して非同期実行する。
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.md_generator_jobs.id
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = var.functions_runtime_service_account_email
  }

  depends_on = [
    google_project_service.required,
    google_pubsub_topic.md_generator_jobs,
    google_secret_manager_secret_iam_member.runtime_gemini_api_key_accessor,
    google_storage_bucket_iam_member.runtime_temp_viewer,
    google_storage_bucket_iam_member.runtime_output_admin,
    google_storage_bucket_object.md_generator_source,
  ]

  lifecycle {
    replace_triggered_by = [terraform_data.md_generator_http_migration]
  }
}

# Workflows API 有効化後、初回作成ではサービスエージェントが未生成のままになることがあるため
# 先に service identity を明示的に作成してから Workflow 本体を作る。
resource "google_project_service_identity" "workflows_service_agent" {
  provider = google-beta
  project  = var.project_id
  service  = "workflows.googleapis.com"

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "md_generator_jobs" {
  # docai-monitor -> md-generator の疎結合連携に使う中継トピック。
  name       = local.md_generator_topic_name
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic_iam_member" "workflow_md_generator_publisher" {
  # Workflow 実行SAに publish 権限のみ付与（最小権限）。
  project = var.project_id
  topic   = google_pubsub_topic.md_generator_jobs.name
  role    = "roles/pubsub.publisher"
  member  = local.workflow_sa_member
}

#
# Workflows definition
#
resource "google_workflows_workflow" "docai_monitor" {
  name            = var.workflow_name
  region          = var.region
  service_account = var.workflow_runner_service_account_email
  description     = "Monitor Document AI batch LRO and trigger markdown generation"

  source_contents = templatefile("${path.module}/workflows/docai_monitor.yaml", {
    # Terraformで確定した実リソース名をWorkflow定義へ注入する。
    project_id         = var.project_id
    temp_bucket_name   = google_storage_bucket.buckets["temp"].name
    jobs_collection    = var.firestore_jobs_collection
    md_generator_topic = google_pubsub_topic.md_generator_jobs.id
  })

  depends_on = [
    google_project_service.required,
    google_project_service_identity.workflows_service_agent,
    google_cloudfunctions2_function.md_generator,
    google_pubsub_topic_iam_member.workflow_md_generator_publisher,
  ]
}

# md-generator を過去構成から安全に切り替えるための one-time trigger
resource "terraform_data" "md_generator_http_migration" {
  # lifecycle.replace_triggered_by 用のダミーリソース。
  # HTTP -> Pub/Sub トリガー移行は in-place update 不可のため、
  # 値を更新して md-generator を明示的に再作成させる。
  input = "v3"
}

#
# OCR trigger function
#
resource "google_cloudfunctions2_function" "ocr_trigger" {
  # input バケット finalize イベントを起点に OCR ジョブを起動するProducer。
  name     = var.ocr_trigger_function_name
  location = var.region

  build_config {
    runtime         = "python311"
    entry_point     = "start_ocr"
    service_account = local.github_actions_service_account_resource

    source {
      storage_source {
        bucket = google_storage_bucket.buckets["source"].name
        object = google_storage_bucket_object.ocr_trigger_source.name
      }
    }
  }

  service_config {
    available_memory                 = var.ocr_trigger_available_memory
    timeout_seconds                  = var.ocr_trigger_timeout_seconds
    max_instance_count               = var.ocr_trigger_max_instance_count
    min_instance_count               = var.ocr_trigger_min_instance_count
    max_instance_request_concurrency = var.ocr_trigger_max_instance_request_concurrency
    # Eventarc 経由で呼ばれるため公開到達性は運用方針に応じて調整可能。
    ingress_settings      = "ALLOW_ALL"
    service_account_email = var.functions_runtime_service_account_email

    environment_variables = {
      # Document AI 実行に必要な識別子と Workflow 起動設定。
      APP_ENV                      = "gcp"
      GCP_PROJECT_ID               = var.project_id
      PROCESSOR_ID                 = google_document_ai_processor.ocr.name
      PROCESSOR_LOCATION           = var.documentai_location
      INPUT_BUCKET                 = google_storage_bucket.buckets["input"].name
      TEMP_BUCKET                  = "gs://${google_storage_bucket.buckets["temp"].name}"
      OUTPUT_BUCKET                = google_storage_bucket.buckets["output"].name
      FIRESTORE_JOBS_COLLECTION    = var.firestore_jobs_collection
      DOCAI_MONITOR_WORKFLOW_NAME  = google_workflows_workflow.docai_monitor.name
      WORKFLOW_REGION              = var.region
      DOCAI_SUBMIT_TIMEOUT_SEC     = tostring(var.docai_submit_timeout_sec)
      FIRESTORE_TIMEOUT_SEC        = tostring(var.ocr_firestore_timeout_sec)
      WORKFLOW_EXECUTE_TIMEOUT_SEC = tostring(var.workflow_execute_timeout_sec)
      LOG_EXECUTION_ID             = "true"
      LOG_LEVEL                    = "INFO"
    }
  }

  event_trigger {
    # input バケットへのファイルアップロード(finalized)で起動する。
    event_type            = "google.cloud.storage.object.v1.finalized"
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = var.functions_runtime_service_account_email
    trigger_region        = var.region

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.buckets["input"].name
    }
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.runtime_input_viewer,
    google_storage_bucket_iam_member.docai_input_viewer,
    google_storage_bucket_iam_member.docai_temp_creator,
    google_storage_bucket_object.ocr_trigger_source,
    google_workflows_workflow.docai_monitor,
  ]
}
