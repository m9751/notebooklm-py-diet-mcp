# AGENTS.md — notebooklm-py-diet-mcp

> Authority hierarchy: this file is the routing entry point for any agent working in this repo.
> Read this first. For deeper Claude-specific guidance see `CLAUDE.md`.

## What this is
A **Python MCP server** ("diet" / workflow-oriented) wrapping
[notebooklm-py](https://github.com/teng-lin/notebooklm-py) to give MCP-compatible agents
multi-step NotebookLM workflows (query, add sources, generate + download artifacts,
PDF/PNG round-trip). Single-file server. **Unofficial** — uses undocumented Google APIs.

## Topics covered
- FastMCP/stdio MCP server (`notebooklm_mcp_server.py`)
- Templated slide generation (`templates/slide_styles.md`)
- PDF/PNG round-trip editing helpers
- Packaging (`pyproject.toml`, `requirements.txt`), CI (`.github/workflows/ci.yml`), tests (`tests/`)

## Routing — where things live
| Concern | Path |
|---|---|
| MCP server (all tools) | `notebooklm_mcp_server.py` |
| Slide design templates | `templates/` |
| Setup / usage | `INSTRUCTIONS.md`, `README.md`, `docs/` |
| Packaging | `pyproject.toml`, `requirements.txt` |
| Tests | `tests/` |
| CI | `.github/workflows/ci.yml` (lint + test matrix 3.10–3.13) |

## Hard rules (this repo)
1. **MCP stdio reserves stdout** — the server speaks JSON-RPC on stdout. Never `print()` to stdout
   from tool code; all diagnostics go to stderr/logging.
2. **UTF-8 everywhere** — explicit `encoding="utf-8"` on every file open (cross-platform NotebookLM
   content carries non-ASCII; Windows cp1252 default corrupts it).
3. **No blocking I/O in async tool handlers** — network/file work off the event loop.
4. **Unofficial-API discipline** — this wraps undocumented Google endpoints; isolate API surface in
   one place so an upstream break is one-file to fix.

## Reviewers
- `.py` → `python-reviewer`.
