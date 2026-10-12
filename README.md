# TONYAgent

<div align="center">

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pytest](https://img.shields.io/badge/tested_with-pytest-orange.svg)](https://pytest.org)

**A local-first desktop AI agent for automating programming tasks**

[Features](#-features) ??[Quick Start](#-quick-start) ??[Installation](#-installation) ??[Configuration](#-configuration) ??[Usage](#-usage) ??[Architecture](#-architecture) ??[Development](#-development) ??[Troubleshooting](#-troubleshooting) ??[License](#-license)

</div>

---

## ??Features

### ?�� Multi-Provider LLM Support
Connect to **two aggregator providers** with one OpenAI-compatible wire format:
- **OpenRouter** (one key, most hosted models)
- **OpenCode Go** (a second aggregator)

Both publish real metadata alongside their model list — reasoning support, effort
levels, pricing — which is where the model picker and the thinking dial get their
values. The single-vendor dialects that used to be listed here are gone: they
answered the model list with an id and nothing else, so keeping them would have
meant a second catalogue implementation returning "unknown" for most fields.

### ?�� Modern Desktop UI
- Built with **React** in a native window: the interface is HTML and CSS, rendered by the system webview with no browser around it (`pywebview`, in `src/tonyagent/window/`)
- **Light/Dark/System themes** with pill-shaped design
- Real-time streaming chat with token-by-token display
- Tool call visualization and confirmation dialogs
- Responsive layout with collapsible sidebar
- **Code viewer**: browse the project tree and open any file — source with syntax highlighting, images, Markdown rendered or as source, CSV/TSV as a grid. Three colour palettes (VSCode's Dark+, Light+ and Monokai). Read-only by default with a per-file toggle; **locked while a turn is running**, so a file cannot be typed into while the agent is writing it. When you do edit and save, the change is written atomically and the next message tells the agent which file and which lines changed, so its picture of your code is never stale
- **Agent / Code switch** in the top bar. Code mode is the whole window rather than a pane: the chat rail, the tab strip and the composer are replaced by a persistent **project explorer** on the left and the editor filling the rest, so leaving the conversation for the project does not mean losing either
- **Desktop pet**: a small always-on-top **circle** that says what the turn is doing right now — "Thinking", "Running read_file", "Needs your approval" — so a long turn can run while you are in another window. It is cut to a circle with a window region *and* has its system shadow turned off: the region takes the corners away, and DWM would otherwise paint the drop shadow to the window's rectangle and fill those corners back in with a dark halo. The corners are really gone — the desktop shows through, and a click there goes to whatever is behind instead of to the pet. The character is the app's own mark, and it *behaves*: it blinks, it works at a keyboard while the agent works, it hops when it wants you, and it falls asleep if nothing has happened for a while. Drag it anywhere by its artwork — the OS's own move loop, so it snaps like a normal window — and it comes back where you left it. It never takes focus (asking for attention must not steal the keyboard) and clicking it brings the app back. It is off until you turn it on from the rail
- **Account view**: the usage panel counts what *this app* sent, which is not your provider's real total. One button opens your provider's own dashboard — activity, credits, API keys — in a browser window the app owns, with a persistent sign-in profile. It is a closed set of views, and the agent has no tool that can reach it

### ?���?Rich Tool Ecosystem (32 Tools)
| Category | Tools |
|----------|-------|
| **File** (8) | `read` (with `offset`/`limit`), `read_image`, `write`, `edit` (unique match, or `replace_all`), `delete_file`, `list_dir`, `sandbox_read_file`, `sandbox_list_files` |
| **Search** (2) | `grep`, `glob` |
| **Shell** (5) | `execute_command` (allowlist/denylist, plus `background=true` for long-running jobs), `execute_js`, `job_list`, `job_output`, `job_kill` |
| **Network** (2) | `http_request`, `web_fetch` |
| **Browser** (10) | `browser_navigate`, `browser_click`, `browser_type`, `browser_eval`, `browser_snapshot`, `browser_get_text`, `browser_wait_for`, `browser_scroll`, `browser_screenshot`, `set_viewport_size` |
| **Utility** (1) | `take_screenshot` |
| **Planning** (4) | `todo_write`, `create_goal`, `get_goal`, `update_goal` — the task list and goal are rendered into the system prompt and saved with the conversation |

### ?�� Security-First Design
- **API keys stored in OS keyring** (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Sandboxed execution** via Docker, WSL2, or Windows Sandbox
- **Command allowlist/denylist** for shell operations
- **Folder locking** during AI generation to prevent conflicts
- **Configurable confirmation** for destructive operations
- **Batched tool calls**: every mode's system prompt states that independent tool calls may be issued together in one message, and the core runs them concurrently. Requests are metered on most plans (OpenRouter's free tier allows 20 requests a minute and 1,000 a day), so a turn that reads three files spends one round trip rather than three

### ?�� Sandboxed Execution
- **Docker backend**: Full Linux environment with network isolation and per-container limits
- **WSL backend**: The Docker-free path -- the same sandbox server, run inside your WSL2 distro's network and PID namespaces, with the project folder live via the /mnt drive mount
- **Windows Sandbox backend**: Native Windows isolation (in progress)
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

## ?? Quick Start

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

The shortcut points at `Start TONYAgent (Prebuilt).bat`, which is the entry point
worth having: it rebuilds the frontend when it is behind and checks that
`pywebview` is installed before it opens anything. From a terminal, the window on
its own is:

```bash
python -m tonyagent.window     # opens the window; the core is its child process
```

(`python -m tonyagent` — which this section used to say — is not a command:
`tonyagent` is a package with no `__main__`, so it exits with "cannot be directly
executed".)

1. **Select a project folder** from the sidebar
2. **Configure your LLM provider** in Settings ??Provider
3. **Enter your API key** (securely stored in OS keyring)
4. **Start chatting** - the agent will use tools to complete tasks!

---

## ?�� Installation

### From Source (Recommended)

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
| `openai>=1.10`, `anthropic>=0.18`, `google-generativeai>=0.3` | LLM provider SDKs |
| `ollama>=0.2` | Local model support |
| `playwright>=1.40` | Browser automation |
| `docker>=7.0` | Sandbox container management |
| `loguru>=0.7` | Structured logging |

### Platform-Specific Notes

<details>
<summary><b>Windows</b></summary>

- Windows 10/11 Pro/Enterprise required for Windows Sandbox
- Docker Desktop with WSL2 backend recommended (or just WSL2 — see "Running without Docker")
- Install Visual C++ Build Tools if building from source
</details>

<details>
<summary><b>Linux</b></summary>

- Install `tkinter` system package: `sudo apt install python3-tk` (Ubuntu/Debian)
- Docker: `sudo usermod -aG docker $USER` (log out/in after)
- Wayland: Set `GDK_BACKEND=x11` if UI issues occur
</details>

<details>
<summary><b>macOS</b></summary>

- Install via Homebrew: `brew install python-tk docker`
- Apple Silicon: Use `docker buildx` for multi-arch builds
- Keychain access granted automatically on first run
</details>

---

## ?�️ Configuration

TONYAgent uses a **TOML-based configuration** with secure keyring storage for secrets.

### Configuration File
Location: `~/.config/tonyagent/config.toml` (Linux/macOS) or `%APPDATA%\tonyagent\config.toml` (Windows)

```toml
[provider]
name = "openai"           # openai, anthropic, gemini, mistral, groq, openrouter, ollama, custom
model = "gpt-4o"
base_url = ""             # For custom endpoints

[custom_provider]
enabled = false
name = "local"
base_url = "http://localhost:1234/v1"
model = "local-model"

[sandbox]
type = "auto"              # auto, docker, wsl, wsb (Windows Sandbox), local
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
theme = "system"          # light, dark, system
language = "en"
font_size = 13
```

### Environment Variables
Override settings via environment (useful for CI/CD):

```bash
export TONYAGENT_PROVIDER_NAME=openai
export TONYAGENT_PROVIDER_MODEL=gpt-4o
export TONYAGENT_SANDBOX_TYPE=docker
export TONYAGENT_LOG_LEVEL=DEBUG
```

### API Key Management
Keys are **never written to config files**. Use the UI (Settings ??Provider ??API Key) or:

```bash
# Via keyring CLI (cross-platform)
python -c "import keyring; keyring.set_password('tonyagent', 'openai', 'sk-...')"
```

---

## ?�� Usage

### Basic Workflow

1. **Open a project folder** - Click "Open Folder" in sidebar
2. **Choose provider & model** - Settings ??Provider
3. **Enter API key** - Securely saved to OS keyring
4. **Start sandbox** - Click "Start Sandbox" in status bar (optional but recommended)
5. **Chat naturally** - Describe what you want to accomplish

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
?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??
?? Confirm Tool Execution                 ??
?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??
?? Tool: execute_command                  ??
?? Command: rm -rf dist/                  ??
?? Working Dir: /project                  ??
??                                        ??
?? [Allow]  [Allow Always]  [Deny]        ??
?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??
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

## ?���?Architecture

```
?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??
??                       TONYAgent (Main Process)                 ??
?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�??         ??
?? ??  UI Layer   ?? ?? Core Logic  ?? ?? Config/State??         ??
?? ?? (Views)     ?�◄?�?? (Controller)?��??�│  (Persistence)         ??
?? ?��??�?�?�?�?�?��??�?�?�?�?�?�?? ?��??�?�?�?�?�?��??�?�?�?�?�?�?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�??         ??
??        ??                ??                                     ??
??        ??                ??                                     ??
?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??              ??
?? ??          Tool Orchestrator                  ??              ??
?? ?? (JSON schema registry, execution dispatcher)??              ??
?? ?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??              ??
??                      ??                                        ??
??        ?��??�?�?�?�?�?�?�?�?�?�?�?�?��??�?�?�?�?�?�?�?�?�?�?�?�??                          ??
??        ??            ??            ??                          ??
?? ?��??�?�?�?�?�?�?�?�?�?�???��??�?�?�?�?�?�?�?�?�?�???��??�?�?�?�?�?�?�?�?�?�??                    ??
?? ??Provider  ???? Sandbox  ???? File     ??                    ??
?? ??Adapter   ???? Manager  ???? System   ??                    ??
?? ?��??�?�?�?�?�?�?�?�?�?�???��??�?�?�?�?�?�?�?�?�?�???��??�?�?�?�?�?�?�?�?�?�??                    ??
?��??�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�??
```

### Key Modules

| Module | Path | Responsibility |
|--------|------|----------------|
| **Window** | `src/tonyagent/window/` | The desktop shell: opens the window, serves the bundle, owns the core. `pet.py` is the status card, `account.py` the provider's dashboard, `prefs.py` the shell's own remembered settings |
| **Interface** | `app/src/` | The React interface, built by Vite into `app/dist/` |
| **Core** | `src/tonyagent/core/` | Conversation state, events, modes; served over JSONL by `headless/server.py` |
| **Providers** | `src/tonyagent/providers/` | 8 LLM adapters + factory |
| **Tools** | `src/tonyagent/tools/` | 15 tools + orchestrator |
| **Sandbox** | `src/tonyagent/sandbox/` | Docker + WSL backends, WSB stub |
| **Config** | `src/tonyagent/config/` | Settings, keyring, migration |
| **Utils** | `src/tonyagent/utils/` | Logging, threading, paths |

### Data Flow

1. **User input** ??the window ??ToolOrchestrator
2. **Orchestrator** ??Builds tool schemas ??Sends to LLM Provider
3. **Provider** ??Streams response ??Parses tool calls
4. **Orchestrator** ??Executes tools (with confirmations)
5. **Results** ??Fed back to LLM ??Final response to UI

---

## ?���?Development

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
?��??� .github/workflows/      # CI/CD pipelines
?��??� docker/sandbox/         # Docker sandbox image
?��??� scripts/                # Build & utility scripts
?��??� src/tonyagent/          # Main package
??  ?��??� config/             # Configuration & keyring
??  ?��??� core/               # Core session & events
??  ?��??� folder/             # Project folder management
??  ?��??� providers/          # LLM provider adapters
??  ?��??� sandbox/            # Sandbox backends
??  ?��??� tools/              # Tool implementations
??  ?��??� utils/              # Shared utilities
?��??� tests/                  # Test suite
??  ?��??� unit/
??  ?��??� integration/
??  ?��??� ui/
?��??� windows/                # Windows Sandbox config
```

### Adding a New Provider

1. Create `src/tonyagent/providers/newprovider.py` inheriting `BaseLLMProvider`
2. Implement required methods: `chat_stream()`, `chat_completion()`, `list_models()`
3. Register in `src/tonyagent/providers/registry.py`
4. Add to `ProviderName` enum in `src/tonyagent/providers/base.py`
5. Add tests in `tests/unit/providers/`

### Adding a New Tool

1. Create tool class in `src/tonyagent/tools/` inheriting `BaseTool`
2. Define `name`, `description`, `parameters` (JSON Schema)
3. Implement `execute()` method
4. Register in `src/tonyagent/tools/orchestrator.py`
5. Add tests and update documentation

---

## ?�� Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **"No module named 'tkinter'"** | Install system package: `python3-tk` (Linux), included with Python (Windows/macOS) |
| **Docker connection failed** | Start Docker Desktop; ensure user in `docker` group (Linux) |
| **API key not working** | Verify key in Settings; check keyring permissions; try re-entering |
| **Sandbox won't start** | Check Docker daemon; verify image exists (`docker images`); check port conflicts |
| **UI freezes during generation** | Normal for long operations; check logs in `~/.local/share/tonyagent/logs/` |
| **Playwright errors** | Run `playwright install --with-deps chromium` |

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

# Full reset (including keyring)
python -c "import keyring; keyring.delete_password('tonyagent', 'openai')"
```

---

## ?�� Related Documentation

| Document | Description |
|----------|-------------|
| [Project Summary](PROJECT_SUMMARY.md) | Detailed project status & roadmap |
| [Phase 2 Plan](PHASE2_PLAN.md) | Provider & tool system implementation |
| [Phase 3 Plan](PHASE3_PLAN.md) | UI/UX & sandbox integration |
| [Phase 4 Plan](PHASE4_PLAN.md) | Polish, testing, packaging |

---

## ?�� Contributing

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

## ?�� License

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

## ?�� Acknowledgments

- **[Pydantic](https://github.com/pydantic/pydantic)** - Data validation
- **[Loguru](https://github.com/Delgan/loguru)** - Beautiful logging
- **[Playwright](https://playwright.dev/python/)** - Browser automation
- All LLM providers for their excellent APIs

---

<div align="center">

**Made with ?�️ by [Tony Lee](https://github.com/tonylee)**

�?Star this repo if you find it useful!

</div>