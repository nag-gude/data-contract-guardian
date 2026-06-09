"""FastAPI application entry point for Data Contract Guardian.

Builds the ASGI ``app``: configures CORS from ``settings.cors_origins`` (wildcard supported for
public demos), mounts every router under ``/api``, and exposes ``/health``. A spec-compatible
``/api/approve-remediation`` alias mirrors the incidents router so the human-in-the-loop endpoint
is reachable at the top level as well. The lifespan hook initialises the SQLite schema on startup.

Run locally with: ``uvicorn app.main:app --reload`` (from the ``backend`` directory).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.schemas import ApproveBody
from app.routers import agent, contracts, demo, incidents, validation
from app.services import incident_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create the database schema before serving requests."""
    init_db()
    yield


app = FastAPI(title="Data Contract Guardian API", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(contracts.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")
app.include_router(validation.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(agent.router, prefix="/api")


@app.post("/api/approve-remediation")
def approve_remediation_spec(body: ApproveBody):
    """Alias of POST /api/incidents/approve-remediation (spec compatibility)."""
    return incident_service.approve_remediation(body)


from app.services.agent_orchestrator import platform_status


@app.get("/health")
def health():
    """Liveness probe that also returns the platform/integration status snapshot."""
    return {"status": "ok", "platform": platform_status()}
