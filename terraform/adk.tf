locals {
  adk_staging_bucket_name = coalesce(
    var.adk_staging_bucket_name,
    "${var.project_id}-dcg-adk-staging"
  )
}

resource "google_storage_bucket" "adk_staging" {
  count = var.create_adk_staging_bucket ? 1 : 0

  project  = var.project_id
  name     = local.adk_staging_bucket_name
  location = var.region

  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.apis]
}


resource "google_storage_bucket_iam_member" "adk_staging_backend" {
  count = var.create_adk_staging_bucket ? 1 : 0

  bucket = google_storage_bucket.adk_staging[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.backend.email}"
}
