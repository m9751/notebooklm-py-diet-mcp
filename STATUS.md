# STATUS — notebooklm-py-diet-mcp

**Current state:** Working MCP server (single file `notebooklm_mcp_server.py`) wrapping notebooklm-py.
CI green on the 3.10–3.13 matrix (ruff lint + format-check + pytest). Unofficial — wraps undocumented
Google APIs via notebooklm-py; an upstream break is a one-file fix.

## Open items
- None blocking. Watch upstream notebooklm-py for API drift (unofficial-API discipline, AGENTS rule #4).

## Scope decisions (declined audit items)
- **No `spec/` tree.** PRM-CDXP-002 flags missing `spec/README.md`/`spec/lessons.md` as P1, but that is the
  docs-INDEX pattern (smokin-os/smokin-knowledge). This is a single-file MCP server, not a docs index —
  it has no specs to index. Adding empty spec/ folders would be empty ceremony (scope-discipline Gate 1).
  Declined deliberately.
