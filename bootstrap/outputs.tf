output "wif_provider_name" {
  value = google_iam_workload_identity_pool_provider.provider.name
}

output "github_actions_service_account" {
  value = google_service_account.github_sa.email
}
