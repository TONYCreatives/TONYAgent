"""Tool JSON schemas for TONYAgent."""

from tonyagent.tools.base import ToolCategory


# File Tools
READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Read the contents of a file from the project folder.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "encoding": {"type": "string", "enum": ["utf-8", "latin-1", "cp1252"], "default": "utf-8"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": False,
    "requires_confirmation": False,
}

WRITE_FILE_SCHEMA = {
    "name": "write_file",
    "description": "Create or overwrite a file in the project folder.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "content": {"type": "string", "description": "File content to write"},
            "encoding": {"type": "string", "enum": ["utf-8", "latin-1"], "default": "utf-8"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": True,
    "requires_confirmation": True,
}

EDIT_FILE_SCHEMA = {
    "name": "edit_file",
    "description": "Edit a file by replacing old_text with new_text (exact match required).",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "old_text": {"type": "string", "description": "Exact text to replace"},
            "new_text": {"type": "string", "description": "New text to insert"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": True,
    "requires_confirmation": True,
}

DELETE_FILE_SCHEMA = {
    "name": "delete_file",
    "description": "Delete a file from the project folder (moves to recycle bin).",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": True,
    "requires_confirmation": True,
}

LIST_DIR_SCHEMA = {
    "name": "list_dir",
    "description": "List directory contents with optional recursion.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root", "default": "."},
            "recursive": {"type": "boolean", "description": "List recursively", "default": False},
            "max_depth": {"type": "integer", "description": "Max recursion depth", "default": 3},
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": False,
    "requires_confirmation": False,
}
# Search Tools
GREP_SCHEMA = {
    "name": "grep",
    "description": "Search for a regex pattern in file contents within the project.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Relative path to search in", "default": "."},
            "include": {"type": "string", "description": "File pattern to include (e.g., *.py)"},
            "case_sensitive": {"type": "boolean", "default": True},
            "max_results": {"type": "integer", "default": 100},
            "context_lines": {
                "type": "integer",
                "description": "Lines of context to show around each match",
                "default": 0,
            },
            "max_filesize_mb": {
                "type": "integer",
                "description": "Skip files larger than this many MB",
                "default": 10,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    "category": ToolCategory.SEARCH,
    "destructive": False,
    "requires_confirmation": False,
}

GLOB_SCHEMA = {
    "name": "glob",
    "description": "Find files matching a glob pattern within the project.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"},
            "path": {"type": "string", "description": "Relative path to search in", "default": "."},
            "max_results": {
                "type": "integer",
                "description": "Maximum paths to return",
                "default": 200,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    "category": ToolCategory.SEARCH,
    "destructive": False,
    "requires_confirmation": False,
}

# Shell Tools
EXECUTE_COMMAND_SCHEMA = {
    "name": "execute_command",
    "description": "Execute a shell command in the sandbox environment.",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "cwd": {"type": "string", "description": "Working directory (relative to project root)", "default": "."},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    "category": ToolCategory.SHELL,
    "destructive": True,
    "requires_confirmation": True,
    "sandbox_required": True,
    "isolation_required": True,
}

# Network Tools
HTTP_REQUEST_SCHEMA = {
    "name": "http_request",
    "description": "Make an HTTP request to a URL.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to request"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"], "default": "GET"},
            "headers": {"type": "object", "description": "HTTP headers", "additionalProperties": {"type": "string"}},
            "body": {"type": "string", "description": "Request body"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "category": ToolCategory.NETWORK,
    "destructive": False,
    "requires_confirmation": True,
}

# Browser Tools
BROWSER_NAVIGATE_SCHEMA = {
    "name": "browser_navigate",
    "description": "Navigate browser to a URL in the sandbox.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": True,
    "sandbox_required": True,
}

BROWSER_CLICK_SCHEMA = {
    "name": "browser_click",
    "description": "Click an element on the page by CSS selector.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of element to click"},
        },
        "required": ["selector"],
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": True,
    "sandbox_required": True,
}

BROWSER_TYPE_SCHEMA = {
    "name": "browser_type",
    "description": "Type text into an element by CSS selector.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of element"},
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["selector", "text"],
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": True,
    "sandbox_required": True,
}

BROWSER_EVAL_SCHEMA = {
    "name": "browser_eval",
    "description": "Evaluate JavaScript in the browser page context.",
    "parameters": {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "JavaScript code to evaluate"},
        },
        "required": ["script"],
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

BROWSER_SCREENSHOT_SCHEMA = {
    "name": "browser_screenshot",
    "description": "Capture a screenshot of the current browser page.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to save screenshot (relative to project root)", "default": ""},
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

EXECUTE_JS_SCHEMA = {
    "name": "execute_js",
    "description": "Execute JavaScript in Node.js context in the sandbox.",
    # SHELL, not BROWSER: it runs under Node, not in a page. It lives in
    # browser_tools.py only because it shares the runtime.
    "parameters": {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "JavaScript code to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10},
        },
        "required": ["script"],
        "additionalProperties": False,
    },
    "category": ToolCategory.SHELL,
    "destructive": False,
    "requires_confirmation": True,
    "sandbox_required": True,
    "isolation_required": True,
}

# Sandbox (read-only, in-container) Tools
SANDBOX_READ_FILE_SCHEMA = {
    "name": "sandbox_read_file",
    "description": (
        "Read a text file through the sandbox runtime, scoped to the project "
        "folder. Use this when you need the runtime's view of a file (e.g. a "
        "dependency installed only in the container image). For ordinary "
        "project files prefer read_file, which is simpler."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the project root (e.g. 'src/main.py')",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read",
                "default": 1048576,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

SANDBOX_LIST_FILES_SCHEMA = {
    "name": "sandbox_list_files",
    "description": (
        "List files through the sandbox runtime, scoped to the project folder. "
        "Use this to inspect the runtime's filesystem. For ordinary project "
        "files prefer list_dir, which is simpler."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory relative to the project root",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum recursion depth",
                "default": 3,
            },
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.FILE,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

BROWSER_GET_TEXT_SCHEMA = {
    "name": "browser_get_text",
    "description": (
        "Read the visible text of the current page, optionally scoped to one CSS "
        "selector. Prefer this over browser_eval('document.body.innerText')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to scope to (e.g. 'main' or 'h1')",
                "default": "",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 20000,
            },
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

BROWSER_WAIT_FOR_SCHEMA = {
    "name": "browser_wait_for",
    "description": (
        "Wait for a CSS selector to reach a state (visible, hidden, attached, "
        "detached), or wait for the page load state. Use before clicking or "
        "reading content that loads asynchronously."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to wait for (empty when state is load/networkidle)",
                "default": "",
            },
            "state": {
                "type": "string",
                "enum": ["visible", "hidden", "attached", "detached", "load", "networkidle"],
                "default": "visible",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds",
                "default": 10000,
            },
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

BROWSER_SCROLL_SCHEMA = {
    "name": "browser_scroll",
    "description": (
        "Scroll the page (or a specific element) up, down, to the top, or to the "
        "bottom. Use to reach content below the fold or to trigger lazy loading."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "top", "bottom"],
                "default": "down",
            },
            "amount": {
                "type": "integer",
                "description": "Pixels to scroll (ignored for top/bottom)",
                "default": 800,
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to scroll a specific element",
                "default": "",
            },
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

BROWSER_SNAPSHOT_SCHEMA = {
    "name": "browser_snapshot",
    "description": (
        "Get a text snapshot of the current page: the interactive elements (with "
        "CSS selectors you can pass to browser_click / browser_type) plus an ARIA "
        "outline. Call this FIRST after navigating, and again after any action that "
        "changes the page, so you know what is clickable. No vision model needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "interactive_only": {
                "type": "boolean",
                "description": "True (default) lists only actionable elements and trims the ARIA outline; False includes a longer outline",
                "default": True,
            },
            "max_elements": {
                "type": "integer",
                "description": "Maximum elements to list",
                "default": 100,
            },
        },
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

SET_VIEWPORT_SIZE_SCHEMA = {
    "name": "set_viewport_size",
    "description": (
        "Set the browser viewport size for responsive testing (for example "
        "390x844 for a phone). Use reset=true to restore the default."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "width": {"type": "integer", "description": "Viewport width in pixels"},
            "height": {"type": "integer", "description": "Viewport height in pixels"},
            "reset": {
                "type": "boolean",
                "description": "Restore the default 1280x720 viewport",
                "default": False,
            },
        },
        "required": ["width", "height"],
        "additionalProperties": False,
    },
    "category": ToolCategory.BROWSER,
    "destructive": False,
    "requires_confirmation": False,
    "sandbox_required": True,
}

# All schemas



ALL_SCHEMAS = [
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    EDIT_FILE_SCHEMA,
    DELETE_FILE_SCHEMA,
    LIST_DIR_SCHEMA,
    GREP_SCHEMA,
    GLOB_SCHEMA,
    EXECUTE_COMMAND_SCHEMA,
    HTTP_REQUEST_SCHEMA,
    BROWSER_NAVIGATE_SCHEMA,
    BROWSER_CLICK_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    BROWSER_EVAL_SCHEMA,
    BROWSER_SNAPSHOT_SCHEMA,
    SET_VIEWPORT_SIZE_SCHEMA,
    BROWSER_GET_TEXT_SCHEMA,
    BROWSER_WAIT_FOR_SCHEMA,
    BROWSER_SCROLL_SCHEMA,
    BROWSER_SCREENSHOT_SCHEMA,
    EXECUTE_JS_SCHEMA,
    SANDBOX_READ_FILE_SCHEMA,
    SANDBOX_LIST_FILES_SCHEMA,
]

SCHEMAS_BY_NAME = {s["name"]: s for s in ALL_SCHEMAS}