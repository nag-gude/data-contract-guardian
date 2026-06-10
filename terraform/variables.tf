variable "project_id" {
  type        = string
  description = "GCP project ID (e.g. my-data-project)."
}

variable "region" {
  type        = string
  description = "Region for Artifact Registry and Cloud Run."
  default     = "us-central1"
}

variable "artifact_repository_id" {
  type    = string
  default = "data-contract-guardian"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag for both services (e.g. latest or git sha)."
  default     = "latest"
}

variable "backend_service_name" {
  type    = string
  default = "data-contract-guardian-api"
}

variable "frontend_service_name" {
  type    = string
  default = "data-contract-guardian-ui"
}

variable "backend_image_name" {
  type    = string
  default = "backend"
}

variable "frontend_image_name" {
  type    = string
  default = "frontend"
}

variable "allow_unauthenticated" {
  type        = bool
  description = "If true, grant roles/run.invoker to allUsers (public demo / unauthenticated access)."
  default     = true
}

variable "gemini_model" {
  type        = string
  description = "Gemini model id for Vertex AI / Agent Builder."
  default     = "gemini-3.5-flash"
}

variable "gemini_location" {
  type        = string
  description = "Vertex AI location for Gemini (gemini-3.5-flash on us-central1). Defaults align with Cloud Run region."
  default     = "us-central1"
}

variable "gemini_fallback_model" {
  type        = string
  description = "Gemini model tried when the primary returns no text or is unavailable in the region."
  default     = "gemini-2.5-flash"
}

variable "gemini_safety_threshold" {
  type        = string
  description = "Gemini safety guardrail applied to every call."
  default     = "BLOCK_ONLY_HIGH"

  validation {
    condition = contains(
      ["BLOCK_NONE", "BLOCK_ONLY_HIGH", "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_LOW_AND_ABOVE"],
      var.gemini_safety_threshold
    )
    error_message = "gemini_safety_threshold must be one of BLOCK_NONE, BLOCK_ONLY_HIGH, BLOCK_MEDIUM_AND_ABOVE, BLOCK_LOW_AND_ABOVE."
  }
}

variable "mock_fivetran_mcp" {
  type        = bool
  description = "Use mock Fivetran MCP for demo; set false with Fivetran secrets for live."
  default     = false
}

variable "fivetran_api_key" {
  type        = string
  description = "Fivetran API key — stored in Secret Manager and injected into Cloud Run when mock_fivetran_mcp=false."
  default     = ""
  sensitive   = true
}

variable "fivetran_api_secret" {
  type        = string
  description = "Fivetran API secret — stored in Secret Manager and injected into Cloud Run when mock_fivetran_mcp=false."
  default     = ""
  sensitive   = true
}

variable "fivetran_connection_id" {
  type        = string
  description = "Real Fivetran connection slug when contracts use alias ft_airtable_network (optional — auto-resolved via list_connections if empty)."
  default     = ""
}

variable "bq_dataset" {
  type        = string
  description = "Fivetran destination BigQuery dataset slug when contract YAML uses placeholder network."
  default     = ""
}

variable "mock_bigquery" {
  type        = bool
  description = "Use mock warehouse; set false for live BigQuery INFORMATION_SCHEMA checks."
  default     = false
}

variable "gemini_api_key" {
  type        = string
  description = "Gemini API key (AI Studio) — stored in Secret Manager and injected into Cloud Run as GEMINI_API_KEY."
  default     = ""
  sensitive   = true
}

variable "create_adk_staging_bucket" {
  type        = bool
  description = "Create GCS bucket for ADK Agent Engine deploy staging artifacts."
  default     = true
}

variable "adk_staging_bucket_name" {
  type        = string
  description = "Override ADK staging bucket name (default: {project_id}-dcg-adk-staging)."
  default     = null
}
