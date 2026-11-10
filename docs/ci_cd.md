# CI/CD

Pipeline: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (GitHub Actions).

| Trigger | `checks` job (lint + test) | `deploy` job (Cloud Run) |
|---|---|---|
| Pull request | runs | skipped |
| Push to `main` | runs | runs **only if `checks` passed** |
| Manual (`workflow_dispatch`) on `main` | runs | runs only if `checks` passed |

- **Lint**: `ruff check .` (version pinned in `requirements-dev.txt` so CI and
  local runs agree; config in `ruff.toml`). Findings show up as inline
  annotations on the PR diff.
- **Test**: `pytest`. The suite is fully offline (BigQuery calls are
  monkeypatched), so this job needs **no GCP credentials**.
- **Deploy**: the same `gcloud run deploy --source .` as a manual deploy (Cloud
  Build builds the `Dockerfile`, pushes to Artifact Registry, rolls out a new
  revision). Env vars, concurrency and max-instances carry over from the
  previous revision.

## Keyless GCP auth (Workload Identity Federation)

No service-account JSON key is stored in GitHub. On each deploy run, GitHub
issues a short-lived OIDC token for the workflow; GCP's Security Token
Service exchanges it for short-lived credentials of the `github-deployer`
service account. Only this exact repository's `main` branch can do the
exchange: the provider's attribute condition rejects tokens from any other
repo or branch.

`github-deployer` has only what `gcloud run deploy --source` needs:

| Role | Scope | Why |
|---|---|---|
| `roles/run.sourceDeveloper` | project | deploy Cloud Run from source (Cloud Build submit, source upload, Artifact Registry) |
| `roles/serviceusage.serviceUsageConsumer` | project | call the APIs used by the deploy |
| `roles/iam.serviceAccountUser` | `fin-api-run` SA only | run the new revision as the runtime SA |
| `roles/iam.serviceAccountUser` | default compute SA only | Cloud Build runs the build as this SA |

It has no BigQuery access and no IAM-admin rights.

## One-time setup (run by a project owner)

One command per line. Works in cmd and PowerShell.

```
gcloud iam roles describe roles/run.sourceDeveloper --format="value(title)"
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project fin-analytics-api

gcloud iam workload-identity-pools create github --project fin-analytics-api --location global --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc fin-analytics-api --project fin-analytics-api --location global --workload-identity-pool github --display-name "fin-analytics-api repo" --issuer-uri "https://token.actions.githubusercontent.com" --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" --attribute-condition "assertion.repository=='SaaSGun/fin-analytics-api'&&assertion.ref=='refs/heads/main'"

gcloud iam service-accounts create github-deployer --project fin-analytics-api --display-name "GitHub Actions deployer"

gcloud projects add-iam-policy-binding fin-analytics-api --member "serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com" --role roles/run.sourceDeveloper --condition None
gcloud projects add-iam-policy-binding fin-analytics-api --member "serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com" --role roles/serviceusage.serviceUsageConsumer --condition None
gcloud iam service-accounts add-iam-policy-binding fin-api-run@fin-analytics-api.iam.gserviceaccount.com --project fin-analytics-api --member "serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com" --role roles/iam.serviceAccountUser
gcloud iam service-accounts add-iam-policy-binding 1089997989086-compute@developer.gserviceaccount.com --project fin-analytics-api --member "serviceAccount:github-deployer@fin-analytics-api.iam.gserviceaccount.com" --role roles/iam.serviceAccountUser

gcloud iam service-accounts add-iam-policy-binding github-deployer@fin-analytics-api.iam.gserviceaccount.com --project fin-analytics-api --role roles/iam.workloadIdentityUser --member "principalSet://iam.googleapis.com/projects/1089997989086/locations/global/workloadIdentityPools/github/attribute.repository/SaaSGun/fin-analytics-api"
```

`1089997989086` is the project number (`gcloud projects describe
fin-analytics-api --format="value(projectNumber)"`). It also appears in
`WIF_PROVIDER` at the top of `ci.yml`. Identifiers like these are not
secrets, which is why the workflow needs no GitHub secrets at all.

New IAM bindings can take a minute or two to take effect, so a deploy that
fails with a permission error right after setup is worth one re-run before
debugging.
