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

# Cost ceiling for the public service. Once the project has billed this much
# query volume in a day, BigQuery refuses every further query with
# quotaExceeded until midnight Pacific time (app/main.py turns that into a
# 503). The two heaviest load-test days billed 169 and 184 GiB.
resource "google_service_usage_consumer_quota_override" "bq_daily_query_cap" {
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project")
  override_value = tostring(var.bq_daily_query_cap_gib * 1024) # this quota's unit is MiB
  force          = true                                        # lowering a quota by >10% needs force
}
