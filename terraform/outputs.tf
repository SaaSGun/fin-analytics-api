output "cloud_run_url" {
  value = google_cloud_run_v2_service.fin_analytics_api.uri
}

output "fin_api_run_service_account" {
  value = google_service_account.fin_api_run.email
}

output "github_deployer_service_account" {
  value = google_service_account.github_deployer.email
}

output "workload_identity_provider" {
  description = "Should match WIF_PROVIDER in .github/workflows/ci.yml - diff after import to confirm they still agree."
  value       = google_iam_workload_identity_pool_provider.fin_analytics_api.name
}
