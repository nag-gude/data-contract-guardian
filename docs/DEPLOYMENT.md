# Deployment guide

This guide covers **local development**, **environment configuration**, **Docker images**, and **Google Cloud Platform (GCP)** deployment using **Terraform** and **Cloud Run**.

## Prerequisites

### Local development

* **Python 3.12+**
* **Node.js 20+** and npm
* **Google Cloud ADC** (`gcloud auth application-default login`) for Vertex Gemini and live BigQuery, or a **Gemini API key** for AI Studio fallback

### GCP (Terraform + Cloud Run)

* GCP **project** with **billing** enabled
* [**gcloud CLI**](https://cloud.google.com/sdk/docs/install)
* [**Terraform**](https://developer.hashicorp.com/terraform/install) `>= 1.3`
* [**Docker**](https://docs.docker.com/get-docker/)

Typical IAM for the deploy principal: Artifact Registry Writer, Cloud Run Admin, Service Usage Consumer. Public demo also needs permission to grant `roles/run.invoker` to `allUsers` (org policy may block this).

---

## 1. Local deployment (two processes)

### Backend (FastAPI)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # edit GCP, Fivetran, BQ_DATASET as needed
```

```bash
export PYTHONPATH=backend
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

* API: `http://127.0.0.1:8000`
* Swagger: `http://127.0.0.1:8000/docs`
* SQLite default: `backend/data/guardian.db`

### Frontend (Next.js)

```bash
cd frontend
cp ../.env.example .env.local
```

```env
BACKEND_URL=http://127.0.0.1:8000
```

```bash
npm install && npm run dev
```

* UI: `http://localhost:3000`

Browser calls to `/api/...` are proxied to FastAPI by `frontend/middleware.ts`. Without `BACKEND_URL`, those routes return **503**.

### ADK web UI (optional, chat-only)

```bash
cd backend
export PYTHONPATH=.
export GCP_PROJECT_ID=your-project
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID
export GOOGLE_CLOUD_LOCATION=us-central1
export GEMINI_MODEL=gemini-2.5-flash
export MOCK_FIVETRAN_MCP=false
export MOCK_BIGQUERY=false
export BQ_DATASET=your_fivetran_destination_schema
export FIVETRAN_CONNECTION_ID=your_connection_slug
# FIVETRAN_API_KEY / FIVETRAN_API_SECRET

adk web agent_builder
```

See [backend/agent_builder/README.md](../backend/agent_builder/README.md) for sample prompts. Approval and remediation execution still go through the Guardian UI or `POST /api/incidents/approve-remediation`.

### Demo script (local, mock mode)

1. **Agent Home** → **Seed failing** → **Run agent pipeline**
2. Open **Incidents** → inspect MCP trace and transcript
3. **Approve & re-verify** (mock: sync remediation refreshes warehouse freshness)
4. Or **Seed passing** → approve again → **resolved**

---

## 2. Environment variables (reference)

Copy **[`.env.example`](../.env.example)**.

### Backend (key variables)

| Variable | Example | Notes |
| -------- | ------- | ----- |
| `GCP_PROJECT_ID` | `prj-caiml-hackathon-01` | Vertex AI + live BigQuery |
| `BQ_DATASET` | `airtable_network_appxzsmwynqrvmfcq` | Overrides contract placeholder `bq_dataset: network` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | GA in `us-central1`; use `global` + `gemini-3.5-*` if needed |
| `GEMINI_FALLBACK_MODEL` | `gemini-2.5-flash` | Used when primary model fails |
| `GEMINI_LOCATION` | `us-central1` | Vertex region for Gemini |
| `GEMINI_BACKEND` | `auto` | `auto` \| `vertex` \| `ai_studio` |
| `USE_AGENT_BUILDER` | `true` | ADK path when `google-adk` installed |
| `MOCK_FIVETRAN_MCP` | `true` | `false` for live Fivetran MCP (needs API key + secret) |
| `MOCK_BIGQUERY` | `true` | `false` for live BigQuery validation |
| `FIVETRAN_CONNECTION_ID` | `toll_donator` | Dashboard slug or hint; resolved via `list_connections` |
| `FIVETRAN_ALLOW_WRITES` | `false` | MCP write tools off; approval sync uses Fivetran REST |
| `DATABASE_PATH` | `backend/data/guardian.db` | `/tmp/guardian.db` in containers |

Terraform mirrors these on Cloud Run (`terraform/main.tf`). Fivetran secrets are injected from **Secret Manager** when `mock_fivetran_mcp = false`.

### Frontend

| Variable | Example | Notes |
| -------- | ------- | ----- |
| `BACKEND_URL` | `https://data-contract-guardian-api-….run.app` | **Required** on Cloud Run UI for `/api` proxy |

---

## 3. Docker images (build context = repository root)

```bash
docker build -f deploy/Dockerfile.backend -t backend:local .
docker build -f deploy/Dockerfile.frontend -t frontend:local .
```

Backend defaults: `PORT=8080`, `CONTRACTS_DIR=/app/contracts`, `DATABASE_PATH=/tmp/guardian.db`, `GEMINI_MODEL=gemini-2.5-flash`, `USE_AGENT_BUILDER=true`.

---

## 4. GCP: Terraform + Cloud Run

Infra: **`terraform/`**

| Resource | Default name |
| -------- | ------------ |
| Artifact Registry repo | `data-contract-guardian` |
| Backend service | `data-contract-guardian-api` |
| Frontend service | `data-contract-guardian-ui` |
| Backend image | `{region}-docker.pkg.dev/{project}/data-contract-guardian/backend:{tag}` |
| Frontend image | `…/frontend:{tag}` |

### 4.1 Setup

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit: project_id, mock_fivetran_mcp, mock_bigquery, fivetran_connection_id, bq_dataset, gemini_model
terraform init
```

**Secrets:** pass Fivetran credentials via env, not committed tfvars:

```bash
export TF_VAR_fivetran_api_key=...
export TF_VAR_fivetran_api_secret=...
```

Example `terraform.tfvars` for live hackathon demo:

```hcl
project_id              = "prj-caiml-hackathon-01"
mock_fivetran_mcp       = false
mock_bigquery           = false
fivetran_connection_id  = "toll_donator"
bq_dataset              = "airtable_network_appxzsmwynqrvmfcq"
gemini_model            = "gemini-2.5-flash"
gemini_location         = "us-central1"
```

### 4.2 Artifact Registry (first time)

```bash
terraform apply -target=google_artifact_registry_repository.dcg
```

### 4.3 Build and push images

From **repository root**:

```bash
export GCP_PROJECT_ID="your-gcp-project-id"
export GCP_REGION="us-central1"
export IMAGE_TAG="latest"
./scripts/gcp-push-images.sh
```

Pushes `backend:{tag}` and `frontend:{tag}` to Artifact Registry (matches Terraform `backend_image_name` / `frontend_image_name` defaults).

### 4.4 Deploy

```bash
cd terraform && terraform apply
terraform output frontend_url
terraform output backend_url
```

### 4.5 Cloud Run notes

* Backend **`max_instance_count = 1`** — SQLite on `/tmp` is per-instance; single instance keeps incidents and workflow counters consistent.
* Backend **`min_instance_count = 1`** — avoids cold-start latency for MCP + Gemini.
* Vertex env vars set automatically: `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`.
* Fivetran MCP in container uses `FIVETRAN_MCP_COMMAND=fivetran-mcp` (bundled in image, not `uvx`).

### 4.6 Redeploy after code changes

```bash
./scripts/gcp-push-images.sh
cd terraform && terraform apply
```

Env-only changes (e.g. `gemini_model`, `bq_dataset`) need only `terraform apply`.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------- | --- |
| Gemini **404** `Publisher Model … gemini-3.5-flash … not found` | Model not in `us-central1` | Use `gemini_model = "gemini-2.5-flash"` or `gemini_location = "global"` |
| Next `/api/...` **503** | `BACKEND_URL` unset | Set on Cloud Run UI service or `.env.local` |
| Empty incidents table, status shows awaiting | Multi-instance SQLite | Confirm backend `max_instance_count = 1`; use `GET /api/incidents?open=true` |
| Validation: table not found | Wrong BigQuery dataset | Set `BQ_DATASET` to Fivetran destination schema slug |
| Approval: verification still fails (live) | BigQuery lag after sync | Wait and re-approve; approval polls ~90s after Fivetran sync trigger |
| `terraform apply` image error | Image not pushed | Run `gcp-push-images.sh` first |
| Slow first page load | MCP discovery client-side | Expected — shell renders first; discovery loads in background |
| ADK: no API key | Vertex not configured | Set `GCP_PROJECT_ID` + ADC, or `GEMINI_API_KEY` for AI Studio |

---

## 6. Related files

| File | Role |
| ---- | ---- |
| [`deploy/Dockerfile.backend`](../deploy/Dockerfile.backend) | API container |
| [`deploy/Dockerfile.frontend`](../deploy/Dockerfile.frontend) | UI container |
| [`scripts/gcp-push-images.sh`](../scripts/gcp-push-images.sh) | Build + push both images |
| [`terraform/`](../terraform/) | Cloud Run, IAM, Secret Manager |
| [`docs/IMPLEMENTATION.md`](./IMPLEMENTATION.md) | Code-level architecture |
