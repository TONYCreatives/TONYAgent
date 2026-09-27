# Phase 2: Provider Abstraction & Streaming Chat

## Objective
Complete the provider abstraction layer with all built-in providers and integrate streaming chat into the UI.

---

## Current State
- `base.py`: Protocol + BaseLLMProvider + Registry (incomplete - truncated)
- `openai.py`: Only imports (401 bytes)
- `registry.py`: Exports only
- No other providers exist

---

## Implementation Plan

| # | Action | Files | Tool |
|---|--------|-------|------|
| 1 | Fix/complete `base.py` - restore full protocol and base classes | `src/tonyagent/providers/base.py` | write |
| 2 | Complete OpenAI provider with full streaming + function calling | `src/tonyagent/providers/openai.py` | write |
| 3 | Create Anthropic provider (Claude 3.5 Sonnet/Haiku/Opus) | `src/tonyagent/providers/anthropic.py` | write |
| 4 | Create Google Gemini provider | `src/tonyagent/providers/gemini.py` | write |
| 5 | Create Mistral provider (OpenAI-compatible) | `src/tonyagent/providers/mistral.py` | write |
| 6 | Create Groq provider (OpenAI-compatible) | `src/tonyagent/providers/groq.py` | write |
| 7 | Create OpenRouter provider (OpenAI-compatible) | `src/tonyagent/providers/openrouter.py` | write |
| 8 | Create Ollama provider (local, /api/chat) | `src/tonyagent/providers/ollama.py` | write |
| 9 | Create Custom endpoint provider (user-defined base_url) | `src/tonyagent/providers/custom.py` | write |
| 10 | Update `__init__.py` to export all providers | `src/tonyagent/providers/__init__.py` | write |
| 11 | Add provider factory with credential loading from keyring | `src/tonyagent/providers/factory.py` | write |
| 12 | Integrate streaming chat into MainWindow (chat_completion call, chunk handling, tool call parsing) | `src/tonyagent/ui/views/main_window.py` | edit |
| 13 | Add token estimation display in UI | `src/tonyagent/ui/views/main_window.py` | edit |
| 14 | Add "Test Connection" functionality in provider panel | `src/tonyagent/ui/views/main_window.py` | edit |

---

## Provider Details

| Provider | SDK | Base URL | Auth | Streaming | Function Calling |
|----------|-----|----------|------|-----------|------------------|
| OpenAI | openai | api.openai.com | Bearer | ✅ | ✅ |
| Anthropic | anthropic | api.anthropic.com | x-api-key | ✅ | ✅ (tools) |
| Gemini | google-generativeai | generativelanguage.googleapis.com | Bearer | ✅ | ✅ |
| Mistral | openai (compat) | api.mistral.ai | Bearer | ✅ | ✅ |
| Groq | openai (compat) | api.groq.com | Bearer | ✅ | ✅ |
| OpenRouter | openai (compat) | openrouter.ai/api/v1 | Bearer | ✅ | ✅ |
| Ollama | ollama / httpx | localhost:11434 | None | ✅ | ⚠️ Limited |
| Custom | openai (compat) | User-defined | Bearer | ✅ | ✅ |

---

## UI Integration Requirements

1. **Streaming Response Handling**
   - Background thread calls `provider.chat_completion(stream=True)`
   - Chunks sent to UI via `schedule_on_ui()` / `queue.Queue`
   - Incremental markdown rendering in chat area
   - Tool call streaming (partial arguments)

2. **Cancellation**
   - Stop button sets `CancellationToken`
   - Provider stream closed gracefully
   - Partial response preserved in history

3. **Token Counting**
   - Pre-flight estimate shown in composer
   - Actual usage from response displayed

4. **Provider Panel**
   - "Test Connection" button calls `validate_credentials()`
   - Load/save API key from keyring
   - Model dropdown populated from provider models

---

## Dependencies (already in pyproject.toml)
- openai, anthropic, google-generativeai, ollama, httpx

---

## Acceptance Criteria
- [ ] All 8 providers registered and instantiable
- [ ] Streaming chat works end-to-end (user sends → AI streams response)
- [ ] Tool calls visible in streaming (partial args)
- [ ] Stop button cancels generation
- [ ] Token count displayed
- [ ] Test Connection works for each provider
- [ ] API keys loaded from keyring automatically
- [ ] Custom endpoint configurable and testable

---

## Estimated Effort: 10 days (per plan)
Implementation can be done in parallel batches (providers 3-9 are independent).