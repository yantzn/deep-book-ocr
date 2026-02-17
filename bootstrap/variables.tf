variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-northeast1"
}

variable "github_repo" {
  type        = string
  description = "owner/repo 形式（例: yantzn/deep-book-ocr）"
}

variable "service_account_id" {
  type    = string
  default = "github-actions-sa"
}
