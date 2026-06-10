locals {
  ar_host        = "${var.region}-docker.pkg.dev"
  ar_repo        = "${local.ar_host}/${var.project_id}/${var.artifact_repository_id}"
  backend_image  = "${local.ar_repo}/${var.backend_image_name}:${var.image_tag}"
  frontend_image = "${local.ar_repo}/${var.frontend_image_name}:${var.image_tag}"

  # Live Fivetran MCP needs real credentials wired through Secret Manager.
  fivetran_live = !var.mock_fivetran_mcp
  # Gemini AI Studio key — preferred on Cloud Run for models like gemini-3.5-flash.
  gemini_live = var.gemini_api_key != ""
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Secret Manager — Fivetran API credentials (created only in live MCP mode).
# The backend service account is granted accessor and the values are mounted
# as Cloud Run secret env vars (never plaintext in the service definition).
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "fivetran_api_key" {
  count     = local.fivetran_live ? 1 : 0
  secret_id = "dcg-fivetran-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "fivetran_api_key" {
  count       = local.fivetran_live ? 1 : 0
  secret      = google_secret_manager_secret.fivetran_api_key[0].id
  secret_data = var.fivetran_api_key

  lifecycle {
    precondition {
      condition     = !local.fivetran_live || (var.fivetran_api_key != "" && var.fivetran_api_secret != "")
      error_message = "mock_fivetran_mcp=false requires both fivetran_api_key and fivetran_api_secret to be set."
    }
  }
}

resource "google_secret_manager_secret" "fivetran_api_secret" {
  count     = local.fivetran_live ? 1 : 0
  secret_id = "dcg-fivetran-api-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "fivetran_api_secret" {
  count       = local.fivetran_live ? 1 : 0
  secret      = google_secret_manager_secret.fivetran_api_secret[0].id
  secret_data = var.fivetran_api_secret
}

resource "google_secret_manager_secret_iam_member" "fivetran_api_key" {
  count     = local.fivetran_live ? 1 : 0
  secret_id = google_secret_manager_secret.fivetran_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_secret_manager_secret_iam_member" "fivetran_api_secret" {
  count     = local.fivetran_live ? 1 : 0
  secret_id = google_secret_manager_secret.fivetran_api_secret[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# ---------------------------------------------------------------------------
# Secret Manager — Gemini API key (AI Studio). When set, backend uses
# GEMINI_BACKEND=ai_studio instead of Vertex ADC (better for gemini-3.5-flash).
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "gemini_api_key" {
  count     = local.gemini_live ? 1 : 0
  secret_id = "dcg-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  count       = local.gemini_live ? 1 : 0
  secret      = google_secret_manager_secret.gemini_api_key[0].id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret_iam_member" "gemini_api_key" {
  count     = local.gemini_live ? 1 : 0
  secret_id = google_secret_manager_secret.gemini_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_service_account" "backend" {
  account_id   = "dcg-backend"
  display_name = "Data Contract Guardian API"
}

resource "google_project_iam_member" "backend_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_bq_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_bq_job" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_artifact_registry_repository" "dcg" {
  location      = var.region
  repository_id = var.artifact_repository_id
  description   = "Data Contract Guardian"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "backend" {
  name     = var.backend_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    max_instance_request_concurrency = 16
    timeout                          = "300s"
    service_account                  = google_service_account.backend.email

    scaling {
      # SQLite lives on /tmp per instance — single instance so incidents match platform status.
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      image = local.backend_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "CORS_ORIGINS"
        value = "*"
      }
      env {
        name  = "DATABASE_PATH"
        value = "/tmp/guardian.db"
      }
      env {
        name  = "CONTRACTS_DIR"
        value = "/app/contracts"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      dynamic "env" {
        for_each = var.bq_dataset != "" ? [1] : []
        content {
          name  = "BQ_DATASET"
          value = var.bq_dataset
        }
      }
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
      env {
        name  = "GEMINI_LOCATION"
        value = var.gemini_location
      }
      # ADK reads GOOGLE_CLOUD_* / GOOGLE_GENAI_USE_VERTEXAI (not GCP_PROJECT_ID).
      # When GEMINI_API_KEY is mounted, use AI Studio (GEMINI_BACKEND=ai_studio).
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = local.gemini_live ? "false" : "true"
      }
      dynamic "env" {
        for_each = local.gemini_live ? [] : [1]
        content {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
      }
      dynamic "env" {
        for_each = local.gemini_live ? [] : [1]
        content {
          name  = "GOOGLE_CLOUD_LOCATION"
          value = var.gemini_location
        }
      }
      env {
        name  = "USE_AGENT_BUILDER"
        value = "true"
      }
      env {
        name  = "GEMINI_BACKEND"
        value = local.gemini_live ? "ai_studio" : "auto"
      }
      dynamic "env" {
        for_each = local.gemini_live ? [1] : []
        content {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "GEMINI_FALLBACK_MODEL"
        value = var.gemini_fallback_model
      }
      env {
        name  = "GEMINI_SAFETY_THRESHOLD"
        value = var.gemini_safety_threshold
      }
      env {
        name  = "MOCK_FIVETRAN_MCP"
        value = var.mock_fivetran_mcp ? "true" : "false"
      }

      # Live Fivetran MCP credentials sourced from Secret Manager (only when not mocked).
      dynamic "env" {
        for_each = local.fivetran_live ? [1] : []
        content {
          name = "FIVETRAN_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.fivetran_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = local.fivetran_live ? [1] : []
        content {
          name = "FIVETRAN_API_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.fivetran_api_secret[0].secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name  = "MOCK_BIGQUERY"
        value = var.mock_bigquery ? "true" : "false"
      }
      env {
        name  = "FIVETRAN_MCP_COMMAND"
        value = "fivetran-mcp"
      }
      env {
        name  = "FIVETRAN_MCP_ARGS"
        value = ""
      }
      dynamic "env" {
        for_each = var.fivetran_connection_id != "" ? [1] : []
        content {
          name  = "FIVETRAN_CONNECTION_ID"
          value = var.fivetran_connection_id
        }
      }
      env {
        name  = "FIVETRAN_ALLOW_WRITES"
        value = "false"
      }
      env {
        name  = "LAST_UPDATED_AT"
        value = timestamp()
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.dcg,
    google_project_iam_member.backend_vertex,
    google_project_iam_member.backend_bq_viewer,
    google_project_iam_member.backend_bq_job,
    google_secret_manager_secret_iam_member.fivetran_api_key,
    google_secret_manager_secret_iam_member.fivetran_api_secret,
    google_secret_manager_secret_iam_member.gemini_api_key,
  ]
}

resource "google_cloud_run_v2_service" "frontend" {
  name     = var.frontend_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    max_instance_request_concurrency = 32
    timeout                          = "300s"

    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }

    containers {
      image = local.frontend_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
      env {
        name  = "LAST_UPDATED_AT"
        value = timestamp()
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_cloud_run_v2_service.backend,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.frontend.location
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
