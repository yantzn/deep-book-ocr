variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

variable "github_owner" {
  description = "GitHub owner/org (e.g. yantzn)"
  type        = string
}

variable "github_repo" {
  description = "GitHub repo name (e.g. deep-book-ocr)"
  type        = string
}

variable "wif_pool_id" {
  description = "Workload Identity Pool ID"
  type        = string
  default     = "github-pool"
}

variable "wif_provider_id" {
  description = "Workload Identity Provider ID"
  type        = string
  default     = "github-provider"
}

variable "service_account_id" {
  description = "Service Account ID for GitHub Actions"
  type        = string
  default     = "github-sa"
}

variable "service_account_display_name" {
  description = "Service Account display name"
  type        = string
  default     = "GitHub Actions (WIF) Service Account"
}
