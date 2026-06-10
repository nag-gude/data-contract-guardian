"""FastAPI routers for the Data Contract Guardian API.

Each module mounts one resource group under the ``/api`` prefix:
    contracts  — list/register YAML data contracts.
    validation — run checks across contracts and list past validation runs.
    incidents  — list/inspect incidents and approve or reject remediations (HITL).
    agent      — multi-step agent investigation, demo pipeline, and platform status.
    demo       — seed mock warehouse state for reproducible failing/passing scenarios.
"""