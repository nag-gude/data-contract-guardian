# Terraform — Data Contract Guardian

Infrastructure as code for **Artifact Registry**, **Cloud Run** (API + UI), **Secret Manager**, **IAM**, and an optional **GCS bucket** for ADK Agent Engine deploy staging.

---

## Prerequisites

* GCP project with billing
* `gcloud auth application-default login`
* Terraform `>= 1.3`
* Docker images pushed to Artifact Registry (see below)

---

## Quick start

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit project_id, mock flags, bq_dataset, fivetran_connection_id, gemini_model

export TF_VAR_fivetran_api_key="..."
export TF_VAR_fivetran_api_secret="..."
export TF_VAR_gemini_api_key="..."    # optional — AI Studio on Cloud Run

terraform init
terraform apply
```

---

## Variables (common)

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `project_id` | — | **Required** |
| `region` | `us-central1` | Cloud Run + Artifact Registry |
| `mock_fivetran_mcp` | `false` | `true` = no Fivetran secrets |
| `mock_bigquery` | `false` | `true` = mock warehouse |
| `fivetran_connection_id` | `""` | Dashboard slug, e.g. `toll_donator` |
| `bq_dataset` | `""` | Fivetran destination schema in BigQuery |
| `gemini_model` | `gemini-3.5-flash` | Use `gemini-2.5-flash` if Vertex 404 in region |
| `gemini_api_key` | `""` | Stored in Secret Manager → `GEMINI_API_KEY` on backend |
| `create_adk_staging_bucket` | `true` | GCS for Agent Engine deploy |

Sensitive values: prefer `TF_VAR_*` env vars over committing `terraform.tfvars`.

---

## Build images before apply

Terraform references images in Artifact Registry. From **repo root**:

```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="us-central1"
./scripts/gcp-push-images.sh
```

Or use Cloud Build:

```bash
gcloud builds submit --config=cloudbuild.yaml .
```

Ensure `deploy/` is present in the upload (see root `.gcloudignore`).

---

## Outputs

```bash
terraform output frontend_url
terraform output backend_url
terraform output -raw adk_staging_bucket
terraform output backend_service_account
terraform output gemini_secret_configured
```

| Output | Use |
| ------ | --- |
| `frontend_url` | Public UI |
| `backend_url` | API + set as frontend `BACKEND_URL` (Terraform does this) |
| `adk_staging_bucket` | `ADK_STAGING_BUCKET` for deploy script |
| `backend_service_account` | Agent Engine runtime SA |
| `adk_deploy_command` | `./scripts/deploy-adk-agent-engine.sh --recreate` |

---

## Secret Manager resources

| Secret id | When created | Mounted as |
| --------- | ------------ | ---------- |
| `dcg-fivetran-api-key` | `mock_fivetran_mcp = false` | `FIVETRAN_API_KEY` |
| `dcg-fivetran-api-secret` | `mock_fivetran_mcp = false` | `FIVETRAN_API_SECRET` |
| `dcg-gemini-api-key` | `gemini_api_key` set | `GEMINI_API_KEY` |

When Gemini secret is mounted, backend uses `GEMINI_BACKEND=ai_studio`. Otherwise Vertex ADC (`GOOGLE_GENAI_USE_VERTEXAI=true`).

---

## Cloud Run defaults

| Service | Memory | Instances | Notes |
| ------- | ------ | --------- | ----- |
| Backend | 512Mi | min 1, max 1 | SQLite on `/tmp` |
| Frontend | 512Mi | min 1, max 4 | Proxies `/api/*` |

Raise backend memory to **1–2Gi** if MCP proxy or pipeline OOMs under load.

---

## Redeploy after code changes

```bash
./scripts/gcp-push-images.sh
cd terraform && terraform apply
```

Env-only changes need only `terraform apply`.

---

## Related docs

* [DEPLOYMENT.md](../docs/DEPLOYMENT.md) — full deployment guide
* [agent-builder-setup.md](../docs/agent-builder-setup.md) — Agent Engine deploy after `terraform apply`
