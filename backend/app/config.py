"""Application configuration for Data Contract Guardian.

Centralises every tunable as a Pydantic ``Settings`` model sourced from environment variables
(and an optional ``.env`` file). Defaults are demo-safe — mock Fivetran MCP, mock BigQuery, and
Gemini auto-detection — so the app runs locally with zero credentials, while the same knobs
promote it to live Vertex AI, the real Fivetran MCP server, and live BigQuery in production.

Import the module-level ``settings`` singleton anywhere config is needed.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_contracts_dir() -> Path:
    """Repo-root ``contracts/`` directory, resolved relative to this file."""
    return Path(__file__).resolve().parent.parent.parent / "contracts"


def _default_database_path() -> Path:
    """Default SQLite path (``backend/data/guardian.db``) for local/demo persistence."""
    return Path(__file__).resolve().parent.parent / "data" / "guardian.db"


class Settings(BaseSettings):
    """Typed application settings, populated from the environment / ``.env``.

    Groups: paths, CORS, Gemini (model/backend/location/safety), Agent Builder/ADK, Slack,
    Fivetran MCP (transport + credentials), and BigQuery. The ``use_*`` properties collapse
    several flags into a single "is this capability live?" decision used across the services.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    contracts_dir: Path = Field(default_factory=_default_contracts_dir)
    database_path: Path = Field(default_factory=_default_database_path)

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Gemini — Vertex AI (GCP) preferred; AI Studio API key fallback.
    # Default is a Gemini 3 model; called through the modern google-genai SDK (the legacy
    # vertexai SDK does not reliably support Gemini 3 and returned empty text).
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    # Fallback model tried when the primary returns no text or is unavailable in the region,
    # so the agent always produces a real RCA. Set empty to disable.
    gemini_fallback_model: str = "gemini-2.5-flash"
    gemini_backend: str = "auto"  # auto | vertex | ai_studio
    # Safety guardrails applied to every Gemini call.
    # One of: BLOCK_NONE | BLOCK_ONLY_HIGH | BLOCK_MEDIUM_AND_ABOVE | BLOCK_LOW_AND_ABOVE.
    gemini_safety_threshold: str = "BLOCK_ONLY_HIGH"
    gcp_project_id: str | None = None
    # Fivetran destination dataset slug when contract YAML still has demo placeholder ``network``.
    bq_dataset: str | None = None
    gcp_location: str = "us-central1"  # Cloud Run, Artifact Registry, BigQuery dataset region
    # Vertex AI region for Gemini — align with Cloud Run (gemini-3.5-flash on us-central1).
    gemini_location: str = "us-central1"

    # Google Cloud Agent Builder / ADK orchestration
    use_agent_builder: bool = True
    require_agent_builder: bool = False
    agent_name: str = "data_contract_guardian"

    slack_webhook_url: str | None = None

    # Fivetran MCP — stdio → github.com/fivetran/fivetran-mcp
    mock_fivetran_mcp: bool = True
    fivetran_api_key: str | None = None
    fivetran_api_secret: str | None = None
    # Real Fivetran connection id when contracts use friendly alias ft_airtable_network
    fivetran_connection_id: str | None = None
    fivetran_allow_writes: bool = False
    fivetran_mcp_command: str = "uvx"
    fivetran_mcp_args: str = "--from,git+https://github.com/fivetran/fivetran-mcp,fivetran-mcp"

    # BigQuery — live INFORMATION_SCHEMA when false + GCP credentials
    mock_bigquery: bool = True

    @property
    def fivetran_mcp_args_list(self) -> list[str]:
        """``fivetran_mcp_args`` parsed from its comma-separated form into an argv list."""
        return [a.strip() for a in self.fivetran_mcp_args.split(",") if a.strip()]

    @property
    def fivetran_credentials_configured(self) -> bool:
        """True when both Fivetran API key and secret are present."""
        return bool(self.fivetran_api_key and self.fivetran_api_secret)

    @property
    def use_real_fivetran(self) -> bool:
        """True when the live Fivetran MCP path should run (not mocked and credentials set)."""
        return not self.mock_fivetran_mcp and self.fivetran_credentials_configured

    @property
    def use_live_bigquery(self) -> bool:
        """True when live BigQuery checks should run (not mocked and a GCP project is set)."""
        return not self.mock_bigquery and bool(self.gcp_project_id)


settings = Settings()
