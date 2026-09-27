# NEXT_SESSION.md — TONYAgent Handoff

**Project:** TONYAgent — local-first desktop AI agent
**Last updated:** 2026-09-27, after the headless-core extraction
**Status:** Core is UI-independent and fully tested. The Tkinter UI is a thin
client over `AgentSession`. The Tauri frontend is scaffolded but **cannot build
yet** (no MSVC linker). Everything green: **Python 197 passed, TypeScript 13
passed**.

---

## 0. Read this first

### How to run

```bash
cd C:\Users\iig2y\Desktop\TONYAgent
python -m tonyagent          # Tkinter GUI
```

### How to verify (run all of these before trusting a change)

```bash
python -m compileall -q src            # syntax
python -m pytest tests -q              # 197 passed
python scripts/check_all.py --fast     # 3 checks incl. GUI launch

cd app && npm test                     # 13 passed (protocol, no Rust needed)
```

`check_all.py` without `--fast` opens a real window and will exceed a 30s
command timeout. Use `--fast`, then run the launch check separately.

### Architecture in one picture

```
        Tkinter UI  ----------+
                              |
        Tauri UI  ------------+-->  AgentSession  -->  events
        (headless/server.py)          (core/session.py)  (core/events.py)
                                            |
                                            +--> LLMClient  (api/)
                                            +--> providers  (providers/)
                                            +--> tools      (tools/)
                                            +--> sandbox    (sandbox/)
```

The core imports **no GUI toolkit**. That is enforced by a test, not by
convention — see §6.

---

## 1. What changed most recently

### 1.1 Bugs found and fixed while preparing the migration

These were live production bugs, not theoretical:

| Bug | Symptom | Root cause | Fix |
|---|---|---|---|
| **Tools never executed** | Every tool call silently did nothing | `MainWindow._generate_response` is `async def` but called the *sync* `execute_tool()`, which raises `RuntimeError` inside a live event loop. A blanket `except Exception` swallowed it. | `await execute_tool_async()` |
| **`CTkComboBox is not a valid model ID`** | 400 from OpenRouter; status bar showed `openrouter/CTkComboBox` | `CTkComboBox.get()` returns **its own class name** when nothing is set, and the model combo was built with `values=[]` | `PillComboBox.get()` override returns `""`; `ProviderFactory._is_valid_model_id()` rejects implausible ids |
| **Truncated key accepted** | `401 User not found` for a 35-char OpenRouter key | `MIN_KEY_LENGTH = 20` was a global floor; a real key is 73 chars | `KeyLengthError` + per-provider `key_length` + `normalize_key()` |
| **Key leaked to disk** | plaintext key in `scripts/k2.log` | a diagnostic script printed `repr(key[7:])` | log deleted, script rewritten, key rotated by the user |

The `execute_tool` bug is the one to remember: **the app had never run a tool.**
An older `NEXT_SESSION.md` flagged it as "unverified"; it had been real for the
whole project.

---

## 2. The wire protocol (contract for the future UI)

Newline-delimited JSON on the sidecar's **stdout**. Logs go to **stderr** —
stdout is protocol-only, or the frontend will parse log lines as JSON.

### Request / reply
```json
{"id":1,"method":"send","params":{"text":"Hi"}}
{"id":1,"result":{"turn_id":"191908db..."}}
{"id":1,"error":{"code":"rejected","message":"no provider configured"}}
```

### Event (a push, not a response)
```json
{"event":true,"type":"message.delta","seq":3,"turn_id":"191908db...","payload":{"text":"Hel"}}
```

### Methods

| Method | Params | Result |
|---|---|---|
| `ping` | — | `{pong, protocol}` |
| `state` | — | `{provider, model, busy, messages}` |
| `send` | `{text}` | `{turn_id}` |
| `cancel` | — | `{cancelled}` |
| `clear` | — | `{cleared}` |
| `bind_provider` | `{name, model?}` | `{provider, model}` |
| `sandbox.start` | `{path?}` | `{running}` |
| `sandbox.stop` | — | `{running}` |
| `sandbox.stats` | — | stats dict |
| `confirm.respond` | `{id, confirmed}` | `{id, confirmed}` |
| `trust.set` | `{project, trusted}` | `{project, trusted}` |

### Event types

`turn.started` `turn.finished` `turn.failed` `message.started` `message.delta`
`message.completed` `tool.started` `tool.completed` `tool.failed`
`confirmation.requested` `confirmation.resolved` `sandbox.status`
`sandbox.stats` `log` `error`

### Invariants — do not break these

1. **The reply to a request is written before any events that request causes.**
   A turn id is therefore known before its first delta. Enforced by
   `test_the_reply_for_a_request_comes_before_its_events` and its TS twin.
2. **Events carry no `id`; replies always do.** That is how a client tells them apart.
3. **A malformed line must not kill the server** — it replies `bad_request`
   and keeps serving.
4. **A rejection is a reply, never a push.** `send` on a busy session used to
   emit an ERROR event *before* the reply, which a client cannot attribute. Fixed.

---

## 3. The Tauri frontend (`app/`) — scaffolded, not buildable yet

```
app/
  tauri.conf.json           productName, window, CSP, externalBin
  capabilities/default.json shell:allow-execute + allow-spawn for the sidecar
  src/backend.ts            TauriBackend + LineTransport + protocol types
  src/backend.test.ts       13 protocol tests
  package.json, tsconfig.json
```

### Why the transport is an interface

`TauriBackend` takes a `makeTransport` factory; the real one lazily requires
`@tauri-apps/plugin-shell`. So the protocol is testable in plain Node with **no
Tauri, no Rust and no Python**. `npm test` compiles the two files with `tsc`
into `.tmp/` and runs `node --test`. This is why the protocol is provable today
even though the app cannot be built.

### What is missing

- `app/src-tauri/` — `Cargo.toml`, `src/main.rs`, `build.rs`
- `app/index.html`, `app/src/main.tsx`, React components
- `app/src-tauri/binaries/tonyagent-core-<target>.exe` (PyInstaller output)
- an app icon

---

## 4. BLOCKER: MSVC build tools missing

Rust **is** installed:

```
rustc 1.98.1 (48a229cea 2026-09-01)
cargo 1.98.1
rustup 1.29.1
stable-x86_64-pc-windows-msvc (default), profile: minimal
PATH: C:\Users\iig2y\.cargo\bin   (registered in the USER path)
```

WebView2 runtime is present (154.0.4258.37) — that requirement is satisfied.

**But a minimal `cargo build` fails:**

```
error: linker `link.exe` not found
  = note: please ensure that Visual Studio 2017 or later, or Build Tools for
          Visual Studio were installed with the Visual C++ option
  = note: VS Code is a different product, and is not sufficient
```

No Visual Studio, no Windows SDK, no `link.exe` on this machine. **Tauri
produces a native Windows binary and cannot link until this is installed.**

### Fix (the user was installing this at handoff)

Visual Studio Build Tools for Visual Studio 2022, workload
"Desktop development with C++" (~6-8 GB). Or unattended:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

### Smoke test after install

Do this **before** writing any Tauri Rust code. It is a two-minute check that
separates "my code is wrong" from "the toolchain is missing".

```powershell
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
cd $env:TEMP; mkdir rusttest; cd rusttest
# Cargo.toml: [package] name/version/edition + [[bin]] name/path
# main.rs:    fn main() { println!("hi"); }
cargo build     # must succeed
```

---

## 5. Non-obvious things a future session must know

1. **Docker Desktop is not a Windows service** on this machine. Start it with
   `Start-Process "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"`
   and wait 2-3 min; the engine pipe is absent until then.
2. **The sandbox container name is fixed** (`tonyagent-sandbox`) and `start()`
   removes a same-named container as stale. Two TONYAgent processes (or pytest
   beside the app) **will kill each other's sandbox**. Override with
   `TONYAGENT_SANDBOX_CONTAINER=<name>`. Never run `pytest -m docker` and
   `scripts/e2e_*.py` concurrently.
3. **The console is cp949** and crashes scripts that print emoji or a checkmark.
   Keep new scripts ASCII-only. Force UTF-8 with `$env:PYTHONIOENCODING="utf-8"`.
4. **PowerShell swallows native stderr.** `python x.py` writing to stderr makes
   the runner report "command failed" and hides stdout. Use
   `cmd /c "... > out.txt 2>&1"` and then read the file.
5. **Node test runs do not always exit.** `node --test` left a process alive on
   this machine; use `Start-Process -PassThru` + `WaitForExit(ms)` + `Kill()`.
6. **The OpenRouter key in the keyring is rate/credit limited:**
   `403 {"message":"Key limit exceeded (total limit)"}`. The key itself is valid
   (73 chars, `/models` returns 458 entries). Raise the limit in the OpenRouter
   dashboard or use a different key. This is **not** a code problem.
7. `execute_command` **fails closed** with no sandbox unless
   `tools.fallback_to_local=true` (env `TONYAGENT_TOOLS__FALLBACK_TO_LOCAL`).
8. `orchestrator.execute_tool()` is **sync** and raises if called from async
   context. From a coroutine use `await tool_orchestrator.execute_tool_async()`.

---

## 6. The one boundary that must not break

`tests/unit/test_headless_core.py::test_core_import_does_not_pull_in_a_gui_toolkit`
spawns a subprocess, imports `tonyagent.core.session` and
`tonyagent.headless.server`, and asserts `sys.modules` contains neither
`tkinter` nor `customtkinter`.

This exists because `core/__init__.py` used to re-export `TONYAgentApp`, which
imports customtkinter — so **any** `tonyagent.core.*` import dragged in a GUI
toolkit and made the core unusable as a sidecar. It is now a lazy
`__getattr__`, and `from tonyagent.core import TONYAgentApp` still works.

If that test ever fails, the headless boundary is broken. **Fix the import, do
not delete the test.**

---

## 7. Remaining work, in the order it should be done

### 7.1 Blocked on MSVC

1. Verify `cargo build` on a hello-world (see section 4).
2. Write `app/src-tauri/` — `Cargo.toml`, `src/main.rs`, `build.rs`.
3. Bundle the core: PyInstaller the sidecar into
   `app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe`.
4. Write the React UI. It only subscribes to events; no turn logic lives there.
5. `npm run tauri dev`.

### 7.2 Not blocked — do these any time

- `read_file` offset/limit
- `edit_file` `replace_all`
- unify timeout units on `timeout_ms`
- `http_request` / `fetch_url` file download
- a "list definitions" tool
- single-source the tool schema/registry
- per-turn output budget
- reset browser page state between runs
- **finish the chat bubble width fix** (see section 8)

---

## 8. Known incomplete work

**Chat bubbles are still full-width.** The intent was for them to hug their
text, but `grid_columnconfigure(0, weight=0)` on the customtkinter frame did not
achieve it; a user message still spans the whole chat column. The wraplength
calculation (`_bubble_wrap_width`) works, the width does not. Fix by measuring
(`winfo_reqwidth`) rather than assuming the grid respects weight, and **verify by
screenshot** — the previous attempt "passed" tests that never checked pixels.

**`test_phase4_ux.py` is intermittently flaky.** Multiple Tk roots created and
destroyed in one process can leave Tcl in a bad state
(`invalid command name "tcl_findLibrary"`). It passes alone and per-file. Not
caused by the refactor. A session-scoped root fixture would fix it.

**`RuntimeWarning: coroutine ... was never awaited`** in
`tests/unit/test_tool_sandbox_routing.py:875` — two occurrences, pre-existing.

---

## 9. Decisions made, and why

- **Keep the Python core, replace only the UI.** A survey of comparable
  projects found the closest precedent is Goose (Block): a native core plus a
  TypeScript UI. A full core rewrite would discard 197 tests and 22 tools.
- **JSONL over stdio, not a local HTTP server.** Tauri owns the sidecar
  lifecycle, so it starts and dies with the app. No port to collide with, no
  auth, no CORS, and a dead pipe is an unambiguous failure signal.
- **Events plus request/reply, not one or the other.** The UI must both ask
  questions and receive unsolicited progress.
- **Exact per-provider `key_length`.** A prefix check plus a 20-char floor let
  a truncated key through and produced a baffling server-side error.
- **Injectable transport in the TS client.** Keeps the protocol verifiable
  without the build toolchain, and keeps Tauri out of the business logic.



