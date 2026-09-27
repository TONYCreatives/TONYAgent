# TONYAgent

<div align="center">

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pytest](https://img.shields.io/badge/tested_with-pytest-orange.svg)](https://pytest.org)

**A local-first desktop AI agent for automating programming tasks**

[Features](#-features) • [Quick Start](#-quick-start) • [Installation](#-installation) • [Configuration](#-configuration) • [Usage](#-usage) • [Architecture](#-architecture) • [Development](#-development) • [Troubleshooting](#-troubleshooting) • [License](#-license)

</div>

---

## ✨ Features

### 🤖 Multi-Provider LLM Support
Connect to **8+ LLM providers** with a unified interface:
- **OpenAI** (GPT-4, GPT-3.5, etc.)
- **Anthropic** (Claude 3 Opus/Sonnet/Haiku)
- **Google Gemini** (Gemini Pro, Flash)
- **Mistral** (Mistral Large, Small, etc.)
- **Groq** (Llama 3, Mixtral, Gemma - fast inference)
- **OpenRouter** (Access 100+ models via single API)
- **Ollama** (Local models - Llama 3, CodeLlama, etc.)
- **Custom OpenAI-compatible endpoints** (LM Studio, vLLM, etc.)

### 🎨 Modern Desktop UI
- Built with **customtkinter** for native-looking, modern interfaces
- **Light/Dark/System themes** with pill-shaped design
- Real-time streaming chat with token-by-token display
- Tool call visualization and confirmation dialogs
- Responsive layout with collapsible sidebar

### 🛠️ Rich Tool Ecosystem (15 Tools)
| Category | Tools |
|----------|-------|
| **File Operations** | `read_file`, `write_file`, `edit_file`, `delete_file`, `list_dir` |
| **Search** | `grep_search`, `glob_search` |
| **Shell** | `execute_command` (with allowlist/denylist) |
| **Network** | `http_request` |
| **Browser Automation** | `navigate`, `click`, `type_text`, `evaluate_js`, `screenshot`, `execute_js` |

### 🔒 Security-First Design
- **API keys stored in OS keyring** (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Sandboxed execution** via Docker or Windows Sandbox
- **Command allowlist/denylist** for shell operations
- **Folder locking** during AI generation to prevent conflicts
- **Configurable confirmation** for destructive operations

### 📦 Sandboxed Execution
- **Docker backend**: Full Linux environment with network isolation
- **Windows Sandbox backend**: Native Windows isolation (in progress)
- **Resource limits**: CPU, memory, and timeout controls
- **Persistent workspace** across sessions

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+**
- **Docker Desktop** (for sandboxed execution)
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

```bash
# Launch the application
python -m tonyagent
# Or if installed as package:
tonyagent
```

1. **Select a project folder** from the sidebar
2. **Configure your LLM provider** in Settings → Provider
3. **Enter your API key** (securely stored in OS keyring)
4. **Start chatting** - the agent will use tools to complete tasks!

---

## 📦 Installation

### From Source (Recommended)

```bash
# Standard installation
pip install -e .

# With development tools (linting, testing, type checking)
pip install -e ".[dev]"

# With packaging tools (PyInstaller, NSIS)
pip install -e ".[packaging]"
```

### Requirements

| Dependency | Purpose |
|------------|---------|
| `customtkinter>=5.2` | Modern UI framework |
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
- Docker Desktop with WSL2 backend recommended
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

## ⚙️ Configuration

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
type = "docker"           # docker, wsb (Windows Sandbox)
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
Keys are **never written to config files**. Use the UI (Settings → Provider → API Key) or:

```bash
# Via keyring CLI (cross-platform)
python -c "import keyring; keyring.set_password('tonyagent', 'openai', 'sk-...')"
```

---

## 💡 Usage

### Basic Workflow

1. **Open a project folder** - Click "Open Folder" in sidebar
2. **Choose provider & model** - Settings → Provider
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

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        TONYAgent (Main Process)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   UI Layer   │  │  Core Logic  │  │  Config/State│          │
│  │  (Views)     │◄─┤  (Controller)│─►│  (Persistence)         │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘          │
│         │                 │                                      │
│         ▼                 ▼                                      │
│  ┌──────────────────────────────────────────────┐               │
│  │           Tool Orchestrator                  │               │
│  │  (JSON schema registry, execution dispatcher)│               │
│  └────────────────────┬─────────────────────────┘               │
│                       │                                         │
│         ┌─────────────┼─────────────┐                           │
│         ▼             ▼             ▼                           │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐                     │
│  │ Provider  │ │  Sandbox  │ │  File     │                     │
│  │ Adapter   │ │  Manager  │ │  System   │                     │
│  └───────────┘ └───────────┘ └───────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

### Key Modules

| Module | Path | Responsibility |
|--------|------|----------------|
| **App Entry** | `src/tonyagent/__main__.py` | CLI entry point |
| **Core App** | `src/tonyagent/core/app.py` | Lifecycle, config, main loop |
| **UI Views** | `src/tonyagent/ui/views/` | Main window, chat, sidebar |
| **Providers** | `src/tonyagent/providers/` | 8 LLM adapters + factory |
| **Tools** | `src/tonyagent/tools/` | 15 tools + orchestrator |
| **Sandbox** | `src/tonyagent/sandbox/` | Docker + WSB backends |
| **Config** | `src/tonyagent/config/` | Settings, keyring, migration |
| **Utils** | `src/tonyagent/utils/` | Logging, threading, paths |

### Data Flow

1. **User input** → MainWindow → ToolOrchestrator
2. **Orchestrator** → Builds tool schemas → Sends to LLM Provider
3. **Provider** → Streams response → Parses tool calls
4. **Orchestrator** → Executes tools (with confirmations)
5. **Results** → Fed back to LLM → Final response to UI

---

## 🛠️ Development

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
├── .github/workflows/      # CI/CD pipelines
├── docker/sandbox/         # Docker sandbox image
├── scripts/                # Build & utility scripts
├── src/tonyagent/          # Main package
│   ├── config/             # Configuration & keyring
│   ├── core/               # App lifecycle
│   ├── folder/             # Project folder management
│   ├── providers/          # LLM provider adapters
│   ├── sandbox/            # Sandbox backends
│   ├── tools/              # Tool implementations
│   ├── ui/                 # CustomTkinter UI
│   └── utils/              # Shared utilities
├── tests/                  # Test suite
│   ├── unit/
│   ├── integration/
│   └── ui/
└── windows/                # Windows Sandbox config
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

## 🐛 Troubleshooting

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
python -m tonyagent
```

### Reset Configuration

```bash
# Delete config (preserves keyring entries)
rm ~/.config/tonyagent/config.toml

# Full reset (including keyring)
python -c "import keyring; keyring.delete_password('tonyagent', 'openai')"
```

---

## 📚 Related Documentation

| Document | Description |
|----------|-------------|
| [Project Summary](PROJECT_SUMMARY.md) | Detailed project status & roadmap |
| [Phase 2 Plan](PHASE2_PLAN.md) | Provider & tool system implementation |
| [Phase 3 Plan](PHASE3_PLAN.md) | UI/UX & sandbox integration |
| [Phase 4 Plan](PHASE4_PLAN.md) | Polish, testing, packaging |

---

## 🤝 Contributing

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

## 📄 License

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

## 🙏 Acknowledgments

- **[customtkinter](https://github.com/TomSchimansky/CustomTkinter)** - Modern UI framework
- **[Pydantic](https://github.com/pydantic/pydantic)** - Data validation
- **[Loguru](https://github.com/Delgan/loguru)** - Beautiful logging
- **[Playwright](https://playwright.dev/python/)** - Browser automation
- All LLM providers for their excellent APIs

---

<div align="center">

**Made with ❤️ by [Tony Lee](https://github.com/tonylee)**

⭐ Star this repo if you find it useful!

</div>