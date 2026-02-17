variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  description = "Default region"
  default     = "asia-northeast1"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in owner/repo format"
}
