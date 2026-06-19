# notebooklm-py-diet-mcp

![The Context Bridge -- Connecting AI coding agents to Google NotebookLM](docs/cover.png)

Connect your AI agent to [Google NotebookLM](https://notebooklm.google.com/). Query your notebooks, add sources, generate reports, podcasts, slide decks, and more -- directly from [Cursor](https://cursor.com/), [Claude Code](https://docs.claude.com/en/docs/claude-code), or any [MCP-compatible](https://modelcontextprotocol.io/) client.

**Workflow-orientated MCP toolset for IDE level interaction with NotebookLM.** Designed as a smart and lightweight MCP server to enable AI code assist-native multi-step workflows (research, generate artifacts, download and convert).  Packaged as single tool calls so the agent gets more done with less messing aroung and without losing capability.

Built on [**notebooklm-py**](https://github.com/teng-lin/notebooklm-py) by [Teng Lin](https://github.com/teng-lin).

> **Unofficial** -- Uses undocumented Google APIs via notebooklm-py. Not affiliated with Google. APIs may change without notice.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Licence: MIT](https://img.shields.io/badge/licence-MIT-green)

Need granular control over every SDK method? See the full-fat [notebooklm-py-MCP](https://github.com/earlyprototype/notebooklm-py-MCP) (72 individual tools exposed - designed primarily for testing).

## Where to start

| If you are asking… | Start here |
|---|---|
| "What is this and what are the rules?" | `AGENTS.md` (routing + hard rules) → `CLAUDE.md` (notes) |
| "What's the current state / open work?" | `STATUS.md` |
| "How do I install / test / lint it?" | `## Quick start` below, or `make help` |
| "Where's the server code?" | `notebooklm_mcp_server.py` (single file — all tools) |
| "How do I make a slide template?" | `templates/slide_styles.md` |
| "What can it do beyond the SDK?" | "Beyond the SDK" below |

## Quick start

```bash
make install     # pip install runtime + dev deps
make lint        # ruff check + ruff format --check
make test        # pytest (matches the CI matrix)
```

`make help` lists all targets. The **Makefile is the canonical command front door** — it mirrors exactly what CI runs, so `make lint` / `make test` locally == the gate on your PR.

## For Claude landing here (read before editing)

1. **Single-file server.** Almost all edits land in `notebooklm_mcp_server.py`.
2. **stdout is reserved for JSON-RPC** — never `print()` to stdout from tool code (AGENTS.md hard rule #1). Diagnostics go to stderr.
3. **UTF-8 on every file open**, and **never hardcode cookies** — auth is the upstream browser session.
4. **Keep 3.10–3.13 compatible** (the CI matrix) and **branch + PR** every change — `main` is protected and CI (`lint` + `test (3.12)`) must pass.

## Beyond the SDK

This server is not just a thin wrapper. It adds capabilities that the underlying API does not provide:

- **Templated slide generation** -- Three bundled design templates (Corporate, Educational, Creative) in `templates/slide_styles.md`. Pass any template as the `instructions` parameter to `generate_and_download` and NotebookLM will follow the specified tone, colour palette, typography, and layout rules. Create your own templates using the same structure.
- **PDF / PNG round-trip editing** -- `pdf_to_png` splits a downloaded slide deck (or any PDF) into individual page images that an LLM can review, critique, or annotate. `png_to_pdf` reassembles edited pages back into a single document. This enables a generate-review-refine loop that is not possible through the NotebookLM interface alone.
- **Inline persona control** -- `ask_question` accepts optional `persona` and `response_length` parameters, configuring the chat persona in the same call rather than requiring a separate configuration step.

## AI Workflow Tools (14)

| Tool | Description |
|------|-------------|
| `list_notebooks_tool` | List all notebooks with IDs and titles |
| `create_notebook` | Create a new notebook |
| `list_sources` | List all sources in a notebook |
| `add_sources` | Add multiple sources (URL, text, file) in a single call |
| `ask_question` | Query a notebook with optional persona, source filtering, and threading |
| `generate_and_download` | Generate and download an artifact in one step (report, audio, slide deck, quiz, infographic) |
| `list_artifacts` | List artifacts in a notebook |
| `export_artifact` | Export an artifact to a file |
| `research_and_import` | Research a topic and import results as sources automatically |
| `get_account_info` | Show the active account and available profiles |
| `switch_account` | Switch to a different Google account profile |
| `create_profile` | Create a new account profile and launch browser sign-in |
| `pdf_to_png` | Convert a PDF to individual PNG images (one per page) |
| `png_to_pdf` | Combine PNG images into a single PDF document |

### MCP Resources

| URI | Description |
|-----|-------------|
| `notebooklm://notebooks` | List all notebooks (read-only) |
| `notebooklm://notebook/{id}` | Notebook details including sources |

### MCP Prompts

| Prompt | Description |
|--------|-------------|
| `analyze_notebook_sources` | Template for analysing notebook sources by theme |
| `research_topic_workflow` | Guided research workflow using NotebookLM tools |
| `generate_styled_slides` | Generate a slide deck using a bundled design template (corporate, educational, creative) |

## Prerequisites

- Python 3.10 or later
- A Google account with access to [NotebookLM](https://notebooklm.google.com/)
- [Cursor](https://cursor.com/) or another MCP-compatible client

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/earlyprototype/notebooklm-py-diet-mcp.git
cd notebooklm-py-diet-mcp
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate

pip install -e ".[dev]"
```

Alternatively, install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 3. Install Playwright (required for first-time login and auto-reauthentication)

```bash
playwright install chromium
```

### 4. Authenticate with Google NotebookLM

```bash
# Set the account profile directory
# Windows (PowerShell)
$env:NOTEBOOKLM_HOME = "$HOME\.notebooklm-work"

# macOS / Linux
export NOTEBOOKLM_HOME=~/.notebooklm-work

# Login (opens a browser window -- select your Google account)
notebooklm login

# Verify
notebooklm list
```

## Configuration

### Cursor

Add the following to your `.cursor/mcp.json` file:

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "<path-to-venv>/python",
      "args": [
        "<path-to-repo>/notebooklm_mcp_server.py"
      ]
    }
  }
}
```

Replace the placeholder paths with your actual paths. The server manages account profiles internally -- no `NOTEBOOKLM_HOME` environment variable is needed. Use `switch_account` and `get_account_info` to manage profiles at runtime.

Restart Cursor after saving the configuration.

### Claude Code

```bash
claude mcp add notebooklm -- python /path/to/notebooklm_mcp_server.py
```

### HTTP Transport (for MCP Inspector or remote access)

```bash
python notebooklm_mcp_server.py --http
```

Then connect your client to `http://localhost:8000/mcp`.

## Multiple Google Accounts

Each Google account is stored in a separate directory. Set `NOTEBOOKLM_HOME` to switch between them:

```bash
# Authenticate different accounts
NOTEBOOKLM_HOME=~/.notebooklm-work notebooklm login      # Work account
NOTEBOOKLM_HOME=~/.notebooklm notebooklm login            # Personal account
NOTEBOOKLM_HOME=~/.notebooklm-design notebooklm login     # Another account
```

The `get_account_info` tool shows the currently active profile and available alternatives. Use `switch_account` to change at runtime without restarting.

## Usage Examples

Once configured, you can interact with NotebookLM directly from your AI agent:

**List notebooks:**
> "List my NotebookLM notebooks"

**Query a knowledge base:**
> "Ask the Strategy notebook: what are our key objectives for 2026?"

**Set a persona and ask:**
> "As a strategy analyst, summarise the key risks in my Research notebook"

**Add multiple sources at once:**
> "Add these URLs to my Research notebook: https://example.com/article1, https://example.com/article2"

**Generate and download content:**
> "Generate a podcast overview for the Project notebook and save it"
> "Generate a report from the Strategy notebook and download it as PDF"
> "Create an infographic from the Training notebook"

**Research and import:**
> "Research 'digital fabrication trends' and import the top results into my Research notebook"

**Generate a styled slide deck:**
> "Generate a slide deck for the Strategy notebook using the Corporate template"

## Slide Template Demos

The three bundled templates produce distinctly different output from the same workflow. Each example below was generated from a subsection of an innovation literacy training programme.

### Corporate

Strategy consulting style -- serif headings, blue accent, data-dense layouts with charts, tables, and evidence callouts.

<p>
<img src="docs/demos/selected/corporate_1.png" width="32%" alt="Corporate slide: historical analogy mapping" />
<img src="docs/demos/selected/corporate_2.png" width="32%" alt="Corporate slide: diagnostic table" />
<img src="docs/demos/selected/corporate_3.png" width="32%" alt="Corporate slide: recommendation table" />
</p>

### Educational

Workshop and training style -- warm cream background, teal/amber accents, illustrated concepts, generous whitespace.

<p>
<img src="docs/demos/selected/educational_1.png" width="32%" alt="Educational slide: operational vs design thinking comparison" />
<img src="docs/demos/selected/educational_2.png" width="32%" alt="Educational slide: four-point capture cycle" />
<img src="docs/demos/selected/educational_3.png" width="32%" alt="Educational slide: disproven hypothesis principle" />
</p>

### Creative

Pitch deck style -- dark backgrounds, lime accent, bold typography, minimal text, visually striking layouts.

<p>
<img src="docs/demos/selected/creative_1.png" width="32%" alt="Creative slide: hero statement on dark background" />
<img src="docs/demos/selected/creative_2.png" width="32%" alt="Creative slide: facilitation gap with split contrast" />
<img src="docs/demos/selected/creative_3.png" width="32%" alt="Creative slide: 2x2 grid with icons" />
</p>

See `templates/slide_styles.md` for the full template definitions or create your own following the same structure.

## Project Structure

```
notebooklm-py-diet-mcp/
  notebooklm_mcp_server.py   # MCP server (14 tools, resources, prompts)
  pyproject.toml              # Python packaging and tool configuration
  requirements.txt            # Convenience dependency file
  INSTRUCTIONS.md             # Context injected into the LLM when loaded
  LICENSE                     # MIT licence
  README.md                   # This file
  tests/
    conftest.py               # Shared test fixtures and mocks
    test_helpers.py            # Unit tests for helper functions
    test_tools.py              # Mock-based tool tests
    test_lifespan.py           # Server startup scenario tests
  templates/
    slide_styles.md           # Bundled slide design templates
  docs/
    setup.md                  # Detailed setup guide
    demos/selected/           # Curated slide demo images (README gallery)
      demos/corporate/          # Full corporate template example set
      demos/educational/        # Full educational template example set
      demos/creative/           # Full creative template example set
```

## Development

### Running tests

```bash
pip install -e ".[dev]"
pytest
```

### Linting

```bash
ruff check .
ruff format .
```

## INSTRUCTIONS.md

The `INSTRUCTIONS.md` file is loaded by MCP clients alongside the server and provides the LLM with usage context -- workflow patterns, error handling guidance, and tool conventions. Place it next to `notebooklm_mcp_server.py` or in the MCP server metadata directory used by your client.

## Acknowledgements

This project would not exist without [**notebooklm-py**](https://github.com/teng-lin/notebooklm-py) by [Teng Lin](https://github.com/teng-lin) and contributors. It provides the complete Python API for Google NotebookLM that this MCP server wraps.

- [notebooklm-py on GitHub](https://github.com/teng-lin/notebooklm-py)
- [notebooklm-py on PyPI](https://pypi.org/project/notebooklm-py/)

The MCP server is built using the [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk) by Anthropic.

## Licence

MIT -- see [LICENSE](LICENSE) for details.

## Disclaimer

This is an **unofficial** project. It is not affiliated with, endorsed by, or supported by Google. It relies on undocumented APIs that may change at any time. Use at your own risk. See the [notebooklm-py security policy](https://github.com/teng-lin/notebooklm-py/blob/main/SECURITY.md) for credential handling guidance.
