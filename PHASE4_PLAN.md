# Phase 4: Sandbox & Browser Automation

## Objective
Implement sandboxed execution environment with Docker and Windows Sandbox backends, plus browser automation via Playwright.

---

## Current State
- Tool system complete with 9 tools
- `execute_command` marked as `sandbox_required: True`
- `browser_eval`, `execute_js`, `screenshot` tools not yet implemented
- No sandbox infrastructure exists

---

## Implementation Plan

| # | Action | Files | Tool |
|---|--------|-------|------|
| 1 | Create sandbox base classes and protocol | `src/tonyagent/sandbox/base.py` | write |
| 2 | Implement Docker sandbox backend | `src/tonyagent/sandbox/docker_backend.py` | write |
| 3 | Implement Windows Sandbox backend | `src/tonyagent/sandbox/wsb_backend.py` | write |
| 4 | Create sandbox manager (auto-detection, lifecycle) | `src/tonyagent/sandbox/manager.py` | write |
| 5 | Build Docker image (Dockerfile + entrypoint) | `docker/sandbox/Dockerfile`, `docker/sandbox/entrypoint.sh` | write |
| 6 | Create Windows Sandbox .wsb config template | `windows/sandbox.wsb` | write |
| 7 | Implement RPC communication (JSON-RPC over stdin/stdout or named pipes) | `src/tonyagent/sandbox/rpc.py` | write |
| 8 | Add browser tools (browser_eval, execute_js, screenshot, browser_navigate) | `src/tonyagent/tools/browser_tools.py` | write |
| 9 | Integrate sandbox with execute_command tool | `src/tonyagent/tools/shell_tools.py` | edit |
| 10 | Update tool registry and exports | `src/tonyagent/tools/__init__.py`, `src/tonyagent/sandbox/__init__.py` | write |

---

## Sandbox Architecture

```
┌─────────────────┐     JSON-RPC      ┌──────────────────┐
│  Main Process   │ ◄───────────────► │  Sandbox Process │
│  (TONYAgent)    │   stdin/stdout    │  (Docker/WS)     │
└─────────────────┘                   └──────────────────┘
        │                                      │
        │                              ┌───────┴───────┐
        │                              ▼               ▼
        │                        ┌──────────┐   ┌──────────┐
        │                        │  Shell   │   │ Browser  │
        │                        │  (bash)  │   │(Playwright)│
        │                        └──────────┘   └──────────┘
        │
        ▼
┌─────────────────┐
│  Project Folder │
│  (bind mount)   │
└─────────────────┘
```

---

## Docker Backend Specs

| Component | Specification |
|-----------|---------------|
| Base Image | `python:3.11-slim` + Playwright deps |
| Entrypoint | Python RPC server (stdin/stdout JSON-RPC) |
| Mounts | Project folder → `/workspace` (read-write) |
| Network | Host network or bridge (configurable) |
| Resources | CPU: 2 cores, Memory: 2GB (configurable) |
| Health | Periodic `/health` RPC calls |

## Windows Sandbox Backend Specs

| Component | Specification |
|-----------|---------------|
| Config | `.wsb` file with mapped folder, networking, vGPU |
| Communication | Named pipe (`\\.\pipe\tonyagent-sandbox`) |
| Browser | Full Windows Chrome/Edge via Playwright |
| .exe Support | Native Windows executables |
| Cleanup | Auto-delete on close |

---

## Browser Tools to Add

| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to URL |
| `browser_click` | Click element by selector |
| `browser_type` | Type text into element |
| `browser_eval` | Evaluate JS in page context |
| `browser_screenshot` | Capture page screenshot |
| `browser_pdf` | Save page as PDF |
| `execute_js` | Run Node.js script in sandbox |

---

## RPC Protocol (JSON-RPC 2.0)

```json
// Request
{"jsonrpc": "2.0", "method": "exec_command", "params": {"command": "ls", "cwd": "/workspace"}, "id": 1}

// Response
{"jsonrpc": "2.0", "result": {"stdout": "...", "stderr": "", "returncode": 0}, "id": 1}

// Browser methods
{"method": "browser_navigate", "params": {"url": "https://example.com"}}
{"method": "browser_eval", "params": {"script": "document.title"}}
```

---

## Estimated Effort: 15 days
- Days 1-3: Base classes + Docker backend + Dockerfile
- Days 4-6: Windows Sandbox backend + .wsb template
- Days 7-9: RPC layer + sandbox manager
- Days 10-12: Browser tools + Playwright integration
- Days 13-15: Integration testing + edge cases