"""Contracts router — list registered data contracts and register new ones.

Contracts are the source of truth for expectations and live as YAML files under
``settings.contracts_dir``; this router reads them via the loader and writes new ones back to
that directory so they are picked up on the next load.
"""

from fastapi import APIRouter, HTTPException

from app.schemas import DataContract
from app.services.contracts_loader import load_all_contracts
from app.config import settings

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("")
def list_contracts():
    """Return every registered data contract as a JSON list."""
    return [c.model_dump() for c in load_all_contracts()]


@router.post("")
def create_contract(contract: DataContract):
    """Persist a new contract as ``<contract_id>.yaml``; 409 if the id already exists."""
    settings.contracts_dir.mkdir(parents=True, exist_ok=True)
    path = settings.contracts_dir / f"{contract.contract_id}.yaml"
    if path.exists():
        raise HTTPException(409, "contract_id already exists")
    import yaml

    path.write_text(
        yaml.safe_dump(contract.model_dump(mode="json", exclude_none=True, by_alias=True), sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(path)}
