# Project-level and SA-level bindings use the additive `_iam_member`
# resource, never the authoritative `_iam_binding`/`_iam_policy` kind.
# This project's IAM policy already has bindings this config doesn't know
# about (e.g. the human owner's roles/owner) — an authoritative resource
# would delete anything not listed here on the next apply.

resource "google_project_iam_member" "fin_api_run_bq_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.fin_api_run.email}"
}

resource "google_project_iam_member" "fin_api_run_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.fin_api_run.email}"
}

resource "google_project_iam_member" "github_deployer_run_source_dev" {
  project = var.project_id
  role    = "roles/run.sourceDeveloper"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "github_deployer_service_usage" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

# github-deployer must be able to run the Cloud Run revision as fin-api-run...
resource "google_service_account_iam_member" "deployer_can_run_as_fin_api_run" {
  service_account_id = google_service_account.fin_api_run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}

# ...and Cloud Build runs the actual build as the default compute SA.
resource "google_service_account_iam_member" "deployer_can_run_as_compute_default" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${data.google_project.this.number}-compute@developer.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}
