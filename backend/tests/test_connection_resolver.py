"""Tests for Fivetran connection alias resolution."""

from unittest.mock import patch

from app.services.fivetran_connection_resolver import (
    clear_resolution_cache,
    resolve_fivetran_connection_id,
)

AIRTABLE_CONN = {
    "id": "toll_donator",
    "service": "airtable",
    "schema": "airtable_network_appxzsmwynqrvmfcq",
}


def test_resolve_uses_env_slug_when_connection_exists(monkeypatch):
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "toll_donator")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[{**AIRTABLE_CONN, "schema": "hackathon"}],
    ):
        assert resolve_fivetran_connection_id("ft_airtable_network") == "toll_donator"


def test_resolve_matches_env_by_schema_name(monkeypatch):
    """FIVETRAN_CONNECTION_ID=hackathon resolves when schema is hackathon."""
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "hackathon")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[{**AIRTABLE_CONN, "schema": "hackathon"}],
    ):
        assert resolve_fivetran_connection_id("ft_airtable_network") == "toll_donator"


def test_resolve_never_returns_raw_env_when_list_empty(monkeypatch):
    """Empty list_connections must not pass hackathon as API connection id."""
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "hackathon")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[],
    ):
        assert resolve_fivetran_connection_id("ft_airtable_network") == "ft_airtable_network"


def test_resolve_direct_hackathon_ref_to_slug(monkeypatch):
    """When connector ref is hackathon (env hint), resolve to dashboard slug."""
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "hackathon")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[{**AIRTABLE_CONN, "schema": "hackathon"}],
    ):
        assert resolve_fivetran_connection_id("hackathon") == "toll_donator"


def test_resolve_falls_back_to_alias_when_env_unmatched(monkeypatch):
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "nonexistent_ref")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[AIRTABLE_CONN],
    ):
        assert resolve_fivetran_connection_id("ft_airtable_network") == "toll_donator"


def test_skip_env_override_bypasses_invalid_env(monkeypatch):
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "hackathon")
    clear_resolution_cache()

    with patch(
        "app.services.fivetran_connection_resolver._fetch_connection_items",
        return_value=[AIRTABLE_CONN],
    ):
        assert (
            resolve_fivetran_connection_id("ft_airtable_network", skip_env_override=True)
            == "toll_donator"
        )
