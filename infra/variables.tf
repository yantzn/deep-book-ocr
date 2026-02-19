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
