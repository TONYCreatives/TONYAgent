"""Vendor-agnostic LLM API layer: one client, pluggable dialects, typed errors."""

from tonyagent.api.client import MIN_KEY_LENGTH, Health, LLMClient, normalize_key
from tonyagent.api.dialects import Chunk, Completion, Dialect
from tonyagent.api.errors import ErrorKind, KeyFormatError, KeyLengthError, LLMError

__all__ = [
    "LLMClient", "Health", "Dialect", "Chunk", "Completion",
    "LLMError", "ErrorKind", "KeyFormatError", "KeyLengthError", "MIN_KEY_LENGTH",
    "normalize_key",
]
