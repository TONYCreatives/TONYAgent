# NEXT_SESSION.md — TONYAgent Handoff

**Project:** TONYAgent — local-first desktop AI agent
**Last updated:** 2026-09-27, after the Tauri app built and ran end to end
**Status:** Core is UI-independent and fully tested. The Tkinter UI is a thin
client over `AgentSession`. **The Tauri app now builds, launches, spawns the
core sidecar, and completes a round trip.** Everything green: **Python 197
passed, TypeScript 13 passed, Tauri MSI + NSIS installers produced.**

The MSVC blocker from the previous handoff is resolved: Visual Studio Community
2026 is installed and `cargo build` links. See section 4.

---

## 0. Read this first

### How to run

```bash
cd C:\Users\iig2y\Desktop\TONYAgent
python -m tonyagent          # Tkinter GUI

# Tauri app (needs the sidecar built once first)
python scripts/build_sidecar.py
cd app && npm run tauri:dev  # or: npm run tauri:build
```

Both UIs are clients of the same core. The Tkinter one is the mature path; the
Tauri one is new and thinner (chat, sandbox status, confirmations).

### How to verify (run all of these before trusting a change)

```bash
python -m compileall -q src            # syntax
python -m pytest tests -q              # 197 passed
python scripts/check_all.py --fast     # 3 checks incl. GUI launch

cd app && npm test                     # 13 passed (protocol, no Rust needed)
cd app && npm run typecheck            # whole app, incl. React components
```

`npm run build` runs `tsc --noEmit && vite build`, so a type error in a
component fails the build. `npm test` deliberately still compiles only the two
protocol files, which is what keeps it runnable without Tauri installed.

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

### 1.2 Bugs found while building the Tauri app

Same character as 1.1: each one produced a build or a window that looked
correct and silently did nothing.

| Bug | Symptom | Root cause | Fix |
|---|---|---|---|
| **Frozen core died at startup** | sidecar exited before serving a request; `ModuleNotFoundError: No module named '3c22db458360489351e4__mypyc'` | `tomli` is mypyc-compiled and each mypyc package ships its own hash-prefixed `__mypyc` runtime. `collect_all()` only walks *inside* the package dir, so the top-level runtime was never collected. The hash changes every release, so it cannot be named. | `scripts/sidecar.spec` globs `*__mypyc*.pyd` from site-packages |
| **Sidecar never spawned** | window opens, says "disconnected", no error | `makeSidecarTransport` used `require()`, which does not exist in an ES module. The fallback `globalThis.__tauriRequire` was never defined by Vite either, so the spawn threw. | dynamic `import()` — resolves in Node for the tests and in a real chunk for the app |
| **`write`/`kill` on the wrong object** | type errors masked by `any` | `spawn()` returns a `Child` that owns stdin and kill(); `Command` only emits output. The code called them on `Command`. Once the `any` was removed the compiler caught it. | hold both; `child.write` / `child.kill` |
| **Process exit went unnoticed** | UI stuck on "connected" after the core died | exit is the Command's `close` event, not a Child method | subscribe to `close` **and** `error` |
| **Config in the wrong directory** | `failed to watch app\Cargo.toml` | in Tauri v2, `tauri.conf.json` and `capabilities/` belong inside `src-tauri/` | moved |
| **Three separate naming mismatches** | three distinct runtime errors, all reading as "disconnected" | `externalBin`, `Command.sidecar()` and the capability `allow` list must all carry the *same* string, and Tauri appends the triple itself | all three are `binaries/tonyagent-core` — see section 3 |
| **stdin rejected by ACL** | sidecar starts, every request fails `plugin:shell\|stdin_write not allowed by ACL` | `stdin_write` is a separate plugin command from `spawn` | added `shell:allow-stdin-write` and `shell:allow-kill` |

The pattern worth keeping: **the sidecar's stderr is the only place core-side
failures appear**, because stdout is protocol-only. The React UI now renders it
in a log strip, and the error banner shows Tauri's exact message. Without that,
every one of the above presented as an unexplained "disconnected".

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

## 3. The Tauri frontend (`app/`) - builds and runs

```
app/
  index.html                Vite entry
  vite.config.ts            base "./", port 1420
  src/
    main.tsx                mounts App
    App.tsx                 owns backend lifecycle, wires everything
    events.ts               reduces core events to render state
    MessageList.tsx         transcript + tool rows
    Composer.tsx            input, Enter to send
    ConfirmDialog.tsx       destructive-action prompt
    StatusBar.tsx           provider / sandbox / connection
    styles.css              light+dark tokens
    backend.ts              the protocol client (13 tests)
  src-tauri/
    tauri.conf.json         productName, window, CSP, externalBin, icons
    capabilities/default.json
    Cargo.toml, build.rs, src/main.rs, src/lib.rs
    icons/                  generated from icons/icon.svg
    binaries/               PyInstaller sidecar output (gitignored)
```

The Rust side is deliberately tiny: it opens a window and registers the shell
plugin. All protocol logic is in `src/backend.ts`, already covered by tests.

### Building the sidecar

```bash
python scripts/build_sidecar.py          # ~45 MB exe into src-tauri/binaries/
```

PyInstaller spec is `scripts/sidecar.spec`. It **excludes `tkinter`,
`customtkinter` and `playwright`** - the headless core must not pull in a GUI
toolkit (that boundary is tested), and Playwright runs inside the Docker
sandbox, not on the host.

The frozen binary speaks the protocol correctly. Verified directly against the
built exe: `ping`, `state`, an unknown method, a malformed line, and a second
`ping` all behave per section 2 - a bad line replies `bad_request` and the
server keeps serving.

### Layout rules that cost real time (tauri 2.12)

These were each a silent failure with a build that looked fine:

1. **`tauri.conf.json` and `capabilities/` live INSIDE `src-tauri/`.** With
   them at `app/`, the CLI resolves the Tauri dir to `app/` and fails with
   `failed to watch app\Cargo.toml`.
2. **`frontendDist` is `../dist`** once the config is in `src-tauri/`.
3. **`bundle.externalBin` is the BARE name** (`binaries/tonyagent-core`).
   Tauri appends `-<target-triple>` itself; putting the triple in the config
   gives `resource path ...-<triple>-<triple>.exe doesn't exist`.
4. **`Command.sidecar()` takes the same string as `externalBin`**, so it is
   also `binaries/tonyagent-core`. Tauri compares them literally (also
   accepting the name minus `.exe`). The bare `tonyagent-core` fails with
   `sidecar not configured under tauri.conf.json > bundle > externalBin`.
5. **The capability `allow` entries use the same `binaries/tonyagent-core`
   name.** The bare name fails with `Scoped command ... not found`.
6. **`shell:allow-stdin-write` is required as a separate permission.** With
   only `allow-execute`/`allow-spawn`, the sidecar *starts* and every request
   then fails with `Command plugin:shell|stdin_write not allowed by ACL`.
   `shell:allow-kill` is granted for the same reason (teardown).

Points 4-6 all fail at *runtime*, not build time, and the only symptom is a
window that says "disconnected". If that happens again, read the error banner:
it carries Tauri's exact message.

### Debugging a release build

`PrintWindow`/screenshot capture is unreliable for a WebView2 window. To see
the real error instead:

```powershell
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9333"
.	onyagent-app.exe
# then query http://localhost:9333/json/list and evaluate in that target
```

The UI surfaces the same thing: the error banner shows the plugin's message and
a log strip shows core stderr (core logs to stderr because stdout is
protocol-only).

---

## 4. Toolchain: MSVC is installed

`cargo build` links. The previous handoff's blocker is resolved.

```
Visual Studio Community 2026 at C:\Program Files\Microsoft Visual Studio8\Community
VC tools 14.51.36231 (link.exe present)
rustc 1.98.1, cargo 1.98.1, WebView2 154.0.4258.37
tauri-cli 2.12.0, PyInstaller 6.21.0
```

Note `where link.exe` also matches Git's `usr/bin/link.exe`, which is a
coreutils symlink and not a linker. The VS install is what unblocked the build;
a successful link is the proof.

`tauri build` produces both an MSI and an NSIS installer (~48 MB each,
sidecar included).

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

### 7.1 Done (was blocked on MSVC)

1. `cargo build` verified.
2. `app/src-tauri/` written.
3. Core bundled via `scripts/build_sidecar.py`.
4. React UI written; it only subscribes to events, no turn logic.
5. `npm run tauri dev` and `npm run tauri:build` both work; the app was
   confirmed running, connected, and completing a send.

### 7.2 Next, in the Tauri UI

These are UI gaps, not core gaps. The core already supports each.

1. **Project folder picker.** `sandbox.start` takes a `path`, but nothing in
   the UI chooses one, so the sandbox can only ever start on the cwd. Needs
   `@tauri-apps/plugin-dialog` (already a dependency).
2. **Settings panel** for provider/model binding (`bind_provider`). The status
   bar shows the current provider but there is no way to change it from the UI.
3. **API key entry.** The key lives in the OS keyring and there is no core
   method for setting it, so this needs a new method on the protocol first.
4. **Sandbox controls** — start/stop buttons. `sandbox.start`/`.stop` are
   implemented and unwired.
5. **Markdown rendering** for assistant text. Currently plain text; the core
   already depends on `markdown2` for the Tkinter UI.
6. **`events.ts` has no tests.** It is pure and easy to cover; the 13 existing
   tests only cover `backend.ts` framing.

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

**Tkinter chat bubbles are still full-width.** The intent was for them to hug
their text, but `grid_columnconfigure(0, weight=0)` on the customtkinter frame
did not achieve it. The wraplength calculation (`_bubble_wrap_width`) works, the
width does not. Fix by measuring (`winfo_reqwidth`) rather than assuming the
grid respects weight, and **verify by screenshot** — the previous attempt
"passed" tests that never checked pixels.

Note this is a **Tkinter-only** problem. The React UI gets it right with
`width: fit-content` and needs no measurement: a short bubble measured 95 px
inside a 1152 px column. If the Tkinter UI is ever retired, this item goes with
it. See section 3.

**`test_phase4_ux.py` is intermittently flaky.** Multiple Tk roots created and
destroyed in one process can leave Tcl in a bad state
(`invalid command name "tcl_findLibrary"`). It passes alone and per-file. Not
caused by the refactor. A session-scoped root fixture would fix it.

Re-confirmed 2026-09-27 while building the Tauri app, and it is **pre-existing**
(`git diff HEAD -- src tests` was empty at the time, so no Python had changed).
The test that actually fails is
`test_key_hint_and_forget_button_do_not_overlap`, which asserts real widget
geometry from `winfo_rootx/rooty` — so it depends on layout having settled. It
passed 6/6 in isolation and failed 2 of 4 full-suite runs, which is the
signature of a timing/state dependency rather than a real layout regression.
`check_all.py --fast` therefore reports FAIL intermittently; that is this, not
a new break.

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



