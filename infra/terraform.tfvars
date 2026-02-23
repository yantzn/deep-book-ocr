# バケット名サフィックスのローテーションキー
# 変更するとバケット再作成に繋がるため、通常は固定
bucket_rotation_key = "v1"

# Document AI サービスエージェントへバケットIAMを付与
enable_documentai_bucket_iam = true

# 必要時のみ手動指定（通常は空文字のまま自動算出を使用）
documentai_service_agent_email_override = ""

# 追加でIAM付与したい Document AI サービスエージェント（必要時のみ）
documentai_service_agent_emails_additional = []

# 例：必須（あなたの環境に合わせて設定）
# project_id と functions_service_account_email は環境ごとに必ず確認
# project_id                   = "deep-book-ocr"
# region                       = "asia-northeast1"
# functions_service_account_email = "xxx@deep-book-ocr.iam.gserviceaccount.com"

# Cloud Functions へ注入する共通アプリ設定
app_env      = "gcp"
gcp_location = "us-central1"

# md_generator 固有設定（必要なら有効化）
# 例: MODEL_NAME は利用可能モデル（gemini-2.5-flash など）を指定
# md_generator_env = {
#   MODEL_NAME       = "gemini-2.5-flash"
#   CHUNK_SIZE       = "10"
#   LOG_LEVEL        = "INFO"
# }

# ocr_trigger 固有設定（必要なら有効化）
# ocr_trigger_env = {
#   LOG_LEVEL = "INFO"
# }
