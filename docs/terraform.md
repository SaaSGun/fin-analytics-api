# Terraform (Infrastructure as Code)

`terraform/` codifies the GCP setup that was previously built by hand
(`gcloud`/console-click history, documented historically in
[`docs/ci_cd.md`](ci_cd.md)): service accounts, project IAM bindings, the
Workload Identity Federation pool/provider, the BigQuery dataset, and the
Cloud Run service's static settings.

**Scope - what this does NOT manage, on purpose:**
- GCP project creation / billing linkage (one-time, org-level, not worth
  re-creating from a Terraform run).
- BigQuery table schemas/rows (owned by `etl/load_bigquery.py` / `bq load`)
  and the `api_keys` table's contents (owned by `scripts/manage_api_keys.py`).
- The Cloud Run service's deployed container image/revision (owned by CI/CD
  - see the `lifecycle.ignore_changes` in `terraform/cloud_run.tf`).
- The dataset's IAM access list (BigQuery auto-grants default ACLs on
  creation; see the comment in `terraform/bigquery.tf`).

Everything here is non-secret identifiers (project ID, service account
emails, the GitHub repo slug) - same reasoning as `docs/ci_cd.md`.

## Running this from Google Cloud Shell

On at least one machine used for this project, the downloaded
`terraform-provider-google` plugin binary is blocked outright by a local
executable allow-list policy (the same AppLocker/WDAC-style restriction
that also blocks `k6.exe` regardless of path — confirmed via
`terraform validate` failing with "This program is blocked by group
policy" on a `fork/exec` of the provider binary, even though `terraform
init` itself succeeds). If that happens, run everything below from
[Google Cloud Shell](https://shell.cloud.google.com/) instead — it comes
with `terraform` + `gcloud` preinstalled and isn't subject to the local
machine's policy:

```bash
gcloud config set project fin-analytics-api
git clone https://github.com/SaaSGun/fin-analytics-api.git
cd fin-analytics-api/terraform
```

Then continue with `terraform init` etc. below as normal. State lives in
the GCS bucket (not locally), so it doesn't matter which machine/shell
runs these commands.

## One-time bootstrap (run by a project owner, not Terraform)

Terraform's own state needs a GCS bucket to exist before `terraform init`
can use it as a backend - chicken-and-egg, so this one step is manual:

```
gcloud storage buckets create gs://fin-analytics-api-1089997989086-tfstate --project fin-analytics-api --location europe-west4 --uniform-bucket-level-access
gcloud storage buckets update gs://fin-analytics-api-1089997989086-tfstate --versioning
```

Then, from `terraform/`:

```
terraform init
```

## Importing the existing resources

Every resource below already exists in GCP (built manually before this
Terraform config existed). Running a bare `terraform apply` without
importing first would fail on the resources marked **required** (GCP
rejects creating a duplicate service account / dataset / Cloud Run service
/ WIF pool with an "already exists" error). The ones marked **optional**
call idempotent/merge-style APIs (enabling an already-enabled API, adding
an IAM member that's already present), so `apply` would succeed even
without importing them first - importing anyway is still worth it so
`terraform plan` reflects reality from the start instead of proposing a
confusing "create" on something that already exists.

Run from `terraform/`. Quoting shown works in both cmd and PowerShell.

**Required:**

```
terraform import google_service_account.fin_api_run projects/fin-analytics-api/serviceAccounts/fin-api-run@fin-analytics-api.iam.gserviceaccount.com
terraform import google_service_account.github_deployer projects/fin-analytics-api/serviceAccounts/github-deployer@fin-analytics-api.iam.gserviceaccount.com
terraform import google_bigquery_dataset.fin_analytics projects/fin-analytics-api/datasets/fin_analytics
terraform import google_cloud_run_v2_service.fin_analytics_api projects/fin-analytics-api/locations/europe-west4/services/fin-analytics-api
terraform import google_iam_workload_identity_pool.github projects/fin-analytics-api/locations/global/workloadIdentityPools/github
terraform import google_iam_workload_identity_pool_provider.fin_analytics_api projects/fin-analytics-api/locations/global/workloadIdentityPools/github/providers/fin-analytics-api
```

**Optional (recommended anyway):**

Quoting below is bash (Cloud Shell). In cmd/PowerShell, replace the
single-quoted `google_project_service.this[...]` addresses with
`"google_project_service.this[\"...\"]"` instead.

```bash
terraform import 'google_project_service.this["iam.googleapis.com"]' fin-analytics-api/iam.googleapis.com
terraform import 'google_project_service.this["bigquery.googleapis.com"]' fin-analytics-api/bigquery.googleapis.com
terraform import 'google_project_service.this["bigquerystorage.googleapis.com"]' fin-analytics-api/bigquerystorage.googleapis.com
terraform import 'google_project_service.this["run.googleapis.com"]' fin-analytics-api/run.googleapis.com
terraform import 'google_project_service.this["artifactregistry.googleapis.com"]' fin-analytics-api/artifactregistry.googleapis.com
terraform import 'google_project_service.this["cloudbuild.googleapis.com"]' fin-analytics-api/cloudbuild.googleapis.com
terraform import 'google_project_service.this["iamcredentials.googleapis.com"]' fin-analytics-api/iamcredentials.googleapis.com
terraform import 'google_project_service.this["sts.googleapis.com"]' fin-analytics-api/sts.googleapis.com
terraform import 'google_project_service.this["storage.googleapis.com"]' fin-analytics-api/storage.googleapis.com
terraform import 'google_project_service.this["logging.googleapis.com"]' fin-analytics-api/logging.googleapis.com

terraform import google_project_iam_member.fin_api_run_bq_viewer "fin-analytics-api roles/bigquery.dataViewer serviceAccount:fin-api-run@fin-analytics-api.iam.gserviceaccount.com"
terraform import google_project_iam_member.fin_api_run_bq_job_user "fin-analytics-api roles/bigquery.jobUser serviceAccount:fin-api-run@fin-analytics-api.iam.gserviceaccount.com"
terraform import google_project_iam_member.github_deployer_run_source_dev "fin-analytics-api roles/run.sourceDeveloper serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com"
terraform import google_project_iam_member.github_deployer_service_usage "fin-analytics-api roles/serviceusage.serviceUsageConsumer serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com"

terraform import google_service_account_iam_member.deployer_can_run_as_fin_api_run "projects/fin-analytics-api/serviceAccounts/fin-api-run@fin-analytics-api.iam.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com"
terraform import google_service_account_iam_member.deployer_can_run_as_compute_default "projects/fin-analytics-api/serviceAccounts/1089997989086-compute@developer.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com"
terraform import google_service_account_iam_member.github_deployer_workload_identity_user "projects/fin-analytics-api/serviceAccounts/github-deployer@fin-analytics-api.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/1089997989086/locations/global/workloadIdentityPools/github/attribute.repository/SaaSGun/fin-analytics-api"
```

## After importing

```
terraform plan
```

Expect **no changes**, or only the fields explicitly listed in
`cloud_run.tf`'s `lifecycle.ignore_changes` comment showing as ignored (not
proposed). Review the plan carefully before ever running `terraform apply`
- especially the BigQuery dataset and Cloud Run resources, since those sit
in front of real (if synthetic) data and a live service.

`1089997989086` is the project number
(`gcloud projects describe fin-analytics-api --format="value(projectNumber)"`),
same as in `docs/ci_cd.md` and `.github/workflows/ci.yml`.
