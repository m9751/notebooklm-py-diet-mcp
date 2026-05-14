"""
NotebookLM Diet MCP Server
A lightweight MCP server exposing Google NotebookLM capabilities as
workflow-oriented tools for AI agents in Cursor, Claude Code, and
other MCP-compatible clients.

Built on top of notebooklm-py: https://github.com/teng-lin/notebooklm-py

Requires:
    - notebooklm-py >= 0.3.2
    - mcp[cli] >= 1.0.0
    - A valid NotebookLM authentication session (run: notebooklm login)

Account selection:
    The server reads NOTEBOOKLM_HOME to determine the initial account.
    Accounts can be switched at runtime via the switch_account tool,
    and the choice is persisted in ~/.notebooklm-active.json so it
    survives server restarts.
"""

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from notebooklm import NotebookLMClient

ACTIVE_PROFILE_PATH = Path.home() / ".notebooklm-active.json"

DEFAULT_PROFILES = {
    "personal": ".notebooklm",
    "work": ".notebooklm-work",
    "design": ".notebooklm-design",
}


def _resolve_profile_dir(name: str) -> Path:
    """Turn a profile name or path into an absolute directory."""
    if os.path.isabs(name):
        return Path(name)
    suffix = DEFAULT_PROFILES.get(name.lower(), f".notebooklm-{name.lower()}")
    return Path.home() / suffix


def _read_active_profile() -> str | None:
    """Read the persisted active profile name, if any."""
    try:
        data = json.loads(ACTIVE_PROFILE_PATH.read_text(encoding="utf-8"))
        return data.get("active")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def _write_active_profile(name: str) -> None:
    """Persist the active profile name."""
    ACTIVE_PROFILE_PATH.write_text(
        json.dumps({"active": name}, indent=2),
        encoding="utf-8",
    )


def _current_profile_name() -> str:
    """Determine the current profile name from persisted state or env."""
    saved = _read_active_profile()
    if saved:
        return saved

    home = os.environ.get("NOTEBOOKLM_HOME", "")
    if home:
        folder = os.path.basename(os.path.expanduser(home))
        for name, suffix in DEFAULT_PROFILES.items():
            if folder == suffix:
                return name
        return folder.replace(".notebooklm-", "").replace(".notebooklm", "personal")

    return "personal"


@dataclass
class AppContext:
    """Application context with a switchable NotebookLM client."""

    client: NotebookLMClient | None
    profile: str


def _find_cli() -> Path | None:
    """Locate the notebooklm CLI executable in the current environment."""
    venv_dir = Path(sys.executable).parent
    for name in ("notebooklm", "notebooklm.exe"):
        p = venv_dir / name
        if p.exists():
            return p
    return None


async def _run_login(profile: str, ctx: Context | None = None) -> bool:
    """Launch notebooklm login for a profile and wait for completion."""
    cli = _find_cli()
    if not cli:
        return False

    target_dir = _resolve_profile_dir(profile)
    target_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["NOTEBOOKLM_HOME"] = str(target_dir)

    if ctx:
        await ctx.info(
            f"Session expired for '{profile}'. "
            "Launching browser for re-authentication -- "
            "please sign into your Google account."
        )

    try:
        process = subprocess.Popen(
            [str(cli), "login"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _stdout, _stderr = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, process.communicate),
            timeout=300,
        )
    except asyncio.TimeoutError:
        with suppress(Exception):
            process.kill()
        return False
    except Exception:
        return False

    from notebooklm.paths import get_storage_path

    storage_file = get_storage_path()
    return storage_file.exists() and process.returncode == 0


async def _create_client(profile: str) -> NotebookLMClient:
    """Create and initialise a NotebookLM client for the given profile."""
    home_env = os.environ.get("NOTEBOOKLM_HOME")
    if home_env:
        profile_dir = Path(home_env)
    else:
        profile_dir = _resolve_profile_dir(profile)
        os.environ["NOTEBOOKLM_HOME"] = str(profile_dir)
    from notebooklm.paths import get_storage_path

    storage_path = get_storage_path()
    client = await NotebookLMClient.from_storage(path=str(storage_path))
    if hasattr(client, "__aenter__"):
        await client.__aenter__()
    return client


async def _ensure_authenticated(
    app: "AppContext",
    ctx: Context,
) -> bool:
    """Test the current session and re-authenticate if expired.

    Handles three cases:
    1. No client at all -- triggers login.
    2. Client exists but session is stale -- triggers re-login.
    3. Client exists and session is valid -- returns immediately.
    """
    if app.client is not None:
        try:
            await app.client.notebooks.list()
            return True
        except Exception:
            pass

    # CSRF tokens expire in minutes — try recreating the client from stored
    # cookies before falling back to browser login.
    try:
        if app.client is not None:
            with suppress(Exception):
                await app.client.__aexit__(None, None, None)
        app.client = await _create_client(app.profile)
        await app.client.notebooks.list()
        return True
    except Exception:
        pass

    # Before attempting a headless browser login (which can't open a GUI),
    # try copying cookies from the default profile — works when the user has
    # logged in normally via `notebooklm login` without NOTEBOOKLM_HOME set.
    default_storage = Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json"
    home_env = os.environ.get("NOTEBOOKLM_HOME")
    diet_storage = (
        (Path(home_env) if home_env else _resolve_profile_dir(app.profile))
        / "profiles"
        / "default"
        / "storage_state.json"
    )
    if default_storage.exists() and default_storage != diet_storage:
        try:
            import shutil

            shutil.copy2(str(default_storage), str(diet_storage))
            app.client = await _create_client(app.profile)
            await app.client.notebooks.list()
            await ctx.info("Re-authenticated by syncing cookies from default profile.")
            return True
        except Exception:
            pass

    if app.client is None:
        await ctx.info(
            "No credentials found. Launching browser for authentication -- please sign into your Google account."
        )
    else:
        await ctx.info("Session expired. Launching browser for re-authentication...")

    success = await _run_login(app.profile, ctx)
    if not success:
        await ctx.error("Automatic re-authentication failed. Please run 'notebooklm login' manually in your terminal.")
        return False

    if app.client is not None:
        with suppress(Exception):
            await app.client.__aexit__(None, None, None)

    app.client = await _create_client(app.profile)
    await ctx.info("Authentication successful. Resuming operation.")
    return True


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage NotebookLM client lifecycle."""
    profile = _current_profile_name()
    home_env = os.environ.get("NOTEBOOKLM_HOME")
    if home_env:
        profile_dir = Path(home_env)
    else:
        profile_dir = _resolve_profile_dir(profile)
        os.environ["NOTEBOOKLM_HOME"] = str(profile_dir)
    from notebooklm.paths import get_storage_path

    storage_file = get_storage_path()

    client = None
    if storage_file.exists():
        try:
            client = await _create_client(profile)
        except (ValueError, Exception):
            client = None

    ctx = AppContext(client=client, profile=profile)
    try:
        yield ctx
    finally:
        if ctx.client is not None:
            with suppress(Exception):
                await ctx.client.__aexit__(None, None, None)


mcp = FastMCP("NotebookLM", lifespan=app_lifespan)


# ============================================================================
# RESOURCES
# ============================================================================


@mcp.resource("notebooklm://notebooks")
async def list_notebooks(ctx: Context[ServerSession, AppContext]) -> str:
    """List all NotebookLM notebooks with IDs and titles."""
    app = ctx.request_context.lifespan_context
    if app.client is None:
        return (
            "Not authenticated. Please call any tool (e.g. list_notebooks_tool) "
            "first to trigger automatic authentication."
        )

    try:
        notebooks = await app.client.notebooks.list()
    except Exception:
        return (
            "Session expired. Please call any tool (e.g. list_notebooks_tool) "
            "to trigger automatic re-authentication, then retry this resource."
        )

    if not notebooks:
        return "No notebooks found."

    result = "# Available NotebookLM Notebooks\n\n"
    for nb in notebooks:
        result += f"- **{nb.title}** (ID: `{nb.id}`)\n"

    return result


@mcp.resource("notebooklm://notebook/{notebook_id}")
async def get_notebook_info(notebook_id: str, ctx: Context[ServerSession, AppContext]) -> str:
    """Get detailed information about a specific notebook."""
    app = ctx.request_context.lifespan_context
    if app.client is None:
        return (
            "Not authenticated. Please call any tool (e.g. list_notebooks_tool) "
            "first to trigger automatic authentication."
        )

    try:
        notebooks = await app.client.notebooks.list()
    except Exception:
        return (
            "Session expired. Please call any tool (e.g. list_notebooks_tool) "
            "to trigger automatic re-authentication, then retry this resource."
        )

    notebook = next((nb for nb in notebooks if nb.id == notebook_id), None)

    if not notebook:
        return f"Notebook {notebook_id} not found."

    sources = await app.client.sources.list(notebook_id)

    result = f"# Notebook: {notebook.title}\n\n"
    result += f"**ID:** `{notebook_id}`\n\n"
    result += f"## Sources ({len(sources)})\n\n"

    for source in sources:
        result += f"- {source.title}\n"

    return result


# ============================================================================
# TOOLS -- Notebooks
# ============================================================================


@mcp.tool()
async def list_notebooks_tool(ctx: Context[ServerSession, AppContext]) -> dict:
    """List all NotebookLM notebooks.

    Returns a dictionary with notebook titles and IDs.
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    await ctx.info("Fetching notebooks...")
    notebooks = await app.client.notebooks.list()

    return {"count": len(notebooks), "notebooks": [{"id": nb.id, "title": nb.title} for nb in notebooks]}


@mcp.tool()
async def create_notebook(title: str, ctx: Context[ServerSession, AppContext]) -> dict:
    """Create a new NotebookLM notebook.

    Args:
        title: Title for the new notebook

    Returns:
        Dictionary with notebook ID and title
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    await ctx.info(f"Creating notebook: {title}")
    notebook = await app.client.notebooks.create(title)

    return {"id": notebook.id, "title": notebook.title, "success": True}


# ============================================================================
# TOOLS -- Sources
# ============================================================================


@mcp.tool()
async def list_sources(
    notebook_id: str,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """List all sources in a notebook.

    Args:
        notebook_id: ID of the notebook

    Returns:
        Dictionary with source count and source details
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    sources = await app.client.sources.list(notebook_id)
    return {
        "count": len(sources),
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "kind": getattr(s, "kind", None),
                "status": getattr(s, "status", None),
            }
            for s in sources
        ],
    }


@mcp.tool()
async def add_sources(
    notebook_id: str,
    sources: str,
    wait: bool = True,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Add multiple sources to a notebook in a single call.

    Each source is a dictionary with a "type" and "value" field.
    Supported types: "url", "text", "file".
    Text sources also require a "title" field.

    Args:
        notebook_id: ID of the notebook
        sources: JSON array of sources, e.g.
            [{"type": "url", "value": "https://example.com"},
             {"type": "text", "value": "Content here", "title": "My Notes"},
             {"type": "file", "value": "/path/to/document.pdf"}]
        wait: Whether to wait for processing to complete

    Returns:
        Dictionary with results for each source
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    try:
        parsed = json.loads(sources) if isinstance(sources, str) else sources
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in sources parameter: {e}"}

    if not isinstance(parsed, list):
        return {"error": "sources must be a JSON array"}

    results = []
    for i, src in enumerate(parsed):
        src_type = src.get("type", "").lower()
        value = src.get("value", "")
        await ctx.info(f"Adding source {i + 1}/{len(parsed)}: {src_type}")
        try:
            if src_type == "url":
                added = await app.client.sources.add_url(notebook_id, value, wait=wait)
            elif src_type == "text":
                title = src.get("title", f"Text source {i + 1}")
                added = await app.client.sources.add_text(notebook_id, title, value)
            elif src_type == "file":
                added = await app.client.sources.add_file(notebook_id, value, wait=wait)
            else:
                results.append({"index": i, "error": f"Unknown source type: {src_type}"})
                continue
            results.append({"index": i, "id": added.id, "title": added.title, "success": True})
        except Exception as e:
            results.append({"index": i, "error": str(e)})

    succeeded = sum(1 for r in results if r.get("success"))
    return {"total": len(parsed), "succeeded": succeeded, "results": results}


# ============================================================================
# TOOLS -- Chat
# ============================================================================


@mcp.tool()
async def ask_question(
    notebook_id: str,
    question: str,
    source_ids: str = "",
    conversation_id: str = "",
    persona: str = "",
    response_length: str = "",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Ask a question to a NotebookLM notebook and get an AI-generated answer.

    Args:
        notebook_id: ID of the notebook to query
        question: The question to ask
        source_ids: Comma-separated source IDs to restrict the query (optional)
        conversation_id: Continue an existing conversation thread (optional)
        persona: Set chat persona before asking (optional). Use a descriptive
            role like "tutor", "analyst", "concise summariser". Cleared if empty.
        response_length: Set response length before asking (optional).
            One of: short, medium, long. Cleared if empty.

    Returns:
        Dictionary with the answer and citation information
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    parsed_source_ids = [s.strip() for s in source_ids.split(",") if s.strip()] if source_ids else None

    if persona or response_length:
        configure_kwargs: dict = {}
        if persona:
            configure_kwargs["goal"] = "custom"
            configure_kwargs["custom_prompt"] = persona
        if response_length:
            configure_kwargs["response_length"] = response_length
        with suppress(Exception):
            await app.client.chat.configure(notebook_id, **configure_kwargs)

    await ctx.info(f"Querying notebook: {notebook_id}")
    await ctx.report_progress(0.5, 1.0, "Generating answer...")

    kwargs = {}
    if parsed_source_ids:
        kwargs["source_ids"] = parsed_source_ids
    if conversation_id:
        kwargs["conversation_id"] = conversation_id

    result = await app.client.chat.ask(notebook_id, question, **kwargs)

    await ctx.report_progress(1.0, 1.0, "Complete")

    return {
        "answer": result.answer,
        "has_citations": hasattr(result, "citations") and bool(result.citations),
        "question": question,
        "conversation_id": getattr(result, "conversation_id", None),
    }


# ============================================================================
# TOOLS -- Artifacts
# ============================================================================


@mcp.tool()
async def generate_and_download(
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    instructions: str = "",
    audio_format: str = "deep-dive",
    audio_length: str = "medium",
    quiz_quantity: str = "standard",
    quiz_difficulty: str = "medium",
    quiz_output_format: str = "json",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Generate an artifact and download it in a single call.

    Supports: report, audio, slide_deck, quiz, infographic.

    Args:
        notebook_id: ID of the notebook
        artifact_type: One of: report, audio, slide_deck, quiz, infographic
        output_path: Path where to save the downloaded file. Use the correct
            extension: .pdf (report, slide_deck, infographic), .wav (audio),
            .json/.md/.html (quiz, based on quiz_output_format)
        instructions: Custom instructions for generation (optional).
            For slide decks, pass a design template here to control visual style.
        audio_format: Audio format: deep-dive, brief, critique, debate
        audio_length: Audio length: short, medium, long
        quiz_quantity: Quiz quantity: few, standard, more
        quiz_difficulty: Quiz difficulty: easy, medium, hard
        quiz_output_format: Quiz download format: json, markdown, html

    Returns:
        Dictionary with generation and download status
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    artifact_type = artifact_type.lower().replace(" ", "_")
    valid_types = {"report", "audio", "slide_deck", "quiz", "infographic"}
    if artifact_type not in valid_types:
        return {"error": f"Unsupported artifact type: {artifact_type}. Use one of: {', '.join(sorted(valid_types))}"}

    await ctx.info(f"Generating {artifact_type}...")

    try:
        gen_kwargs: dict = {}
        if instructions:
            gen_kwargs["instructions"] = instructions

        if artifact_type == "audio":
            gen_kwargs["audio_format"] = audio_format
            gen_kwargs["audio_length"] = audio_length
            status = await app.client.artifacts.generate_audio(notebook_id, **gen_kwargs)
        elif artifact_type == "report":
            report_kwargs: dict = {}
            if instructions:
                report_kwargs["custom_prompt"] = instructions
            status = await app.client.artifacts.generate_report(notebook_id, **report_kwargs)
        elif artifact_type == "slide_deck":
            status = await app.client.artifacts.generate_slide_deck(notebook_id, **gen_kwargs)
        elif artifact_type == "quiz":
            gen_kwargs["quantity"] = quiz_quantity
            gen_kwargs["difficulty"] = quiz_difficulty
            status = await app.client.artifacts.generate_quiz(notebook_id, **gen_kwargs)
        elif artifact_type == "infographic":
            status = await app.client.artifacts.generate_infographic(notebook_id, **gen_kwargs)

        await ctx.info(f"Waiting for {artifact_type} generation to complete...")
        await app.client.artifacts.wait_for_completion(notebook_id, status.task_id)

        await ctx.info(f"Downloading {artifact_type} to {output_path}...")
        if artifact_type == "audio":
            await app.client.artifacts.download_audio(notebook_id, output_path)
        elif artifact_type == "report":
            await app.client.artifacts.download_report(notebook_id, output_path)
        elif artifact_type == "slide_deck":
            await app.client.artifacts.download_slide_deck(notebook_id, output_path)
        elif artifact_type == "quiz":
            await app.client.artifacts.download_quiz(notebook_id, output_path, output_format=quiz_output_format)
        elif artifact_type == "infographic":
            await app.client.artifacts.download_infographic(notebook_id, output_path)

        return {"artifact_type": artifact_type, "output_path": output_path, "success": True}

    except Exception as e:
        return {"artifact_type": artifact_type, "error": str(e)}


@mcp.tool()
async def list_artifacts(
    notebook_id: str,
    artifact_type: str = "",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """List artifacts in a notebook, optionally filtered by type.

    Args:
        notebook_id: ID of the notebook
        artifact_type: Filter by type (audio, video, report, quiz, flashcards,
                       slide_deck, infographic, data_table, mind_map).
                       Leave empty for all types.

    Returns:
        Dictionary with the list of artifacts
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    artifacts = await app.client.artifacts.list(notebook_id, artifact_type or None)
    return {
        "count": len(artifacts),
        "artifacts": [{"id": getattr(a, "id", str(a)), "title": getattr(a, "title", "")} for a in artifacts],
    }


@mcp.tool()
async def export_artifact(
    notebook_id: str,
    artifact_id: str,
    output_path: str,
    export_format: str = "",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Export an artifact to a file in the requested format.

    Uses the appropriate export method based on the artifact type.

    Args:
        notebook_id: ID of the notebook
        artifact_id: ID of the artifact to export
        output_path: Path where to save the exported file
        export_format: Desired format (pdf, csv, json, etc.). Leave empty for default.

    Returns:
        Dictionary with export status
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    await ctx.info(f"Exporting artifact to: {output_path}")
    export_kwargs: dict = {"artifact_id": artifact_id}
    if export_format:
        export_kwargs["export_type"] = export_format
    data = await app.client.artifacts.export(notebook_id, **export_kwargs)
    Path(output_path).write_bytes(data if isinstance(data, bytes) else str(data).encode("utf-8"))
    return {"output_path": output_path, "success": True}


# ============================================================================
# TOOLS -- Research
# ============================================================================


@mcp.tool()
async def research_and_import(
    notebook_id: str,
    query: str,
    source: str = "web",
    max_results: int = 5,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Research a topic and import the results as notebook sources in a single call.

    Starts a research task, polls until completion, and automatically imports
    the top results.

    Args:
        notebook_id: ID of the notebook
        query: Research query
        source: Where to search: "web" or "drive"
        max_results: Maximum number of results to import

    Returns:
        Dictionary with research results and import status
    """
    app = ctx.request_context.lifespan_context
    if not await _ensure_authenticated(app, ctx):
        return {"error": "Authentication failed. Please check the logs."}

    await ctx.info(f"Researching: {query}")
    try:
        task = await app.client.research.start(notebook_id, query, source=source)
        task_id = task.task_id

        poll_result = None
        for _ in range(60):
            await asyncio.sleep(2)
            poll_result = await app.client.research.poll(notebook_id)
            status = getattr(poll_result, "status", str(poll_result))
            if status == "completed" or (isinstance(poll_result, dict) and poll_result.get("status") == "completed"):
                break

        results = getattr(poll_result, "results", [])
        if isinstance(poll_result, dict):
            results = poll_result.get("results", [])

        to_import = results[:max_results] if results else []
        if to_import:
            await ctx.info(f"Importing {len(to_import)} sources...")
            import_result = await app.client.research.import_sources(notebook_id, task_id=task_id, sources=to_import)
        else:
            import_result = {"imported": 0}

        return {
            "query": query,
            "results_found": len(results),
            "imported": len(to_import),
            "import_details": import_result,
            "success": True,
        }

    except Exception as e:
        return {"query": query, "error": str(e)}


# ============================================================================
# TOOLS -- Account Management
# ============================================================================


@mcp.tool()
async def get_account_info(ctx: Context[ServerSession, AppContext]) -> dict:
    """Show the current NotebookLM account and available profiles.

    Returns:
        Dictionary with current account, config path, available profiles,
        and instructions for switching or adding accounts.
    """
    app = ctx.request_context.lifespan_context
    profile_dir = _resolve_profile_dir(app.profile)

    available = {}
    for name, suffix in DEFAULT_PROFILES.items():
        path = Path.home() / suffix
        if path.exists() and (path / "storage_state.json").exists():
            available[name] = str(path)

    for p in Path.home().glob(".notebooklm-*"):
        if p.is_dir() and (p / "storage_state.json").exists():
            label = p.name.replace(".notebooklm-", "")
            if label not in available:
                available[label] = str(p)

    return {
        "current_account": app.profile,
        "config_path": str(profile_dir),
        "available_profiles": available,
        "switch_instructions": (
            "Use the switch_account tool with a profile name "
            "(e.g. 'work', 'personal', 'design') to change account. "
            "No restart required."
        ),
        "new_account_instructions": (
            "To authenticate a new account, run in your terminal:\n"
            "  notebooklm login\n"
            "with NOTEBOOKLM_HOME set to the desired profile directory, e.g.:\n"
            "  NOTEBOOKLM_HOME=~/.notebooklm-<name> notebooklm login"
        ),
    }


@mcp.tool()
async def switch_account(
    profile: str,
    ctx: Context[ServerSession, AppContext],
) -> dict:
    """Switch the active NotebookLM account to a different Google profile.

    The change takes effect immediately and is persisted across server
    restarts. Use get_account_info to see available profiles.

    Args:
        profile: Profile name to switch to (e.g. 'work', 'personal',
                 'design', or any custom name matching ~/.notebooklm-<name>)

    Returns:
        Dictionary confirming the switch with the new profile details.
    """
    app = ctx.request_context.lifespan_context
    target_dir = _resolve_profile_dir(profile)
    storage_file = target_dir / "storage_state.json"

    if not storage_file.exists():
        return {
            "success": False,
            "error": f"No credentials found for profile '{profile}' at {target_dir}",
            "hint": (f"Authenticate first by running:\n  NOTEBOOKLM_HOME={target_dir} notebooklm login"),
        }

    previous = app.profile

    await ctx.info(f"Switching from '{previous}' to '{profile}'...")
    if app.client is not None:
        with suppress(Exception):
            await app.client.__aexit__(None, None, None)

    app.client = await _create_client(profile)
    app.profile = profile

    _write_active_profile(profile)

    await ctx.info(f"Switched to '{profile}' account")

    return {
        "success": True,
        "previous_account": previous,
        "current_account": profile,
        "config_path": str(target_dir),
    }


@mcp.tool()
async def create_profile(
    profile: str,
    ctx: Context[ServerSession, AppContext],
) -> dict:
    """Create a new NotebookLM account profile and launch the Google login.

    This opens a browser window for the user to sign into their Google
    account. Once authentication is complete, the profile is ready to
    use via switch_account.

    Args:
        profile: Name for the new profile (e.g. 'work', 'design',
                 'testing'). Will be stored at ~/.notebooklm-<name>.

    Returns:
        Dictionary with the profile status and next steps.
    """
    target_dir = _resolve_profile_dir(profile)
    storage_file = target_dir / "storage_state.json"

    if storage_file.exists():
        return {
            "success": False,
            "error": f"Profile '{profile}' already exists at {target_dir}",
            "hint": "Use switch_account to switch to it, or choose a different name.",
        }

    success = await _run_login(profile, ctx)

    if not success:
        return {
            "success": False,
            "error": f"Login failed for profile '{profile}'",
            "hint": (
                "Ensure playwright and chromium are installed:\n"
                "  pip install playwright && playwright install chromium\n"
                "Or try running notebooklm login manually in your terminal."
            ),
        }

    return {
        "success": True,
        "profile": profile,
        "config_path": str(target_dir),
        "next_step": (f"Profile '{profile}' is ready. Use switch_account with profile='{profile}' to start using it."),
    }


# ============================================================================
# TOOLS -- Utilities
# ============================================================================


@mcp.tool()
async def pdf_to_png(
    pdf_path: str,
    output_directory: str = "",
    dpi: int = 200,
) -> dict:
    """Convert a PDF file to individual PNG images (one per page).

    Useful for making slide deck pages visible to LLMs for review or editing.

    Args:
        pdf_path: Path to the source PDF file
        output_directory: Directory to write PNGs into. Defaults to a folder
            beside the PDF named <filename>_pages/
        dpi: Render resolution (default 200 -- good balance of quality and size)

    Returns:
        Dictionary with output directory, list of page image paths, and page count
    """
    import fitz  # pymupdf

    pdf = Path(pdf_path)
    if not pdf.is_file():
        return {"error": f"PDF not found: {pdf_path}"}

    out_dir = Path(output_directory) if output_directory else pdf.parent / f"{pdf.stem}_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf))
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pages: list[str] = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=matrix)
        out_file = out_dir / f"page_{i + 1:03d}.png"
        pix.save(str(out_file))
        pages.append(str(out_file))

    doc.close()

    return {
        "output_directory": str(out_dir),
        "pages": pages,
        "page_count": len(pages),
        "dpi": dpi,
        "success": True,
    }


@mcp.tool()
async def png_to_pdf(
    image_paths: str = "",
    image_directory: str = "",
    output_path: str = "",
) -> dict:
    """Combine PNG images into a single PDF document.

    Provide either a list of image paths or a directory containing PNGs.
    When using a directory, images are sorted alphabetically (the naming
    convention from pdf_to_png -- page_001.png, page_002.png, etc. --
    preserves correct order automatically).

    Args:
        image_paths: Comma-separated image file paths, or a JSON array of paths
        image_directory: Directory of PNG files to combine (alternative to image_paths)
        output_path: Path for the output PDF. Defaults to <directory>/combined.pdf

    Returns:
        Dictionary with the output PDF path and page count
    """
    import fitz  # pymupdf

    resolved_paths = None
    if image_paths:
        image_paths = image_paths.strip()
        if image_paths.startswith("["):
            try:
                resolved_paths = json.loads(image_paths)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON in image_paths: {e}"}
        else:
            resolved_paths = [p.strip() for p in image_paths.split(",") if p.strip()]

    if resolved_paths:
        files = [Path(p) for p in resolved_paths]
    elif image_directory:
        src = Path(image_directory)
        if not src.is_dir():
            return {"error": f"Directory not found: {image_directory}"}
        files = sorted(src.glob("*.png"))
    else:
        return {"error": "Provide either image_paths or image_directory"}

    if not files:
        return {"error": "No PNG files found"}

    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        return {"error": f"Files not found: {', '.join(missing)}"}

    doc = fitz.open()
    for img_path in files:
        img_doc = fitz.open(str(img_path))
        rect = img_doc[0].rect
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        img_pdf = fitz.open("pdf", pdf_bytes)
        page = doc.new_page(width=rect.width, height=rect.height)
        page.show_pdf_page(page.rect, img_pdf, 0)
        img_pdf.close()

    out = Path(output_path) if output_path else (files[0].parent / "combined.pdf")
    doc.save(str(out))
    doc.close()

    return {
        "output_path": str(out),
        "page_count": len(files),
        "success": True,
    }


# ============================================================================
# PROMPTS
# ============================================================================


@mcp.prompt()
def analyze_notebook_sources(notebook_id: str, focus_area: str = "main themes") -> str:
    """Generate a prompt for analyzing notebook sources.

    Args:
        notebook_id: ID of the notebook to analyze
        focus_area: What to focus on in the analysis

    Returns:
        Formatted prompt for analysis
    """
    return f"""Please analyze the sources in notebook {notebook_id}.

Focus on: {focus_area}

Provide:
1. Key themes and concepts
2. Important findings or insights
3. Connections between sources
4. Gaps or areas needing more research

Use the NotebookLM MCP tools to query the notebook for specific information."""


@mcp.prompt()
def research_topic_workflow(topic: str, depth: str = "comprehensive") -> str:
    """Generate a prompt for researching a topic using NotebookLM.

    Args:
        topic: Topic to research
        depth: Level of depth (quick, standard, comprehensive)

    Returns:
        Formatted workflow prompt
    """
    return f"""Research Workflow for: {topic}
Depth: {depth}

Steps:
1. Create a new notebook for this research topic
2. Add relevant sources (URLs, documents, or text)
3. Ask key questions to understand the topic:
   - What are the fundamental concepts?
   - What are current trends or developments?
   - What are the key challenges or debates?
4. Generate a quiz to test understanding
5. Create an audio overview for easy review

Use the NotebookLM MCP tools to execute this workflow."""


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STYLE_SECTIONS = {"corporate": "## Corporate", "educational": "## Educational", "creative": "## Creative"}


def _load_slide_template(style: str) -> str:
    """Extract a single template section from slide_styles.md."""
    styles_file = _TEMPLATE_DIR / "slide_styles.md"
    if not styles_file.is_file():
        return f"Template file not found at {styles_file}"

    content = styles_file.read_text(encoding="utf-8")
    header = _STYLE_SECTIONS.get(style.lower())
    if not header:
        return f"Unknown style '{style}'. Available: {', '.join(_STYLE_SECTIONS)}"

    start = content.find(header)
    if start == -1:
        return f"Style '{style}' not found in template file"

    after_header = content[start + len(header) :]
    for other in _STYLE_SECTIONS.values():
        if other != header:
            end = after_header.find(other)
            if end != -1:
                after_header = after_header[:end]
                break

    return (header + after_header).rstrip("-\n ").strip()


@mcp.prompt()
def generate_styled_slides(
    notebook_id: str,
    style: str = "corporate",
    output_path: str = "slides.pdf",
) -> str:
    """Generate a slide deck using a bundled design template.

    Reads the selected template from templates/slide_styles.md and
    provides complete instructions for generating and downloading
    a styled slide deck.

    Args:
        notebook_id: ID of the notebook to generate slides from
        style: Design template to use: corporate, educational, or creative
        output_path: Where to save the downloaded PDF

    Returns:
        Formatted prompt with the template and tool call instructions
    """
    template = _load_slide_template(style)

    return f"""Generate a styled slide deck from notebook {notebook_id}.

Style: {style}

Call the generate_and_download tool with these parameters:
  notebook_id: {notebook_id}
  artifact_type: slide_deck
  output_path: {output_path}
  instructions: (paste the design template below)

--- DESIGN TEMPLATE ---
{template}
--- END TEMPLATE ---

After downloading, consider using pdf_to_png to split the PDF into
individual page images for review."""


# ============================================================================
# SERVER EXECUTION
# ============================================================================

if __name__ == "__main__":
    transport = "stdio"
    if "--http" in sys.argv:
        transport = "streamable-http"

    mcp.run(transport=transport)
