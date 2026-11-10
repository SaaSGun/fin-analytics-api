resource "google_bigquery_dataset" "fin_analytics" {
  project    = var.project_id
  dataset_id = "fin_analytics"
  location   = var.region

  # No `access` block on purpose: BigQuery auto-grants default ACLs
  # (projectOwners/Writers/Readers + the creating user's own OWNER grant)
  # on dataset creation. Declaring `access` here would make Terraform
  # authoritative over it and risk removing those on the next apply.
  delete_contents_on_destroy = false
}
