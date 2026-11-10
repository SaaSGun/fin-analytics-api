resource "google_service_account" "fin_api_run" {
  project      = var.project_id
  account_id   = "fin-api-run"
  display_name = "Fin Analytics API - Cloud Run runtime SA"
}

resource "google_service_account" "github_deployer" {
  project      = var.project_id
  account_id   = "github-deployer"
  display_name = "GitHub Actions deployer"
}
