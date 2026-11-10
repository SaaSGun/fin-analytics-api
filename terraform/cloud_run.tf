resource "google_cloud_run_v2_service" "fin_analytics_api" {
  project  = var.project_id
  name     = "fin-analytics-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.fin_api_run.email
    max_instance_request_concurrency = 40
    timeout                          = "300s"

    scaling {
      # min_instance_count left unset (0) deliberately - no sustained
      # traffic on this demo, not worth paying to avoid cold starts.
      max_instance_count = 10
    }

    containers {
      # Ignored below - CI/CD owns the deployed image, not Terraform.
      image = "europe-west4-docker.pkg.dev/fin-analytics-api/cloud-run-source-deploy/fin-analytics-api@sha256:3596cd41cb588a3ff6602b756fb04d55f66076786c84d525b6144299a93a8e09"

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }

      startup_probe {
        failure_threshold = 1
        period_seconds    = 240
        timeout_seconds   = 240
        tcp_socket {
          port = 8080
        }
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.fin_analytics.dataset_id
      }
      env {
        name  = "BQ_LOCATION"
        value = var.region
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      # Every `gcloud run deploy` / CI run produces a new image digest, a
      # fresh revision label and a gcloud client-version annotation. None
      # of that should fight the deploy pipeline on the next `terraform
      # apply` - concurrency, max-instances, service account, env vars
      # and resource limits above ARE still enforced by Terraform.
      template[0].containers[0].image,
      template[0].labels,
      template[0].annotations,
      client,
      client_version,
    ]
  }
}
