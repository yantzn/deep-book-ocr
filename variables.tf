variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

# GitHub repository (owner/name)
variable "github_repository" {
  description = "GitHub repository in the form 'owner/repo' used for Workload Identity Federation condition"
  type        = string
  default     = "yantzn/deep-book-ocr"
}
