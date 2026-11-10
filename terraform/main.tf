terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Bucket must exist before `terraform init` can use it as a backend —
  # one-time manual bootstrap, see docs/terraform.md.
  backend "gcs" {
    bucket = "fin-analytics-api-1089997989086-tfstate"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}
