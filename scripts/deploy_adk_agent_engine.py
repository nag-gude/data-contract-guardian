#!/usr/bin/env python3
"""Deploy guardian_assistant to Vertex AI Agent Engine (Agent Builder playground).

Adapted from consentops-agent (github.com/prabhakaran-jm/consentops-agent).
Use --recreate after agent.py or requirements.txt changes (update() does not rebuild).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "guardian-adk" / "guardian_assistant"
STAGING_DIR = ROOT / ".adk-staging"
ID_FILE = ROOT / "guardian-adk" / ".agent_engine_id"
DISPLAY_NAME = os.environ.get("ADK_DISPLAY_NAME", "Data Contract Guardian")
APP_NAME = AGENT_DIR.name
DEFAULT_GUARDIAN_API = "https://data-contract-guardian-api-920722415791.us-central1.run.app"
DEFAULT_GUARDIAN_UI = "https://data-contract-guardian-ui-920722415791.us-central1.run.app"

_AGENT_ENGINE_APP = """\
from vertexai.preview.reasoning_engines import AdkApp
from guardian_assistant.agent import root_agent

adk_app = AdkApp(
    agent=root_agent,
    enable_tracing=True,
)
"""

_REGISTER_OPERATIONS = {
    "": ["get_session", "list_sessions", "create_session", "delete_session"],
    "async": [
        "async_get_session",
        "async_list_sessions",
        "async_create_session",
        "async_delete_session",
    ],
    "async_stream": ["async_stream_query"],
    "stream": ["stream_query", "streaming_agent_run_with_events"],
}


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _terraform_output(name: str) -> str | None:
    try:
        result = subprocess.run(
            ["terraform", "-chdir=terraform", "output", "-raw", name],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _secret_ref(secret_id: str, version: str = "latest") -> Any:
    from google.cloud.aiplatform_v1.types import env_var

    return env_var.SecretRef(secret=secret_id, version=version)


def _build_env_vars(project: str) -> dict[str, Any]:
    model = os.environ.get("ADK_GEMINI_MODEL", "gemini-2.5-flash")
    guardian_api = os.environ.get("GUARDIAN_API_BASE_URL", _terraform_output("backend_url") or DEFAULT_GUARDIAN_API).rstrip("/")
    guardian_ui = os.environ.get("GUARDIAN_UI_BASE_URL", _terraform_output("frontend_url") or DEFAULT_GUARDIAN_UI).rstrip("/")

    # Native stdio MCP off on Engine by default (fastmcp/httpx conflicts with ADK runtime).
    mcp_enabled = os.environ.get("ADK_FIVETRAN_MCP_ENABLED", "false").lower() in ("1", "true", "yes")

    env: dict[str, Any] = {
        "CLOUD_ML_PROJECT_ID": project,
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "GEMINI_MODEL": model,
        "ADK_GEMINI_MODEL": model,
        "GUARDIAN_API_BASE_URL": guardian_api,
        "GUARDIAN_UI_BASE_URL": guardian_ui,
        "ADK_FIVETRAN_MCP_ENABLED": "true" if mcp_enabled else "false",
    }

    if mcp_enabled:
        env["FIVETRAN_ALLOW_WRITES"] = "false"
        env["FIVETRAN_MCP_COMMAND"] = os.environ.get("ADK_FIVETRAN_MCP_COMMAND", "fivetran-mcp")
        use_secrets = os.environ.get("ADK_FIVETRAN_PLAIN_ENV", "").lower() not in ("1", "true", "yes")
        key_secret = os.environ.get("ADK_FIVETRAN_KEY_SECRET_ID", "dcg-fivetran-api-key")
        secret_secret = os.environ.get("ADK_FIVETRAN_API_SECRET_ID", "dcg-fivetran-api-secret")
        secret_version = os.environ.get("ADK_FIVETRAN_SECRET_VERSION", "latest")
        if use_secrets:
            env["FIVETRAN_API_KEY"] = _secret_ref(key_secret, secret_version)
            env["FIVETRAN_API_SECRET"] = _secret_ref(secret_secret, secret_version)
        else:
            api_key = os.environ.get("FIVETRAN_API_KEY", "").strip()
            api_secret = os.environ.get("FIVETRAN_API_SECRET", "").strip()
            if api_key and api_secret:
                env["FIVETRAN_API_KEY"] = api_key
                env["FIVETRAN_API_SECRET"] = api_secret

    return env


def _prepare_staging() -> Path:
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    agent_dest = STAGING_DIR / APP_NAME
    shutil.copytree(
        AGENT_DIR,
        agent_dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (STAGING_DIR / "agent_engine_app.py").write_text(_AGENT_ENGINE_APP, encoding="utf-8")
    return STAGING_DIR


def _patch_module_agent_clone() -> Any:
    import vertexai.agent_engines._agent_engines as ae_mod

    original = ae_mod.ModuleAgent.clone

    def clone_with_framework(self: ae_mod.ModuleAgent) -> ae_mod.ModuleAgent:
        cloned = original(self)
        framework = getattr(self, "agent_framework", None)
        if framework:
            cloned.agent_framework = framework
        return cloned

    ae_mod.ModuleAgent.clone = clone_with_framework  # type: ignore[method-assign]
    return original


def _should_skip_staging_file(file_path: Path) -> bool:
    if "__pycache__" in file_path.parts:
        return True
    name = file_path.name
    return name.startswith("._") or name in {".DS_Store", "Thumbs.db"}


def _patch_upload_extra_packages() -> Any:
    import vertexai.agent_engines._agent_engines as ae_mod

    original = ae_mod._upload_extra_packages

    def clean_upload(*, extra_packages, gcs_bucket, gcs_dir_name, logger=ae_mod._LOGGER):
        logger.info("Creating in-memory tarfile of extra_packages (relative arcnames)")
        tar_fileobj = io.BytesIO()
        with tarfile.open(fileobj=tar_fileobj, mode="w|gz") as tar:
            for package_dir in extra_packages:
                root = Path(package_dir)
                for file_path in root.rglob("*"):
                    if not file_path.is_file() or _should_skip_staging_file(file_path):
                        continue
                    arcname = file_path.relative_to(root).as_posix()
                    tar.add(file_path, arcname=arcname)
        tar_fileobj.seek(0)
        blob = gcs_bucket.blob(f"{gcs_dir_name}/{ae_mod._EXTRA_PACKAGES_FILE}")
        blob.upload_from_string(tar_fileobj.read())

    ae_mod._upload_extra_packages = clean_upload
    return original


def _engine_resource_name(project: str, region: str, engine_id: str) -> str:
    return f"projects/{project}/locations/{region}/reasoningEngines/{engine_id}"


def _delete_engine(*, project: str, region: str, engine_id: str) -> None:
    from vertexai import agent_engines

    resource_name = _engine_resource_name(project, region, engine_id)
    print(f"Deleting Agent Engine {engine_id}...")
    agent_engines.delete(resource_name, force=True)
    import time

    time.sleep(int(os.environ.get("ADK_DELETE_WAIT_SECONDS", "30")))


def _deploy(
    *,
    project: str,
    region: str,
    staging_bucket: str,
    agent_engine_id: str | None,
    service_account: str | None,
) -> str | None:
    import vertexai
    from vertexai import agent_engines

    package_dir = _prepare_staging()
    sys.path.insert(0, str(package_dir))
    vertexai.init(project=project, location=region, staging_bucket=staging_bucket)

    agent_engine = agent_engines.ModuleAgent(
        module_name="agent_engine_app",
        agent_name="adk_app",
        register_operations=_REGISTER_OPERATIONS,
        sys_paths=["."],
        agent_framework="google-adk",
    )

    agent_config: dict[str, Any] = {
        "display_name": DISPLAY_NAME,
        "description": (
            "Read-only Data Contract Guardian: Fivetran MCP, contract validation, "
            "evidence-grounded RCA. Approval in Guardian web UI."
        ),
        "extra_packages": [str(package_dir.resolve())],
        "requirements": str((package_dir / APP_NAME / "requirements.txt").resolve()),
        "env_vars": _build_env_vars(project),
        "agent_engine": agent_engine,
        "min_instances": int(os.environ.get("ADK_MIN_INSTANCES", "1")),
        "max_instances": int(os.environ.get("ADK_MAX_INSTANCES", "2")),
    }
    if service_account:
        agent_config["service_account"] = service_account

    create_attempts = int(os.environ.get("ADK_CREATE_RETRIES", "3"))
    last_exc: Exception | None = None

    for attempt in range(1, create_attempts + 1):
        try:
            if agent_engine_id:
                resource_name = _engine_resource_name(project, region, agent_engine_id)
                result = agent_engines.update(resource_name=resource_name, **agent_config)
            else:
                result = agent_engines.create(**agent_config)
            resource_name = getattr(result, "resource_name", None) or str(result)
            match = re.search(r"reasoningEngines/(\d+)", resource_name)
            return match.group(1) if match else None
        except Exception as exc:
            last_exc = exc
            from google.api_core import exceptions as gcp_exceptions

            if not isinstance(exc, gcp_exceptions.InternalServerError) or attempt == create_attempts:
                raise
            import time

            time.sleep(30 * attempt)

    if last_exc:
        raise last_exc
    return None


def _smoke_test(*, project: str, region: str, engine_id: str, timeout_s: int = 300) -> bool:
    import time

    from vertexai import agent_engines

    resource_name = _engine_resource_name(project, region, engine_id)
    deadline = time.time() + timeout_s
    attempt = 0
    last_error: Exception | None = None
    print(f"\nSmoke test: create_session (timeout {timeout_s}s)...")
    while time.time() < deadline:
        attempt += 1
        try:
            engine = agent_engines.get(resource_name)
            session = engine.create_session(user_id="smoke")
            sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", session)
            print(f" Smoke test PASSED (attempt {attempt}): session {sid}")
            return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f" attempt {attempt}: not ready ({str(exc)[:140]})")
            time.sleep(15)
    print(f"SMOKE TEST FAILED: {last_error}", file=sys.stderr)
    return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy Guardian ADK agent to Agent Engine.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing engine and create fresh (required after agent.py changes).",
    )
    return parser.parse_args()


def _ensure_agent_engines_sdk() -> None:
    """Require deploy venv packages (google-adk + agent_engines)."""
    missing: list[str] = []
    try:
        import vertexai.agent_engines  # noqa: F401
    except ModuleNotFoundError:
        missing.append("vertexai.agent_engines (google-cloud-aiplatform[agent_engines])")
    try:
        from google.adk.agents import Agent  # noqa: F401
    except ModuleNotFoundError:
        missing.append("google.adk (google-adk)")
    if missing:
        print(
            "ERROR: deploy environment missing: " + ", ".join(missing) + "\n"
            "Run (uses isolated .adk-deploy-venv/):\n"
            "  ./scripts/deploy-adk-agent-engine.sh --recreate\n"
            "If the venv is stale:\n"
            "  rm -rf .adk-deploy-venv && ./scripts/deploy-adk-agent-engine.sh --recreate",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> int:
    args = _parse_args()
    recreate = args.recreate or os.environ.get("ADK_RECREATE", "").lower() in ("1", "true", "yes")

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    _load_dotenv(ROOT / ".env")
    _ensure_agent_engines_sdk()

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    region = os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("GCP_REGION") or "us-central1"
    staging_bucket = os.environ.get("ADK_STAGING_BUCKET") or _terraform_output("adk_staging_bucket")
    service_account = os.environ.get("ADK_SERVICE_ACCOUNT") or _terraform_output("backend_service_account")

    if not project:
        print("ERROR: Set GCP_PROJECT_ID in .env", file=sys.stderr)
        return 1
    if not staging_bucket:
        print("ERROR: Set ADK_STAGING_BUCKET or run: cd terraform && terraform apply", file=sys.stderr)
        return 1
    if not AGENT_DIR.is_dir():
        print(f"ERROR: Agent folder not found: {AGENT_DIR}", file=sys.stderr)
        return 1

    agent_engine_id: str | None = None
    if ID_FILE.is_file():
        agent_engine_id = ID_FILE.read_text(encoding="utf-8").strip() or None

    if recreate and agent_engine_id:
        import vertexai

        vertexai.init(project=project, location=region, staging_bucket=staging_bucket)
        try:
            _delete_engine(project=project, region=region, engine_id=agent_engine_id)
        except Exception as exc:
            print(f"WARNING: Delete failed ({exc})", file=sys.stderr)
        ID_FILE.unlink(missing_ok=True)
        agent_engine_id = None
    elif agent_engine_id:
        print(f"Updating Agent Engine {agent_engine_id} (use --recreate after code changes)")

    print(f"Deploying {AGENT_DIR.relative_to(ROOT)}...")
    print(f" project={project} region={region} staging={staging_bucket}")

    restore_clone = _patch_module_agent_clone()
    restore_upload = _patch_upload_extra_packages()
    try:
        engine_id = _deploy(
            project=project,
            region=region,
            staging_bucket=staging_bucket,
            agent_engine_id=agent_engine_id,
            service_account=service_account,
        )
    except Exception as exc:
        import traceback
        from google.api_core import exceptions as gcp_exceptions

        if agent_engine_id and isinstance(exc, gcp_exceptions.NotFound):
            print(f"Agent Engine {agent_engine_id} not found — creating a new one...", file=sys.stderr)
            ID_FILE.unlink(missing_ok=True)
            try:
                engine_id = _deploy(
                    project=project,
                    region=region,
                    staging_bucket=staging_bucket,
                    agent_engine_id=None,
                    service_account=service_account,
                )
            except Exception as retry_exc:
                print(f"Deploy failed: {retry_exc}", file=sys.stderr)
                traceback.print_exc()
                return 1
        else:
            print(f"Deploy failed: {exc}", file=sys.stderr)
            traceback.print_exc()
            return 1
    finally:
        import vertexai.agent_engines._agent_engines as ae_mod

        ae_mod.ModuleAgent.clone = restore_clone  # type: ignore[method-assign]
        ae_mod._upload_extra_packages = restore_upload
        shutil.rmtree(STAGING_DIR, ignore_errors=True)

    if engine_id:
        ID_FILE.write_text(engine_id, encoding="utf-8")
        playground = (
            "https://console.cloud.google.com/agent-platform/runtimes/locations/"
            f"{region}/agent-engines/{engine_id}/playground?project={project}"
        )
        print(f"Saved engine id to {ID_FILE.relative_to(ROOT)}")
        print(f"Agent Engine playground: {playground}")

        if os.environ.get("ADK_SKIP_SMOKE", "").lower() not in ("1", "true", "yes"):
            if not _smoke_test(project=project, region=region, engine_id=engine_id):
                return 1

    print(f'\nDone. Chat with "{DISPLAY_NAME}" in the Agent Engine playground.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
