# Data Contract Guardian — ADK chat (Agent Builder playground)

Pattern from [consentops-agent](https://github.com/prabhakaran-jm/consentops-agent): a **standalone ADK package** that calls the hosted Cloud Run read-only API and optionally runs Fivetran MCP locally.

| Surface | Command |
| ------- | ------- |
| **Local ADK Web UI** | `./scripts/adk-playground-local.sh` |
| **Agent Engine playground** | `./scripts/deploy-adk-agent-engine.sh --recreate` |

## Layout

```
guardian-adk/
  guardian_assistant/
    agent.py           # root_agent + FunctionTools → Cloud Run /api/agent/*
    instructions.txt
    requirements.txt
```

## Local playground

```bash
pip install -r guardian-adk/guardian_assistant/requirements.txt
export GEMINI_API_KEY=your_key          # ADK model calls
export FIVETRAN_API_KEY=...             # optional native MCP
export FIVETRAN_API_SECRET=...
./scripts/adk-playground-local.sh
```

Open http://127.0.0.1:8081 → **guardian_assistant**.

## Agent Engine deploy

Uses an **isolated venv** (`.adk-deploy-venv/`) so Cloud Shell global Python (tensorflow/streamlit) does not conflict.

```bash
cd terraform && terraform apply   # creates ADK staging bucket
cd ..
gcloud auth application-default login
ADK_RECREATE=true ./scripts/deploy-adk-agent-engine.sh --recreate
```

Do **not** `pip install guardian-adk/.../requirements.txt` into Cloud Shell **global** Python — use the deploy script venv instead. The venv installs the same agent deps (`google-adk` + `google-cloud-aiplatform[agent_engines]`) needed because the SDK imports `root_agent` locally before upload.

Console playground URL is printed at the end. Engine id is saved to `guardian-adk/.agent_engine_id`.

### Fivetran MCP on Engine

Native stdio MCP is **off by default** on Agent Engine (`ADK_FIVETRAN_MCP_ENABLED=false`). The agent uses Cloud Run `/api/agent/fivetran` proxies instead — same read-only tools, no fastmcp conflict in the Engine venv.

See [docs/agent-builder-setup.md](../docs/agent-builder-setup.md) for the full guide.
