# Phase 3: Tool System Implementation

## Objective
Implement the complete tool system with file operations, search, shell commands, and network tools that the AI can call during chat.

---

## Current State
- Provider layer complete with function calling support
- ToolSchema and ChatMessage types defined
- UI streaming chat working
- No tool registry or execution infrastructure yet

---

## Implementation Plan

| # | Action | Files | Tool |
|---|--------|-------|------|
| 1 | Create tool base classes (Tool, ToolResult, ToolRegistry) | `src/tonyagent/tools/base.py` | write |
| 2 | Create tool schemas (JSON schemas for all tools) | `src/tonyagent/tools/schemas.py` | write |
| 3 | Implement file tools (read, write, edit, delete, list) | `src/tonyagent/tools/file_tools.py` | write |
| 4 | Implement search tools (grep, glob) | `src/tonyagent/tools/search_tools.py` | write |
| 5 | Implement shell tools (execute_command) | `src/tonyagent/tools/shell_tools.py` | write |
| 6 | Implement network tools (http_request) | `src/tonyagent/tools/network_tools.py` | write |
| 7 | Create tool orchestrator (execution, validation, logging) | `src/tonyagent/tools/orchestrator.py` | write |
| 8 | Create tool confirmation dialog (for destructive ops) | `src/tonyagent/ui/views/confirm_dialog.py` | write |
| 9 | Update tool log panel to show real tool executions | `src/tonyagent/ui/views/main_window.py` | edit |
| 10 | Integrate tools into provider chat completion | `src/tonyagent/ui/views/main_window.py` | edit |
| 11 | Update `__init__.py` exports | `src/tonyagent/tools/__init__.py` | write |

---

## Tool Specifications

### File Tools
| Tool | Parameters | Destructive | Confirmation |
|------|------------|-------------|--------------|
| `read_file` | path (str), encoding? (str) | No | No |
| `write_file` | path (str), content (str), encoding? (str) | Yes | Yes |
| `edit_file` | path (str), old_text (str), new_text (str) | Yes | Yes |
| `delete_file` | path (str) | Yes | Yes |
| `list_dir` | path? (str), recursive? (bool) | No | No |

### Search Tools
| Tool | Parameters | Destructive | Confirmation |
|------|------------|-------------|--------------|
| `grep` | pattern (str), path? (str), include? (str) | No | No |
| `glob` | pattern (str), path? (str) | No | No |

### Shell Tools
| Tool | Parameters | Destructive | Confirmation |
|------|------------|-------------|--------------|
| `execute_command` | command (str), cwd? (str), timeout? (int) | Yes | Yes |

### Network Tools
| Tool | Parameters | Destructive | Confirmation |
|------|------------|-------------|--------------|
| `http_request` | url (str), method? (str), headers? (dict), body? (str), timeout? (int) | No | Yes |

---

## Security Requirements
- All paths resolved relative to project folder (no traversal)
- Destructive tools require user confirmation via modal dialog
- Shell commands validated against allowlist/denylist
- Execution logged with full arguments and results
- Sandbox integration ready (Phase 4)

---

## UI Integration
- Tool calls appear in streaming response (tool_calls chunks)
- Tool executions logged in Tool Log panel with timestamps
- Confirmation dialog blocks until user responds
- Results returned to AI as tool_response messages

---

## Estimated Effort: 10 days
Can be implemented in 3 batches:
- Batch 1: Core + File tools (days 1-4)
- Batch 2: Search + Shell + Network tools (days 5-7)
- Batch 3: Orchestrator + UI integration + Confirmation (days 8-10)