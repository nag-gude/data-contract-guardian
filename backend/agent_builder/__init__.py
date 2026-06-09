"""Google Cloud Agent Builder (ADK) package for Data Contract Guardian.

Houses the managed-agent definition the FastAPI backend delegates to when
``USE_AGENT_BUILDER=true`` and the ``google-adk`` SDK is installed. The agent reasons with
Gemini and reaches the real ``fivetran/fivetran-mcp`` server through an ADK ``McpToolset``,
so the same investigation can run either as a deterministic in-process loop or as a managed
Agent Builder turn.

Modules:
    agent       — the ADK ``Agent`` definition and ``run_guardian_turn`` entry point.
    mcp_config  — shared Fivetran MCPToolset construction and ADK availability probing.
"""