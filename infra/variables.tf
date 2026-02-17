variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-northeast1"
}

variable "bucket_rotation_key" {
  # これを変えると suffix が変わって “新バケット” になる
  # 例: "v1" → "v2"
  type    = string
  default = "v1"
}

variable "bucket_location" {
  type    = string
  default = "asia-northeast1"
}

variable "documentai_location" {
  type    = string
  default = "us"
}
