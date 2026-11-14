variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "fin-analytics-api"
}

variable "region" {
  description = "Region for the BigQuery dataset and Cloud Run service"
  type        = string
  default     = "europe-west4"
}

variable "github_repo" {
  description = "GitHub repo (owner/name) allowed to assume github-deployer via Workload Identity Federation"
  type        = string
  default     = "SaaSGun/fin-analytics-api"
}

variable "bq_daily_query_cap_gib" {
  description = "BigQuery query volume (GiB billed) the whole project may use per day - the cost ceiling for the public service"
  type        = number
  default     = 200
}
