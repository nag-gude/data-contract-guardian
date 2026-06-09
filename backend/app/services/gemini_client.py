"""Unified Gemini client built on the modern google-genai SDK (Vertex AI or AI Studio).

Uses Google Cloud AI only. Vertex AI on GCP is the production path (default ``us-central1`` for
``gemini-3.5-flash``); an AI Studio API key is supported for local dev. We use the **google-genai**
SDK rather than the legacy ``vertexai.generative_models`` SDK because the legacy client does not
reliably support current Gemini models (it returned empty text), which silently degraded the agent
to template RCA.

Design notes that make the agent's reasoning robust:
  • **JSON mode** sets ``response_mime_type="application/json"`` so structured RCA parses cleanly.
  • **Fallback model** — if the primary model returns no text (or is unavailable in the region),
    a second model is tried before giving up, so the agent keeps producing real Gemini output.
  • **Cross-backend fallback** — a Vertex failure with an AI Studio key present retries on AI Studio.
  • Safety settings are applied to every call.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

GeminiBackend = Literal["vertex_ai", "ai_studio", "none"]

# Harm categories guarded on every Gemini call.
_SAFETY_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)


def resolve_backend() -> GeminiBackend:
    """Decide which Gemini backend is usable: ``vertex_ai``, ``ai_studio``, or ``none``.

    Honours an explicit ``GEMINI_BACKEND``; in ``auto`` mode prefers Vertex AI on GCP and falls
    back to an AI Studio API key, returning ``none`` when neither is available.
    """
    mode = settings.gemini_backend.lower()
    if mode == "vertex":
        return "vertex_ai" if _vertex_available() else "none"
    if mode == "ai_studio":
        return "ai_studio" if settings.gemini_api_key else "none"
    # auto: prefer Vertex on GCP, else AI Studio
    if _vertex_available():
        return "vertex_ai"
    if settings.gemini_api_key:
        return "ai_studio"
    return "none"


def _vertex_available() -> bool:
    """True when a GCP project is configured and the google-genai SDK can be imported."""
    if not settings.gcp_project_id:
        return False
    try:
        import google.auth  # noqa: F401
        from google import genai  # noqa: F401

        return True
    except ImportError:
        return False


def _client(backend: GeminiBackend):
    """Construct a google-genai client for the given backend."""
    from google import genai

    if backend == "vertex_ai":
        return genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gemini_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


def _safety_settings() -> list[Any]:
    """Build google-genai ``SafetySetting`` objects for all guarded categories."""
    from google.genai import types

    return [
        types.SafetySetting(category=cat, threshold=settings.gemini_safety_threshold)
        for cat in _SAFETY_CATEGORIES
    ]


def _models_to_try() -> list[str]:
    """Primary model, then the configured fallback (deduplicated)."""
    models = [settings.gemini_model]
    fb = (settings.gemini_fallback_model or "").strip()
    if fb and fb not in models:
        models.append(fb)
    return models


def _generate(prompt: str, backend: GeminiBackend, *, json_mode: bool) -> str:
    """Generate text on ``backend``, trying the primary then fallback model. Returns text or ``""``."""
    from google.genai import types

    client = _client(backend)
    config = types.GenerateContentConfig(
        safety_settings=_safety_settings(),
        temperature=0.2,
        response_mime_type="application/json" if json_mode else None,
    )

    last_exc: Exception | None = None
    for model in _models_to_try():
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            text = (getattr(resp, "text", None) or "").strip()
            if text:
                if model != settings.gemini_model:
                    logger.info("Gemini primary model unavailable; used fallback %s", model)
                return text
            logger.warning("Gemini model %s returned no text", model)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Gemini model %s failed: %s", model, exc)
    if last_exc:
        raise last_exc
    return ""


def generate_text(prompt: str, *, json_mode: bool = False) -> tuple[str | None, GeminiBackend]:
    """Generate text with Gemini. Returns ``(text_or_None, backend_used)``."""
    backend = resolve_backend()
    if backend == "none":
        return None, "none"
    try:
        text = _generate(prompt, backend, json_mode=json_mode)
        return (text or None), (backend if text else "none")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini generation failed on %s: %s", backend, exc)
        # Cross-backend fallback: Vertex failed but an AI Studio key is available.
        if backend == "vertex_ai" and settings.gemini_api_key:
            try:
                text = _generate(prompt, "ai_studio", json_mode=json_mode)
                return (text or None), ("ai_studio" if text else "none")
            except Exception:  # noqa: BLE001
                pass
        return None, "none"


def generate_json(prompt: str) -> tuple[dict[str, Any] | None, GeminiBackend]:
    """Generate JSON with Gemini (``response_mime_type=application/json``) and parse it robustly.

    Returns ``(parsed_dict_or_None, backend_used)``; ``None`` on no output or unparseable text.
    """
    text, backend = generate_text(prompt, json_mode=True)
    if not text:
        return None, backend
    data = _parse_json(text)
    return data, backend


def _parse_json(text: str) -> dict[str, Any] | None:
    """Parse model output as a JSON object, tolerating code fences and surrounding prose."""
    cleaned = text.strip()
    # Strip ```json ... ``` fences if present.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    for candidate in (cleaned, _first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _first_json_object(text: str) -> str | None:
    """Extract the first ``{...}`` block from text (handles models that wrap JSON in prose)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def gemini_status() -> dict[str, Any]:
    """Report the resolved Gemini backend, model, location, and safety threshold for diagnostics."""
    backend = resolve_backend()
    return {
        "model": settings.gemini_model,
        "fallback_model": settings.gemini_fallback_model or None,
        "backend": backend,
        "sdk": "google-genai",
        "vertex_configured": bool(settings.gcp_project_id),
        "ai_studio_configured": bool(settings.gemini_api_key),
        "active": backend != "none",
        "gcp_project": settings.gcp_project_id,
        "gcp_location": settings.gcp_location,
        "gemini_location": settings.gemini_location,
        "safety_threshold": settings.gemini_safety_threshold,
    }
