variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

# 既存 main.tf が参照しているが、repoの variables.tf に無かったもの
variable "bucket_location" {
  description = "GCS bucket location (region or multi-region). Usually same as region."
  type        = string
  default     = "asia-northeast1"
}

variable "documentai_location" {
  description = "Document AI location (e.g. us, eu)."
  type        = string
  default     = "us"
}

variable "bucket_rotation_key" {
  description = "Change this value to rotate (recreate) buckets with a new random suffix."
  type        = string
  default     = "v1"
}

variable "functions_service_account_email" {
  description = "Service account email used by Cloud Functions runtime/build/trigger."
  type        = string
}

variable "enable_documentai_bucket_iam" {
  description = "true のとき、infra作成時に input/temp バケットへ Document AI SA の IAM を付与"
  type        = bool
  default     = true
}

variable "documentai_service_agent_email_override" {
  description = "Document AI サービスエージェントの手動指定値。空なら project_id から自動算出した値を使用"
  type        = string
  default     = ""
}
