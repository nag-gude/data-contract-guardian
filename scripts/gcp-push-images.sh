#!/usr/bin/env bash
# Build and push images to Artifact Registry (run from repository root).
set -euo pipefail
PROJECT="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
REPO="${ARTIFACT_REPO:-data-contract-guardian}"
TAG="${IMAGE_TAG:-latest}"
PREFIX="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

echo "Configuring docker auth for ${REGION}-docker.pkg.dev ..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" -q

echo "Building backend ..."
docker build -f deploy/Dockerfile.backend -t "${PREFIX}/backend:${TAG}" .

echo "Building frontend ..."
docker build -f deploy/Dockerfile.frontend -t "${PREFIX}/frontend:${TAG}" .

echo "Pushing ..."
docker push "${PREFIX}/backend:${TAG}"
docker push "${PREFIX}/frontend:${TAG}"

echo "Done. Images:"
echo "  ${PREFIX}/backend:${TAG}"
echo "  ${PREFIX}/frontend:${TAG}"
