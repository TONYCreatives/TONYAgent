"""Tools package for TONYAgent."""

from tonyagent.tools.base import (
    Tool,
    ToolResult,
    ToolResultStatus,
    ToolCategory,
    ToolRegistry,
    tool_registry,
    register_tool,
)

# Import all tools to trigger registration.
#
# **This has to happen before the schemas are imported below**, and the order is
# the whole reason it is written this way. `tonyagent.tools.schemas` derives
# `ALL_SCHEMAS` from the registry on first access, so reaching for it while the
# registry is still empty binds an empty list -- and an empty tool list is not an
# error anywhere, it is a model that is offered no tools at all. The tool modules
# import `tonyagent.tools.base` and `tonyagent.tools.runtime_access`, never this
# package, so importing them from here is safe.
from tonyagent.tools import (
    file_tools,
    search_tools,
    shell_tools,
    network_tools,
    browser_tools,
    sandbox_file_tools,
    screen_tools,
    job_tools,
    planning_tools,
    user_tools,
    subagent_tools,
)

from tonyagent.tools.schemas import (
    ALL_SCHEMAS,
    SCHEMAS_BY_NAME,
    READ_SCHEMA,
    WRITE_SCHEMA,
    EDIT_SCHEMA,
    DELETE_FILE_SCHEMA,
    LIST_DIR_SCHEMA,
    GREP_SCHEMA,
    GLOB_SCHEMA,
    EXECUTE_COMMAND_SCHEMA,
    HTTP_REQUEST_SCHEMA,
    SANDBOX_READ_FILE_SCHEMA,
    SANDBOX_LIST_FILES_SCHEMA,
    # Was named in `__all__` without ever being imported, so `from
    # tonyagent.tools import TAKE_SCREENSHOT_SCHEMA` raised AttributeError and
    # `import *` did too. It resolves now like the rest of them.
    TAKE_SCREENSHOT_SCHEMA,
)
from tonyagent.tools.orchestrator import (
    ToolOrchestrator,
    ToolCall,
    ConfirmationRequest,
    tool_orchestrator,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolResultStatus",
    "ToolCategory",
    "ToolRegistry",
    "tool_registry",
    "register_tool",
    "ALL_SCHEMAS",
    "SCHEMAS_BY_NAME",
    "READ_SCHEMA",
    "WRITE_SCHEMA",
    "EDIT_SCHEMA",
    "DELETE_FILE_SCHEMA",
    "LIST_DIR_SCHEMA",
    "GREP_SCHEMA",
    "GLOB_SCHEMA",
    "EXECUTE_COMMAND_SCHEMA",
    "HTTP_REQUEST_SCHEMA",
    "SANDBOX_READ_FILE_SCHEMA",
    "SANDBOX_LIST_FILES_SCHEMA",
    "TAKE_SCREENSHOT_SCHEMA",
    "ToolOrchestrator",
    "ToolCall",
    "ConfirmationRequest",
    "tool_orchestrator",
]
