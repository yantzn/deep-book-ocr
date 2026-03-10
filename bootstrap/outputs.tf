# bootstrap モジュールの主要出力値。
# CI/CD 設定や infra/backend 初期化時に参照する想定。

output "tfstate_bucket_name" {
  # infra 側 backend の bucket に指定する値。
  description = "Terraform backend bucket name"
  value       = google_storage_bucket.tfstate.name
}

output "github_actions_service_account_email" {
  # GitHub Actions の認証先 SA（WIF 経由）として使用。
  description = "GitHub Actions deployment service account email"
  value       = google_service_account.github_sa.email
}

output "functions_runtime_service_account_email" {
  # Cloud Functions/Run 実行時の principal。
  # バケット権限や API 呼び出し権限の付与対象になる。
  description = "Cloud Functions runtime service account email"
  value       = google_service_account.functions_runtime_sa.email
}

output "workflow_runner_service_account_email" {
  # Workflows 実行主体として使う SA。
  description = "Workflows runner service account email"
  value       = google_service_account.workflow_runner_sa.email
}

output "workload_identity_provider_name" {
  # GitHub Secrets の WIF_PROVIDER に設定する値（フルリソース名）。
  description = "Full Workload Identity Provider resource name"
  value       = google_iam_workload_identity_pool_provider.provider.name
}

output "workload_identity_pool_name" {
  # WIF Pool のフル名。トラブルシュート時の参照用にも有用。
  description = "Full Workload Identity Pool resource name"
  value       = google_iam_workload_identity_pool.pool.name
}

output "bootstrap_suffix" {
  # 命名に使っている suffix。どの世代のリソースか識別するための値。
  description = "Generated suffix used across bootstrap resources"
  value       = random_id.suffix.hex
}
