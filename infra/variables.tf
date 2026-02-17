variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

variable "bucket_location" {
  description = "GCS bucket location"
  type        = string
  default     = "asia-northeast1"
}

variable "bucket_seed" {
  description = "Change this value to force new random suffix (bucket recreation). e.g. v1, v2, 20260218"
  type        = string
  default     = "v1"
}
