# Log-based metrics over the app's structured stdout logs (see
# app/observability.py). They appear in Metrics Explorer as
# logging.googleapis.com/user/<name>. They only count log entries written
# after the metric was created, with no backfill.
locals {
  app_log_filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${google_cloud_run_v2_service.fin_analytics_api.name}\"",
    "logName=\"projects/${var.project_id}/logs/run.googleapis.com%2Fstdout\"",
  ])
}

resource "google_logging_metric" "rate_limited_requests" {
  project     = var.project_id
  name        = "fin_api/rate_limited_requests"
  description = "Requests rejected with 429 by the per-client rate limiter (app/rate_limit.py)"
  # httpRequest is lifted from jsonPayload to the top-level LogEntry field.
  filter = "${local.app_log_filter} AND jsonPayload.event=\"request\" AND httpRequest.status=429"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "client_name"
      value_type  = "STRING"
      description = "API client (api_keys.client_name)"
    }
  }

  label_extractors = {
    client_name = "EXTRACT(jsonPayload.client_name)"
  }
}

resource "google_logging_metric" "bigquery_bytes_processed" {
  project     = var.project_id
  name        = "fin_api/bigquery_bytes_processed"
  description = "Bytes processed per BigQuery query (what on-demand pricing bills), by API client"
  filter      = "${local.app_log_filter} AND jsonPayload.event=\"bigquery_query\""

  value_extractor = "EXTRACT(jsonPayload.bytes_processed)"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "By"
    labels {
      key         = "client_name"
      value_type  = "STRING"
      description = "API client (api_keys.client_name)"
    }
  }

  label_extractors = {
    client_name = "EXTRACT(jsonPayload.client_name)"
  }

  # 1 B .. ~1 TB in 4x steps.
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 4
      scale              = 1
    }
  }
}
