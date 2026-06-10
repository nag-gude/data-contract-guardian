"""Configure Google ADK / Gemini auth to match ``app.services.gemini_client``."""

from __future__ import annotations

import os
from functools import cached_property
from typing import Any

from app.config import settings
from app.services.gemini_client import resolve_backend


def configure_adk_gemini_env() -> str:
    """
    Align ADK with the same Gemini backend as the FastAPI orchestrator.

    ADK defaults to Gemini API (AI Studio) and requires ``GOOGLE_API_KEY`` unless
    ``GOOGLE_GENAI_USE_VERTEXAI=true`` with ``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION``.
    Cloud Run sets ``GCP_PROJECT_ID`` but ADK does not read that name — map it here.
    """
    backend = resolve_backend()
    if backend == "vertex_ai" and settings.gcp_project_id:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.gcp_project_id
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.gemini_location
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        return backend

    if backend == "ai_studio" and settings.gemini_api_key:
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        return backend

    return "none"


def build_adk_model() -> Any:
    """
    Return an ADK model configured for Vertex AI or AI Studio.

    Prefer an explicit Vertex ``Gemini`` client (ADC on Cloud Run) over a bare model string,
    which would otherwise require an AI Studio API key.
    """
    backend = configure_adk_gemini_env()
    if backend == "vertex_ai":
        from google.adk.models import Gemini
        from google import genai

        class VertexGemini(Gemini):
            @cached_property
            def api_client(self) -> genai.Client:
                return genai.Client(
                    vertexai=True,
                    project=settings.gcp_project_id,
                    location=settings.gemini_location,
                )

        return VertexGemini(model=settings.gemini_model)

    if backend == "ai_studio":
        return settings.gemini_model

    raise RuntimeError(
        "ADK requires Gemini credentials: set GCP_PROJECT_ID for Vertex AI "
        "or GEMINI_API_KEY for AI Studio."
    )


def adk_gemini_ready() -> bool:
    """True when ADK can authenticate to Gemini (Vertex ADC or AI Studio key)."""
    return resolve_backend() != "none"
