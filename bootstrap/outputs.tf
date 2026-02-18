output "tfstate_bucket_name" {
  value = google_storage_bucket.tfstate.name
}

output "github_actions_service_account" {
  value = google_service_account.github_sa.email
}

output "wif_provider_name" {
  # GitHub Actions の secrets.WIF_PROVIDER に入れる値
  value = google_iam_workload_identity_pool_provider.provider.name
}

output "wif_pool_name" {
  value = google_iam_workload_identity_pool.pool.name
}
