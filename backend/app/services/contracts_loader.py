"""Load and cache data contracts from the ``contracts/`` directory.

Reads YAML/JSON contract files into validated ``DataContract`` models. Parsing is cached per
file and invalidated by mtime, so the hot ``get_contract`` / ``load_all_contracts`` paths don't
re-read and re-parse every file on each validation while still picking up edits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.schemas import DataContract
from app.config import settings


# Per-file parse cache keyed by path → (mtime_ns, parsed contract). Avoids re-reading and
# re-parsing every YAML/JSON file on each get_contract / validate call, while still picking up
# edits (cache entry is invalidated when the file's mtime changes).
_PARSE_CACHE: dict[Path, tuple[int, DataContract]] = {}


def _load_one(path: Path) -> DataContract:
    """Parse one contract file into a ``DataContract``, served from the mtime cache if unchanged."""
    mtime = path.stat().st_mtime_ns
    cached = _PARSE_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data: dict[str, Any] = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    contract = DataContract.model_validate(data)
    contract = _resolve_bq_project(contract)
    contract = _resolve_bq_dataset(contract)
    contract = _resolve_connector_alias(contract)
    _PARSE_CACHE[path] = (mtime, contract)
    return contract


def _resolve_connector_alias(contract: DataContract) -> DataContract:
    """Map env hints (e.g. hackathon) back to the contract alias for MCP resolution."""
    cid = (contract.fivetran_connector_id or "").strip()
    env_ref = (settings.fivetran_connection_id or "").strip()
    if cid.startswith("ft_"):
        return contract
    if cid == env_ref or cid in {"hackathon"}:
        return contract.model_copy(update={"fivetran_connector_id": "ft_airtable_network"})
    return contract


def _resolve_bq_project(contract: DataContract) -> DataContract:
    """Use GCP_PROJECT_ID when contract YAML still has the demo placeholder."""
    project = contract.bq_project
    if project in (None, "", "demo-gcp-project") and settings.gcp_project_id:
        return contract.model_copy(update={"bq_project": settings.gcp_project_id})
    return contract


def _resolve_bq_dataset(contract: DataContract) -> DataContract:
    """Use BQ_DATASET when contract YAML still has the demo placeholder ``network``."""
    dataset = contract.bq_dataset
    if dataset in (None, "", "network") and settings.bq_dataset:
        return contract.model_copy(update={"bq_dataset": settings.bq_dataset})
    return contract


def load_all_contracts() -> list[DataContract]:
    """Load every contract file in ``settings.contracts_dir``, sorted by filename."""
    base = settings.contracts_dir
    if not base.exists():
        return []
    out: list[DataContract] = []
    for p in sorted(base.iterdir()):
        if p.suffix.lower() in {".yaml", ".yml", ".json"}:
            out.append(_load_one(p))
    return out


def get_contract(contract_id: str) -> DataContract | None:
    """Return the contract with the given id, or ``None`` if no file defines it."""
    for c in load_all_contracts():
        if c.contract_id == contract_id:
            return c
    return None
