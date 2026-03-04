variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "Default region"
  type        = string
  default     = "asia-northeast1"
}

variable "tfstate_location" {
  description = "Location for the tfstate bucket"
  type        = string
  default     = "ASIA-NORTHEAST1"
}

variable "github_repository" {
  description = "GitHub repository in the form owner/repo (e.g. yantzn/deep-book-ocr)"
  type        = string
}

variable "rotation_key" {
  description = "Change this to rotate suffixes (forces new SA/WIF/tfstate bucket)"
  type        = string
  default     = "v1"
}
