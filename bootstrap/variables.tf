# bootstrap モジュールの入力値。
# ここで作るのは「土台」(tfstate / SA / WIF / optional Firestore) で、
# アプリ本体の詳細設定は infra 側で行う想定。

variable "project_id" {
  # すべてのリソース作成先となる GCP プロジェクト。
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  # bootstrap でリージョン依存リソースを作る場合の既定値。
  # 現状は主に整合性のために保持している。
  description = "Default region for bootstrap-created regional resources"
  type        = string
  default     = "asia-northeast1"
}

variable "tfstate_location" {
  # Terraform state バケットのロケーション。
  # backend の設定値と揃える（不一致だと運用が複雑になる）。
  description = "Location for the Terraform state bucket"
  type        = string
  default     = "ASIA-NORTHEAST1"
}

variable "github_repository" {
  # WIF の attribute_condition に使う。
  # 例: owner/repo
  description = "GitHub repository in the form owner/repo"
  type        = string
}

variable "github_repository_owner" {
  # 将来 owner 単位の制御（org 単位制限など）に拡張しやすくするため保持。
  description = "GitHub repository owner or organization"
  type        = string
}

variable "rotation_key" {
  # 値を変えると suffix がローテーションされ、
  # SA / WIF / tfstate バケット名が新規系へ切り替わる。
  # 意図的な再作成時のみ変更する。
  description = "Change this to rotate suffixes (forces new SA/WIF/tfstate bucket)"
  type        = string
  default     = "v1"
}

variable "enable_firestore" {
  # true: Firestore (default DB) を bootstrap で作成。
  # 既に別管理で Firestore が存在する環境では false 推奨。
  description = "Whether to create Firestore Native database in bootstrap"
  type        = bool
  default     = true
}

variable "firestore_location" {
  # Firestore の配置リージョン。作成後は変更不可。
  # データ重力・レイテンシ・災対方針を決めてから固定する。
  description = "Firestore database location"
  type        = string
  default     = "asia-northeast1"
}
