# CLAUDE.md — notebooklm-py-diet-mcp

@AGENTS.md

## Claude-specific notes
- This is a **single-file MCP server** (`notebooklm_mcp_server.py`) — most edits land there.
- It is the "diet" variant: tools are bundled into multi-step workflows, not 1:1 with SDK methods.
  When adding capability, prefer extending an existing workflow tool over exposing a new raw method.
- Auth is via the upstream notebooklm-py browser session — never hardcode cookies or set them in
  committed config.
- The CI matrix tests Python 3.10–3.13; keep new code compatible across that range.
