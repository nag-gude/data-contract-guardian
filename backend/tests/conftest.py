"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_PATH", "/tmp/guardian-test.db")
os.environ.setdefault("MOCK_FIVETRAN_MCP", "true")
os.environ.setdefault("MOCK_BIGQUERY", "true")

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)
