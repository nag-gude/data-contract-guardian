#!/usr/bin/env bash
# Deploy guardian_assistant to Vertex AI Agent Engine (Agent Builder playground).
# Uses an isolated venv so Cloud Shell global packages (tensorflow/streamlit) do not conflict.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.adk-deploy-venv"
REQ="$ROOT/scripts/requirements-adk-deploy.txt"

if [[ ! -d "$VENV" ]]; then
  echo "Creating deploy venv at .adk-deploy-venv ..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -q --upgrade pip
python -m pip install -q -r "$REQ"

if ! python -c "from google.adk.agents import Agent; from vertexai import agent_engines" 2>/dev/null; then
  echo "ERROR: deploy venv missing google-adk or vertexai.agent_engines after pip install." >&2
  echo "Try: rm -rf .adk-deploy-venv && ./scripts/deploy-adk-agent-engine.sh --recreate" >&2
  exit 1
fi

exec python scripts/deploy_adk_agent_engine.py "$@"
