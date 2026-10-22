# TONYAgent

<div align="center">

<img src="logo/tonyagent-logo.png" alt="TONYAgent" width="180">

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pytest](https://img.shields.io/badge/tested_with-pytest-orange.svg)](https://pytest.org)

**A local-first desktop AI agent for automating programming tasks**

[Features](#features) • [Quick Start](#quick-start) • [Installation](#installation-1) • [Configuration](#configuration) • [Usage](#usage) • [Architecture](#architecture) • [Development](#development) • [Troubleshooting](#troubleshooting) • [License](#license)

</div>

---

## Features

### Multi-Provider LLM Support
One OpenAI-compatible wire format, four provider adapters:
- **OpenRouter** — one key, most hosted models
- **OpenCode Go** — OpenCode's subscription gateway
- **OpenCode Zen** — OpenCode's pay-as-you-go gateway, with its own balance and
  catalogue (a Go key does not carry Zen credit)
- **AirLLM** — a model running on this machine's CPU behind an
  OpenAI-compatible server on loopback (`http://127.0.0.1:8765/v1`). It needs
  no key and is **Chat mode only**: it is offered from the Chat track, refused in
  the working modes, and sent no tool schemas, because a small local model
  cannot reliably choose and call tools.

OpenRouter, Go and Zen publish real metadata alongside their model lists —
reasoning support, effort levels, pricing — which is where the model picker and
the thinking dial get their values. The single-vendor dialects that used to be
listed here are gone: they answered the model list with an id and nothing else,
so keeping them would have meant a second catalogue implementation returning
"unknown" for most fields.

### Modern Desktop UI
- Built with **React** in a native window: the interface is HTML and CSS, rendered by the system webview with no browser around it (`pywebview`, in `src/tonyagent/window/`)
- **Dark theme** with shared design tokens for colour, spacing, typography, borders and motion
- Real-time streaming chat with token-by-token display
- Tool call visualization and confirmation dialogs
- Responsive layout with collapsible sidebar
- **Code viewer**: browse the project tree and open any file — source with syntax highlighting, images, Markdown rendered or as source, CSV/TSV as a grid. Three colour palettes (VSCode's Dark+, Light+ and Monokai). Read-only by default with a per-file toggle; **locked while a turn is running**, so a file cannot be typed into while the agent is writing it. When you do edit and save, the change is written atomically and the next message tells the agent which file and which lines changed, so its picture of your code is never stale
- **Agent / Code switch** in the top bar. Code mode is the whole window rather than a pane: the chat rail and tab strip are replaced by a persistent **project explorer** on the left and the editor filling the rest. The same conversation and composer move into a collapsible **Assistant panel** on the right, so leaving the transcript for the project does not mean losing either
- **Two tracks:** a conversation is either a **Chat** (plain conversation) or a **Build** (the working modes). The composer draws only the open track's modes, and crossing tracks mints a new conversation in the other track rather than converting the one you are in, so nothing is cleared and no chat changes what it was written as.
- **Composer modes:** the composer offers the core's Chat mode first for plain conversation. Chat has no project, browser, shell, or mutation tools: nothing is read, run, or changed. Build, Plan, Mission, and Skills remain available from the same pills.
- **Trajectory and Usage views:** the title bar opens a full **Trajectory** view of the turn's events (the debugging view behind the transcript) and a **Usage** dashboard for requests, tokens, reasoning and spend over a chosen window. Settings is a full-window page with its own section nav, not a dialog.
- **Desktop pet**: a small always-on-top **circle** that says what the turn is doing right now — "Thinking", "Running read_file", "Needs your approval" — so a long turn can run while you are in another window. It is cut to a circle with a window region *and* has its system shadow turned off: the region takes the corners away, and DWM would otherwise paint the drop shadow to the window's rectangle and fill those corners back in with a dark halo. The corners are really gone — the desktop shows through, and a click there goes to whatever is behind instead of to the pet. The character is the app's own mark, and it *behaves*: it blinks, it works at a keyboard while the agent works, it hops when it wants you, and it falls asleep if nothing has happened for a while. Drag it anywhere by its artwork — the OS's own move loop, so it snaps like a normal window — and it comes back where you left it. It never takes focus (asking for attention must not steal the keyboard) and clicking it brings the app back. It is off until you turn it on from the rail
- **Account view**: the usage panel counts what *this app* sent, which is not your provider's real total. One button opens your provider's own dashboard — activity, credits, API keys — in a browser window the app owns, with a persistent sign-in profile. It is a closed set of views, and the agent has no tool that can reach it

### Rich Tool Ecosystem (41 Tools)
The core registers 41 tools across six categories. The registry is the source of truth; names here are grouped by capability.

| Category | Count | Tools |
|----------|------:|-------|
| **File** | 8 | `read`, `read_image`, `write`, `edit`, `delete_file`, `list_dir`, `sandbox_read_file`, `sandbox_list_files` |
| **Search** | 2 | `grep`, `glob` |
| **Shell & jobs** | 5 | `execute_command`, `execute_js`, `job_list`, `job_output`, `job_kill` |
| **Network** | 2 | `http_request`, `web_fetch` |
| **Browser** | 10 | `browser_navigate`, `browser_click`, `browser_type`, `browser_eval`, `browser_snapshot`, `set_viewport_size`, `browser_get_text`, `browser_wait_for`, `browser_scroll`, `browser_screenshot` |
| **Utility & planning** | 14 | `take_screenshot`, `todo_write`, `create_goal`, `get_goal`, `update_goal`, `ask_user_question`, `present`, `subagent`, `send_message`, `subagent_fork`, `list_agents`, `interrupt_agent`, `list_skills`, `run_skill` |

### Security-First Design
- **API keys stored in OS keyring** (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Sandboxed execution** via Docker or WSL2; local mode is available with execution tools disabled. Windows Sandbox is currently a non-isolating stub and is not an available isolation backend
- **Command allowlist/denylist** for shell operations
- **Folder locking** during AI generation to prevent conflicts
- **Configurable confirmation** for destructive operations
- **Batched tool calls**: every mode's system prompt states that independent tool calls may be issued together in one message, and the core runs them concurrently. Requests are metered on most plans (OpenRouter's free tier allows 20 requests a minute and 1,000 a day), so a turn that reads three files spends one round trip rather than three

### Sandboxed Execution
- **Docker backend**: Full Linux environment with network isolation and per-container limits
- **WSL backend**: The Docker-free path -- the same sandbox server, run inside your WSL2 distro's network and PID namespaces, with the project folder live via the /mnt drive mount
- **Windows Sandbox**: backend stub only; it does not provide isolation and is not selected as a sandbox
- **Resource limits**: CPU, memory, and timeout controls
- **Persistent workspace** across sessions

#### Running without Docker

Docker is the strongest containment where it is available, but it is no
longer required for the agent to run commands. With `sandbox.type = "auto"`
(the default) the backend is picked in this order:

1. **docker** -- when a daemon answers a ping.
2. **wsl** -- when `wsl.exe` exists and you have a distro installed (Docker
   Desktop's helper distro is skipped). Network is off by default
   (`unshare -n`), processes run in a PID namespace so nothing outlives the
   session, and files the agent writes land as your own user.
3. **local** -- no containment at all: the browser and read-only file tools
   work, and `execute_command` / `execute_js` are refused on purpose.

Pick explicitly with `[sandbox] type = "wsl"`, or choose the distro with
`wsl_distro = "Ubuntu-24.04"` (empty = your default distro). Two capabilities
depend on what is inside the distro, not on TONYAgent: `execute_js` needs
Node.js and the browser tools need Playwright -- when the distro has neither,
`execute_js` says so and the browser tools fall back to the host browser
(which refuses internal addresses by default, like the network tools).

What the WSL backend does **not** have is per-container memory/CPU limits;
that is what Docker's cgroups provide. If you run both, Docker remains the
backend to prefer.

---

## Quick Start

### Prerequisites
- **Python 3.11+**
- **Docker Desktop** (for sandboxed execution) — or **WSL2** alone, which is enough (see "Running without Docker")
- **Git** (for version control operations)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/tonyagent.git
cd tonyagent

# Install in development mode
pip install -e .

# Optional: Install development dependencies
pip install -e ".[dev]"
pre-commit install
```

### First Run

Double-click **`TONYAgent.lnk`** in the repository folder. If it is not there, or
you would rather have it on the Desktop:

```powershell
# in the repository folder
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1 -Destination "$env:USERPROFILE\Desktop"
```

The shortcut points at `Start TONYAgent (Prebuilt).bat`, whose **default
frontend is the terminal interface** — so double-clicking it opens `tony` in a
`cmd` window. Pass `window` to that file for the webview app instead:

```
Start TONYAgent (Prebuilt).bat           the terminal interface   (default)
Start TONYAgent (Prebuilt).bat window    the webview desktop app
```

The `window` path rebuilds the frontend when it is behind and checks that
`pywebview` is installed before it opens anything; the terminal path needs
neither, being pure Python from the checkout. From a terminal, either one on
its own is:

```bash
python -m tonyagent.cli     # the terminal interface
python -m tonyagent.window  # opens the window; the core is its child process
```

(`python -m tonyagent` — which this section used to say — is not a command:
`tonyagent` is a package with no `__main__`, so it exits with "cannot be directly
executed".)

1. **Select a project folder** from the sidebar or Settings.
2. **Add a provider key** in Settings; credentials are stored in the OS keyring.
3. **Choose a model** from the title-bar model selector.
4. **Start chatting** - the permission level and confirmation gates govern tool use.

---

## Installation

### From an Installer (Windows)

`Build Installer.bat` produces `build\installer\TONYAgent-<version>.msi`, which
installs the program to `Program Files`, adds a Start Menu entry and a desktop
shortcut, and registers an uninstaller in Apps & Features. Python does not have
to be installed on the target machine: the interpreter, the frontend and the
WebView2 bindings are all inside the bundle. The WebView2 *runtime* is a Windows
component that ships with Windows 10 and 11; the installer does not carry one.

It needs two tools on the *build* machine, installed once:

```bash
python -m pip install pyinstaller
dotnet tool install --global wix --version 5.0.2
```

**WiX 5 rather than the newest WiX.** WiX 7 refuses to run until its Open Source
Maintenance Fee EULA is accepted, which is a licensing decision rather than a
build step; WiX 5 is the same authoring schema and asks for nothing.

### From Source (Recommended for Development)

```bash
# Standard installation
pip install -e .

# With development tools (linting, testing, type checking)
pip install -e ".[dev]"

# The window is `pywebview`, which is a runtime dependency rather than a build one
pip install -e ".[packaging]"
```

### Requirements

| Dependency | Purpose |
|------------|---------|
| `pydantic>=2.5` | Data validation & settings |
| `keyring>=24.0` | Secure credential storage |
| `openai>=1.10` | OpenAI-compatible provider transport |
| `httpx>=0.25` | Network tools and redirect-safe requests |
| `pywebview>=6.0` | Native desktop window host |
| `playwright>=1.40` | Browser automation |
| `docker>=7.0` | Sandbox container management |
| `Pillow>=10.0` | `take_screenshot` |
| `send2trash>=1.8` | Recoverable `delete_file` |
| `loguru>=0.7` | Structured logging |

### Platform-Specific Notes

<details>
<summary><b>Windows</b></summary>

- Docker Desktop or WSL2 is needed for isolated shell and code execution; Windows Sandbox is not currently implemented
- Docker Desktop with WSL2 backend recommended (or just WSL2 — see "Running without Docker")
- Install Visual C++ Build Tools if building from source
</details>

<details>
<summary><b>Linux</b></summary>

- Install the system webview dependencies required by `pywebview` (WebKitGTK on Linux)
- Docker: `sudo usermod -aG docker $USER` (log out/in after)
- Wayland: Set `GDK_BACKEND=x11` if UI issues occur
</details>

<details>
<summary><b>macOS</b></summary>

- Install the `pywebview` WebKit runtime dependencies; use Docker for the supported isolated execution backend
- Apple Silicon: Use `docker buildx` for multi-arch builds
- Keychain access granted automatically on first run
</details>

---

## Configuration

TONYAgent uses a **TOML-based configuration** with secure keyring storage for secrets. The current desktop interface is React in a `pywebview` window, backed by a separate headless Python core; there is no current Tkinter UI or Tauri shell.

### Configuration File
Location: `~/.config/tonyagent/config.toml` (Linux/macOS) or `%APPDATA%\tonyagent\config.toml` (Windows)

```toml
[provider]
name = "openrouter"       # or "opencode-go"
model = "openrouter/auto"
base_url = ""             # Optional OpenAI-compatible endpoint

[sandbox]
type = "auto"              # auto, docker, wsl, local (Windows Sandbox is a stub)
docker_image = "tonyagent/sandbox:latest"
memory_limit = "2g"
cpu_limit = "2"
timeout = 300
enable_network = true

[tools]
command_allowlist = ["python", "pip", "npm", "git", "cargo", "go"]
command_denylist = ["rm -rf", "format", "fdisk", "shutdown"]
confirm_destructive = true
max_output_size = 10485760  # 10MB

[logging]
level = "INFO"
file_max_mb = 10
file_count = 5

[folder]
current = ""
recent = []
lock_on_generation = true

[ui]
theme = "dark"            # current UI uses the shared dark design system
language = "en"
font_size = 13
```

### Environment Variables
Override settings via environment (useful for CI/CD):

```bash
export TONYAGENT_PROVIDER_NAME=openrouter
export TONYAGENT_PROVIDER_MODEL=openrouter/auto
export TONYAGENT_SANDBOX_TYPE=docker
export TONYAGENT_LOG_LEVEL=DEBUG
```

### API Key Management
Keys are **never written to config files**. Add and manage them in Settings; values are saved to the OS keyring.

---

## Usage

### Basic Workflow

1. **Choose a project folder** from the sidebar or Settings.
2. **Add a provider key** in Settings; keys are stored in the OS keyring.
3. **Choose a model** from the model selector in the title bar.
4. **Start the sandbox** from Settings when you want isolated shell/code execution (Docker or WSL).
5. **Chat naturally** - describe what you want to accomplish; the permission level and tool confirmation gates control what may run.

### Example Prompts

```text
"Create a REST API with FastAPI for a todo app with CRUD operations"
"Refactor the auth module to use JWT instead of sessions"
"Write unit tests for the payment service"
"Debug why the Docker build is failing"
"Scrape the pricing page from competitor.com and summarize"
"Create a React component for a data table with sorting/filtering"
```

### Tool Confirmation Dialog

When the AI wants to execute a potentially destructive action (file deletion, shell command), you'll see a confirmation dialog:

```
┌─────────────────────────────────────────┐
│  Confirm Tool Execution                 │
├─────────────────────────────────────────┤
│  Tool: execute_command                  │
│  Command: rm -rf dist/                  │
│  Working Dir: /project                  │
│                                         │
│  [Allow]  [Allow Always]  [Deny]        │
└─────────────────────────────────────────┘
```

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+N` | New chat |
| `Ctrl+O` | Open folder |
| `Ctrl+,` | Settings |
| `Ctrl+Shift+P` | Command palette |
| `Esc` | Stop generation |
| `Ctrl+Enter` | Send message |

---

## Architecture

The native Python window host serves the React/Vite bundle, exposes a narrow `pywebview` bridge, and owns a headless Python core process. The bridge talks to the core over newline-delimited JSON (JSONL) on stdio.

```text
┌───────────────────────────────┐
│ React + Vite desktop interface│
└───────────────┬───────────────┘
                │ pywebview bridge
┌───────────────▼───────────────┐
│ Python window host            │── serves app/dist/
│ owns child-process lifecycle  │
└───────────────┬───────────────┘
                │ JSONL over stdio
┌───────────────▼───────────────┐
│ Headless AgentSession         │
│ conversations · events · tools│
└───────┬───────────────┬───────┘
        │               │
┌───────▼───────┐ ┌─────▼────────────┐
│ OpenRouter /  │ │ Docker / WSL      │
│ OpenCode Go   │ │ sandbox backends  │
└───────────────┘ └──────────────────┘
```

### Key Modules

| Module | Path | Responsibility |
|--------|------|----------------|
| **Window host** | `src/tonyagent/window/` | Native webview, frontend asset serving, JS bridge, core process and desktop integrations |
| **Interface** | `app/src/` | React UI and shared CSS design system; Vite builds into `app/dist/` |
| **Headless core** | `src/tonyagent/headless/` | JSONL request/event server for the agent session |
| **Core** | `src/tonyagent/core/` | Conversations, events, permissions, tools, usage and session orchestration |
| **Providers** | `src/tonyagent/providers/` | OpenRouter, OpenCode Go, OpenCode Zen and local AirLLM adapters |
| **Tools** | `src/tonyagent/tools/` | Registry-derived schemas and 41 registered tool implementations |
| **Sandbox** | `src/tonyagent/sandbox/` | Docker and WSL backends; local mode refuses sandbox-required execution; Windows Sandbox is a stub |
| **Config** | `src/tonyagent/config/` | Settings, OS keyring integration and migration |

### Data Flow

1. **User input** → the window → `ToolOrchestrator`
2. **Orchestrator** → builds tool schemas → sends to the LLM provider
3. **Provider** → streams response → parses tool calls
4. **Orchestrator** → executes tools (with confirmations)
5. **Results** → fed back to the LLM → final response to the UI

---

## Development

### Setup

```bash
# Install dev dependencies
pip install -e ".[dev]"
pre-commit install

# Install Playwright browsers
playwright install chromium
```

### Code Quality

```bash
# Format code
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/tonyagent --cov-report=html
```

### Project Structure

```
tonyagent/
├── app/                    # React/Vite desktop interface + styles
├── design/                 # Design notes and reviewable plans
├── docker/sandbox/         # Docker sandbox image
├── packaging/              # Installer assets
├── scripts/                # Build, capture & verification scripts
├── src/tonyagent/
│   ├── api/                # Provider transport and wire dialects
│   ├── cli/                # Terminal interface (`tony`)
│   ├── config/             # Configuration & keyring
│   ├── core/               # Session, events, modes, skills
│   ├── folder/             # Project folder management
│   ├── headless/           # JSONL server for the window
│   ├── providers/          # OpenRouter, OpenCode Go/Zen, AirLLM
│   ├── sandbox/            # Docker, WSL and local backends
│   ├── tools/              # 41 registered tools
│   ├── window/             # pywebview host & desktop integration
│   └── utils/              # Shared utilities
├── tests/
│   ├── unit/
│   └── integration/
└── windows/                # Windows Sandbox configuration (stub)
```

### Adding a New Provider

1. Create a provider module under `src/tonyagent/providers/` and implement the `LLMProvider` contract.
2. Register it with `@register_provider` and import it from `src/tonyagent/providers/__init__.py` so registration runs.
3. Add provider and registry tests under `tests/`.

### Adding a New Tool

1. Create a tool class under `src/tonyagent/tools/` using the existing tool base and decorator conventions.
2. Declare its schema and execution/security metadata on the tool class; `schemas.py` derives advertised descriptors from the registry.
3. Ensure the orchestrator/runtime gates are appropriate, then add focused tests under `tests/`.

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **Webview fails to open** | Install the platform's `pywebview` runtime dependencies and inspect the window log |
| **Docker connection failed** | Start Docker Desktop; ensure user in `docker` group (Linux) |
| **API key not working** | Verify key in Settings; check keyring permissions; try re-entering |
| **Sandbox won't start** | Check Docker daemon; verify image exists (`docker images`); check port conflicts |
| **UI freezes during generation** | Normal for long operations; check logs in `~/.local/share/tonyagent/logs/` |
| **Playwright errors** | Install the browser runtime required by the selected sandbox backend; check the core log for the missing dependency |

### Logs

```bash
# View recent logs
tail -f ~/.local/share/tonyagent/logs/tonyagent.log

# Enable debug logging
export TONYAGENT_LOG_LEVEL=DEBUG
python -m tonyagent.window
```

### Reset Configuration

```bash
# Delete config (preserves keyring entries)
rm ~/.config/tonyagent/config.toml

# Remove a saved provider key from Settings (recommended). Provider keys are
# named OS-keyring entries and should not be guessed or reset by backend name.
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Project Summary](PROJECT_SUMMARY.md) | Detailed project status & roadmap |
| [Session Handoff](NEXT_SESSION.md) | Current state, invariants and next work |
| [CLI](CLI.md) | Terminal interface and its commands |
| [Agent Workspace Refine](design/AGENT_WORKSPACE_REFINE.md) | Reviewable plan for the next UI pass |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make changes with tests
4. Run quality checks: `ruff format && ruff check && mypy src/ && pytest`
5. Commit with conventional commits: `feat: add amazing feature`
6. Push and open a Pull Request

### Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

---

## License

**MIT License** - See [LICENSE](LICENSE) for details.

```
MIT License

Copyright (c) 2024 Tony Lee

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Acknowledgments

- **[Pydantic](https://github.com/pydantic/pydantic)** - Data validation
- **[Loguru](https://github.com/Delgan/loguru)** - Beautiful logging
- **[Playwright](https://playwright.dev/python/)** - Browser automation
- All LLM providers for their excellent APIs

---

<div align="center">

**Made by [Tony Lee](https://github.com/tonylee)**

Star this repo if you find it useful!

</div>