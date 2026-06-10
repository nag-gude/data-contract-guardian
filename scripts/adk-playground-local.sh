#!/usr/bin/env bash
# Local ADK Web UI — same agent as Agent Engine playground.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export GEMINI_API_KEY="${GEMINI_API_KEY:-}"
export FIVETRAN_API_KEY="${FIVETRAN_API_KEY:-}"
export FIVETRAN_API_SECRET="${FIVETRAN_API_SECRET:-}"
export ADK_FIVETRAN_MCP_ENABLED="${ADK_FIVETRAN_MCP_ENABLED:-true}"

PORT="${ADK_WEB_PORT:-8081}"
echo "ADK Web UI: http://127.0.0.1:${PORT} → select guardian_assistant"
cd "$ROOT"
exec adk web guardian-adk --port "$PORT"
