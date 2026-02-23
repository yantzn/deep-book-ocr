# ============================
# プロジェクト/リージョン基本設定
# ============================
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

# Cloud Functions/Artifact Registry 用リージョンと合わせるのが基本
# （マルチリージョンを使う場合のみ個別調整）
variable "bucket_location" {
  description = "GCS bucket location (region or multi-region). Usually same as region."
  type        = string
  default     = "asia-northeast1"
}

# Document AI Processor の配置リージョン
# 例: us / eu（documentai APIの提供リージョンに合わせる）
variable "documentai_location" {
  description = "Document AI location (e.g. us, eu)."
  type        = string
  default     = "us"
}

# 値を変更するとランダムサフィックスが再生成され、バケット名がローテーションされる
# 既存バケットを作り直したいときにのみ変更する
variable "bucket_rotation_key" {
  description = "Change this value to rotate (recreate) buckets with a new random suffix."
  type        = string
  default     = "v1"
}

# Cloud Functions の実行/ビルド/トリガーで利用する SA
# 通常は bootstrap などで作成した SA の email を指定
variable "functions_service_account_email" {
  description = "Service account email used by Cloud Functions runtime/build/trigger."
  type        = string
}

# ============================
# Document AI バケット IAM 制御
# ============================
# true の場合、Document AI SA に以下を付与:
# - input バケット: roles/storage.objectViewer
# - temp  バケット: roles/storage.objectCreator
variable "enable_documentai_bucket_iam" {
  description = "true のとき、infra作成時に input/temp バケットへ Document AI SA の IAM を付与"
  type        = bool
  default     = true
}

# Document AI SA を手動で 1 つ指定したい場合に使用
# 空文字のときは project number から既定アドレスを自動算出
variable "documentai_service_agent_email_override" {
  description = "Document AI サービスエージェントの手動指定値。空なら project_id から自動算出した値を使用"
  type        = string
  default     = ""
}

# 自動算出/override に加えて、追加でIAM付与したい SA 一覧
# 移行期間などで複数 SA を許可したいときに利用
variable "documentai_service_agent_emails_additional" {
  description = "自動算出に追加でIAM付与する Document AI サービスエージェント一覧（必要時のみ指定）"
  type        = list(string)
  default     = []
}

# ============================
# 関数に注入するアプリ設定
# ============================
# Cloud Functions の APP_ENV
# ローカルは local、デプロイ環境は gcp を想定
variable "app_env" {
  description = "Application environment string injected into Cloud Functions (e.g., gcp/local)."
  type        = string
  default     = "gcp"
}

# Gemini を呼び出す Vertex AI のロケーション
# md_generator の GCP_LOCATION に注入される
variable "gcp_location" {
  description = "Vertex AI location for Gemini. Often same as region, but Vertex AI supports specific locations."
  type        = string
  default     = "us-central1"
}

# md_generator 用の追加/上書き環境変数
# 例: MODEL_NAME, CHUNK_SIZE, LOG_LEVEL など
variable "md_generator_env" {
  description = "Extra/override env vars for md_generator (merged into environment_variables)."
  type        = map(string)
  default     = {}
}

# ocr_trigger 用の追加/上書き環境変数
# 例: LOG_LEVEL など
variable "ocr_trigger_env" {
  description = "Extra/override env vars for ocr_trigger (merged into environment_variables)."
  type        = map(string)
  default     = {}
}
