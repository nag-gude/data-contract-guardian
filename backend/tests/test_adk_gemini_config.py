"""Tests for ADK Gemini / Vertex configuration."""

import os

import pytest

from agent_builder.gemini_config import adk_gemini_ready, build_adk_model, configure_adk_gemini_env


def test_configure_vertex_env_from_gcp_project(monkeypatch):
    monkeypatch.setattr("app.config.settings.gcp_project_id", "my-gcp-project")
    monkeypatch.setattr("app.config.settings.gemini_location", "us-central1")
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    monkeypatch.setattr("app.config.settings.gemini_backend", "auto")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    backend = configure_adk_gemini_env()

    assert backend == "vertex_ai"
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "my-gcp-project"
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "us-central1"


def test_build_adk_model_uses_vertex_gemini(monkeypatch):
    monkeypatch.setattr("app.config.settings.gcp_project_id", "my-gcp-project")
    monkeypatch.setattr("app.config.settings.gemini_location", "us-central1")
    monkeypatch.setattr("app.config.settings.gemini_model", "gemini-2.5-flash")
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    monkeypatch.setattr("app.config.settings.gemini_backend", "auto")

    model = build_adk_model()

    assert model.__class__.__name__ == "VertexGemini"
    assert model.model == "gemini-2.5-flash"


def test_adk_gemini_ready_false_without_credentials(monkeypatch):
    monkeypatch.setattr("app.config.settings.gcp_project_id", None)
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    monkeypatch.setattr("app.config.settings.gemini_backend", "auto")

    assert adk_gemini_ready() is False


def test_build_adk_model_raises_without_credentials(monkeypatch):
    monkeypatch.setattr("app.config.settings.gcp_project_id", None)
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    monkeypatch.setattr("app.config.settings.gemini_backend", "auto")

    with pytest.raises(RuntimeError, match="ADK requires Gemini credentials"):
        build_adk_model()
