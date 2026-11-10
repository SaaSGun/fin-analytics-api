# APIs this stack deliberately depends on. The project shows several more
# enabled (pubsub, dataplex, sql-component, ...) that are incidental
# defaults pulled in by BigQuery/Cloud Build — not something this config
# owns, so they're left unmanaged on purpose.
locals {
  apis = [
    "iam.googleapis.com",
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
  ]
}

resource "google_project_service" "this" {
  for_each = toset(local.apis)

  project = var.project_id
  service = each.value

  # Enabling an already-enabled API is a no-op, so this resource doesn't
  # strictly need importing. Never disable a shared project's API as a
  # side effect of `terraform destroy` against this config.
  disable_on_destroy = false
}
