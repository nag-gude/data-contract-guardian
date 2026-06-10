output "artifact_registry_url" {
  value       = google_artifact_registry_repository.dcg.name
  description = "Artifact Registry resource name"
}

output "backend_url" {
  value       = google_cloud_run_v2_service.backend.uri
  description = "Public URL of the FastAPI backend (also set BACKEND_URL on frontend)."
}

output "frontend_url" {
  value       = google_cloud_run_v2_service.frontend.uri
  description = "Public URL of the Next.js UI."
}

output "docker_push_prefix" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repository_id}"
  description = "docker tag prefix for docker push commands"
}

output "backend_service_account" {
  value       = google_service_account.backend.email
  description = "Cloud Run backend SA (also used as Agent Engine runtime SA)."
}

output "adk_staging_bucket" {
  value       = var.create_adk_staging_bucket ? "gs://${google_storage_bucket.adk_staging[0].name}" : null
  description = "GCS bucket URI for ADK Agent Engine deploy staging."
}

output "adk_deploy_command" {
  value       = "./scripts/deploy-adk-agent-engine.sh --recreate"
  description = "Deploy guardian_assistant to Vertex AI Agent Engine playground."
}

output "gemini_secret_configured" {
  value       = nonsensitive(local.gemini_live)
  description = "True when GEMINI_API_KEY is mounted on Cloud Run from Secret Manager."
}
