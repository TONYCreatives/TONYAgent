# NEXT_SESSION.md — TONYAgent Handoff

**Project:** TONYAgent — local-first desktop AI agent
**Last updated:** 2026-09-27, after Phase 5 (custom model + endpoint, first live
turn check)
**Status:** Core is UI-independent and fully tested. **The Tauri app builds,
launches, spawns the core sidecar, and every control in it is wired to a real
protocol method.** Everything green: **Python 244 passed, TypeScript 54 passed,
Tauri MSI + NSIS installers produced.**

Five phases of work landed since the MSVC blocker was cleared:

| Phase | What it did |
|---|---|
| 1 | Folder picker, settings panel, provider binding, sandbox start/stop. All three greyed rail icons went live |
| 2 | `key.save`/`key.delete` (OS keyring, with a real no-leak design) and a `search` method that delegates to the agent's own grep |
| 3 | The four composer modes became real permissions, and the Files tree reports diffs the core measured instead of counting tool calls |
| 4 | Assistant text is rendered as Markdown, parsed to a token tree and built as React elements so untrusted model output never becomes raw HTML |
| 5 | The model field is free text (OpenRouter's namespaced ids, any self-hosted gateway) and `bind_provider` accepts an optional `base_url`, which is what makes the `custom` provider reachable from the UI at all |

The Tkinter UI is untouched throughout and still the mature path. See
sections 1.3-1.6 for what each phase changed and why.

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
python -m pytest tests -q              # 244 passed
python scripts/check_all.py --fast     # 3 checks incl. GUI launch

cd app && npm test                     # 54 passed (protocol + reducer + markdown, no Rust needed)
cd app && npm run typecheck            # whole app, incl. React components
```

`npm run build` runs `tsc --noEmit && vite build`, so a type error in a
component fails the build. `npm test` compiles only the two protocol modules
(`backend.ts`, `events.ts`) and their tests, which is what keeps it runnable
without Tauri or Rust installed. It is no longer just `backend.ts` — the
reducer gained its own suite in Phase 3, and that suite found a real bug.

**One test is flaky, and it is not yours.** `check_all.py --fast` will
occasionally report FAIL from
`test_phase4_ux.py::test_key_hint_and_forget_button_do_not_overlap`. It passes
in isolation and in most full runs. It has been failing in 2 of ~6 full-suite
runs since before Phase 1. Section 8 has the details; re-run before believing
it.

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
| **Sidecar build script crashed** | `NameError: name 'ensure_external_bin' is not defined` | a rename updated the *call* but left the *definition* on the old name, so the script died after an otherwise successful 45 MB build | both sides renamed; a definition-vs-call check guards it |
| **Window stuck on "disconnected" under StrictMode** | banner `Backend is not running`, while a working sidecar ran unowned in the background | React 19 StrictMode mounts, unmounts and remounts every effect, so `start -> stop -> start` genuinely races. A sidecar's exit event is delivered *asynchronously*, so the one just killed reported "exited" **after** its replacement was assigned, and `onExit` nulled `this.transport` unconditionally - disposing the healthy new backend. | `onExit` returns early unless `this.transport` is still its own transport; `start`/`stop` are serialised through one promise chain |
| **Sandbox ran but could not read its own workspace** | `search` and every file tool answered `No project folder selected` while the container was mounted and healthy | `start_sandbox(path)` mounts the container but never called `folder_manager.set_folder`. Only the Tkinter UI did, so the sidecar had a sandbox and no project | `_h_sandbox_start` registers the folder **before** starting, so a bad path fails before a container exists |
| **Tool arguments were echoed into the on-screen log** | the log strip showed `write_file({'path': 'a.py', 'content': <the entire file>})` | the orchestrator interpolated `tool_call.arguments` whole, and that log is rendered in the React UI *and* written to stderr. A user who asked the agent to write a config holding a credential saw it echoed back -- the same leak Phase 2 closed for API keys | `_summarise_args`: values over 24 chars become `<N chars>`, containers become `<dict>`. Paths survive, contents do not |
| **Every `schedule_on_ui` callback was silently dropped under the sidecar** | LOG events never reached the React UI; the log strip only showed stderr and looked fine | the queue is drained only by `process_ui_queue`, which returns immediately when `_ui_root` is None -- and there is no Tk root under Tauri. It *looked* correct because loguru writes the same message to stderr independently | call through immediately when there is no UI root. This is the second time this layer ate a callback |
| **`events.ts` mutated the state it was given** | invisible while every caller replaced the whole object; corrupts any `useMemo` dependency or replayed event | `applyEvent` did `messages.slice()`, copying the array but not the messages, so `target.tools = [...]` wrote through to the caller's state | `copyMessages` deep-copies each message and its tools. Found by the first `events.test.ts` |
| **`tauri dev` died at startup** | `EBUSY: resource busy or locked, watch '...build_script_build.exe'` | Vite's watcher walks the project root, including `src-tauri/target/`. Cargo holds those `.exe` files open and `fs.watch` fails on Windows, killing Vite and taking the dev command with it | `server.watch.ignored` excludes `src-tauri/**` |
| **A saved key had no effect** | after saving the OpenRouter key, the first message was rejected `no provider configured`, while `state` cheerfully reported provider `openrouter` | the core session starts with a provider *name* but no provider *object*; only the settings panel's Apply button ever called `bind_provider`. Neither startup nor a key save bound one, so the UI showed a provider it could not actually use | `App` binds on startup and rebinds after a key save (which also rebuilds the provider, clearing an HTTP client cached before the key existed) |
| **`No models provided` when no model was chosen** | binding a provider without picking a model sent an empty model id and the API rejected the request | `ProviderRegistry.create` passed `model=""` explicitly, clobbering every provider's constructor default (`openrouter/auto`, `gpt-4o-mini`, `claude-3-5-sonnet-20241022`, ...) | omit an empty model so the class default applies; `session.bind_provider` now records the *resolved* model so `state` agrees |
| **"Request URL is missing an 'http://' or 'https://' protocol"** | a scheme-less Base URL ("openrouter.ai/api/v1") surfaced as a network error on the first message, with a hint about VPNs and firewalls | the value was passed straight to httpx as the request URL. `LLMClient` only substitutes the dialect's default when the base URL is *empty* | `normalize_base_url()` rejects a scheme-less value at bind time with an actionable message and strips a trailing slash |
| **A failed turn left an empty assistant bubble** | with a rejected key the error banner rendered correctly *and* an empty bubble sat under it, so the transcript read as a broken UI | `turn.started` creates the assistant bubble eagerly so the first delta has a home, and `turn.finished` dropped a placeholder the core never wrote to. `turn.failed` and `error` did not -- and those are the paths a new user hits first, because a wrong key is the first thing a new user has | one `dropEmptyAssistantMessages` helper called by all three terminal events. Found by driving the **packaged** app with a credit-exhausted key, not by a test |

The pattern worth keeping: **the sidecar's stderr is the only place core-side
failures appear**, because stdout is protocol-only. The React UI now renders it
in a log strip, and the error banner shows Tauri's exact message. Without that,
every one of the above presented as an unexplained "disconnected".

### 1.3 Phase 1: the disabled rail icons

The Sandbox and Settings rail buttons were grey placeholders. Both now open one
`SettingsPanel`, because the project folder and the model answer the same
question - "what is this window working on" - and two modals would mean two
places reaching the same core methods. Search stays disabled: it needs a real
core method, and a UI that filters its own transcript is the kind of
presentation-only control this project keeps having to unpick later.

What was added:

| Piece | Why it exists |
|---|---|
| `app/src/dialog.ts` | `pickFolder()` over `@tauri-apps/plugin-dialog`, lazily imported for the same reason `backend.ts` does it - a top-level import would make the protocol tests require Tauri |
| `app/src/SettingsPanel.tsx` | folder picker, sandbox start/stop, trust toggle, provider + model selects, API key field (Phase 2) |
| `app/src/SearchPanel.tsx` | project-wide regex search (Phase 2) |
| `src/tonyagent/core/modes.py` | the four modes: system prompt + tool allow-list (Phase 3) |
| `app/src/events.test.ts` | the reducer's suite (Phase 3) - found the mutation bug on its first run |
| `tests/unit/test_modes_and_diffs.py` | modes + diff stats (Phase 3) |
| `providers.list` (core) | so the panel asks the registry instead of carrying a hardcoded provider list that would drift the moment a provider is added or renamed |
| `project` in `state`/`sandbox.start` | a reloaded window otherwise cannot tell what folder the core is attached to |

Two decisions worth keeping:

- **Trust state lives in `App`, not the panel.** The core keeps the trusted set
  in memory with no getter, so the UI cannot ask. It remembers what it asked
  for instead, and defaults to *untrusted* - the safe direction to be wrong in,
  because a wrongly-trusted folder skips the confirmation prompt.
- **Provider/model are a draft until Apply.** Two round trips per keystroke
  would be its own bug, and model ids are provider-specific, so changing the
  provider clears the model.

The Files panel's empty state now offers the picker directly. A panel that only
explains itself is the dead end this replaces.

### 1.4 Phase 2: API keys and search

**The key rules, and why they are the way they are.** A key arrives on stdin
and must not leave by any other route. The problem is that both output streams
are *displayed*: stdout frames become the transcript, the error banner and the
event log, and stderr becomes the log strip. So a key that reaches either one
is a key on screen. Four consequences:

- **The reply carries only the provider name.** Never an echo, never a masked
  form - a masked prefix still identifies the key to anyone who has seen it.
- **Errors are re-raised with a fixed message, never `str(exc)`.** The real
  keyring backend quotes the value it refused inside its own exception, so
  returning it would put the rejected secret in the error banner. The fake in
  `test_a_keyring_failure_does_not_echo_the_key` reproduces exactly that.
- **There is no `key.get`, and there must not be one.** A method that returns a
  secret is a method whose secret can end up in a screenshot. This is pinned by
  `test_there_is_no_method_that_returns_a_key`, which fails the moment someone
  adds one.
- **The frontend field clears on both success and failure.** A field that keeps
  a credential in the DOM after storing it is a field that ends up in a support
  bundle. The client cannot redact what it sends - the core needs the real value
  - so its only job is never to *display* it.

`carriesSecret()` in `backend.ts` exists so the one place that could leak a key
(a debug log of an outgoing frame) is hard to add by accident.

**Search delegates to `GrepTool`, it does not reimplement the scan.** A second
implementation would be a second set of rules about which directories to skip
and how a path is confined to the project, and the two would drift - so the
search a user runs and the search the agent runs would quietly answer different
questions. `test_search_matches_the_same_rules_the_agent_gets` fails if the
protocol ever grows its own scanner. The panel also cannot start before a
folder is chosen, because grep resolves paths against the project root.

### 1.5 Phase 3: real modes and real diff stats

**Modes are enforced, not requested.** A mode sets a system prompt *and* an
allow-list, and only the second one is a permission. Prompt text produces a
model that says "I will not modify that file" and then modifies it. So the
schema is filtered (advisory -- it stops the model wanting the tool) *and* the
orchestrator refuses the call (the guarantee -- it holds even if the model
hallucinates a tool it was never shown). The refusal happens **before**
argument validation and **before** the confirmation prompt: asking the user to
approve something a mode was meant to make impossible is worse than the tool
running.

`test_the_orchestrator_refuses_a_tool_the_mode_forbids` asserts the file does
not exist afterwards, not merely that an error came back -- otherwise the test
would also pass if `write_file` were simply broken.
`test_the_same_call_succeeds_once_the_mode_allows_it` exists to rule out that
false pass.

Two other decisions worth keeping:

- **Switching mode clears the conversation.** A "you cannot write files" system
  prompt that outlives Plan leaves the model obeying a rule the user has
  already switched off.
- **`mode.set` replies with the mode actually in force**, not the one asked
  for. An unknown name resolves to Build, and echoing the request would leave
  the UI showing a mode that is not active.
- **The pills come from `mode.list`.** Same reasoning as `providers.list`: a
  hardcoded list drifts from the allow-lists behind it. There is also a test
  that every registered tool is reachable in *some* mode -- it immediately
  caught `http_request` being in no allow-list, i.e. dead code.

**Diff stats are a real line diff.** `write_file` used to report only a char
count, so the Files tree invented a badge by counting tool invocations and
scraped the path out of an English sentence -- which meant a file the agent
merely *read* appeared in the tree. Now the mutating tools emit a
`file_change` artifact with a `difflib` line diff, and the tree reads that.
`test_rewriting_a_file_reports_a_real_line_diff` is the case a length
comparison gets wrong: same character count, one line changed, a length diff
reports nothing at all.

A `0/0` change is passed through and the sidebar hides it. Showing "+0 -0"
would claim a file was edited when a no-op write touched nothing.

### 1.6 Phase 4: assistant text is Markdown

Assistant messages were plain text with `white-space: pre-wrap`. They are now
parsed and rendered as Markdown. Two decisions carried it:

- **A dependency-free parser, not a library.** The `NEXT_SESSION` note that
  preceded this said the core "already depends on `markdown2` for the Tkinter
  UI". That is not true and was worth checking: `markdown2` is declared in
  `pyproject.toml` but imported nowhere, in either UI. So there was nothing to
  reuse, and the choice was a new dependency or a parser. The parser won: the
  frontend's protocol tests must keep running in plain Node with no build
  toolchain and no network install, and a new package would have broken that on
  the first `npm ci` without a network.

- **Token tree, never an HTML string.** The obvious shortcut -- build an HTML
  string and hand it to `dangerouslySetInnerHTML` -- turns every model
  completion into an XSS surface. Assistant text is untrusted output from a
  remote model. `markdown.ts` is pure and returns a typed tree of blocks and
  inlines; `MarkdownText.tsx` maps that tree to React elements, so React escapes
  every string and the only place a URL reaches the DOM is a sanitised `<a>`.
  `markdown.test.ts` pins the security cases: a `javascript:` link keeps its
  text and loses its href, and a remote image renders as its alt text rather
  than becoming a tracking beacon.

It implements a deliberate subset -- fenced code (with an unterminated fence
running to the end, which is the streaming case), headings, ordered/unordered
lists, blockquotes, rules, and inline code/strong/em/strike/links. A missing
feature degrades to plain text, which is exactly what rendered before. Only
*assistant* text is parsed; a user's message is shown as typed, because someone
who pasted `**not bold**` meant the asterisks.

Two smaller things this surfaced:

- **`markdown.ts` and `Markdown.tsx` differ only in case**, which collides on a
  case-insensitive filesystem. `tsc` refused the whole program with TS1149. The
  component is `MarkdownText.tsx` now. Any future module pair here must not
  differ only in case.
- **The assistant bubble must reset `white-space`.** `.bubble` sets `pre-wrap`
  for user text and tool output; leaving it on for rendered Markdown makes the
  whitespace between block elements significant.

### 1.7 Phase 5: custom model and endpoint, and the first live turn check

A provider's `models` list is a set of *suggestions*, not a closed set. The
settings panel used to render it as a `<select>`, so the only bindable OpenRouter
models were the four the registry happens to list -- and OpenRouter serves
hundreds of namespaced ids (`anthropic/claude-sonnet-4.5`,
`deepseek/deepseek-chat:free`). Self-hosted gateways are worse: their ids are
ones the registry has never heard of.

What changed:

- **The model field is free text.** It became `<input list="model-suggestions">`
  with a `<datalist>` of the provider's known ids -- native combobox behaviour,
  no dependency, and any typed id binds as-is. (The Tkinter `PillComboBox`
  already allowed typing, so only the React panel needed this.)
- **`bind_provider` takes an optional `base_url`,** echoed back in the reply;
  `state` reports it too. The panel grew an optional Base URL row.
- **This is what makes `custom` usable.** That provider raises `ValueError`
  without a `base_url`; the handler now converts that into a `rejected` reply
  with the provider's own message instead of an opaque `internal` error.
- **No new protocol surface beyond one optional field.** `session.bind_provider`
  gained a third argument (defaulting to `""`, so the Tkinter call site is
  untouched) and `ProviderFactory.create_provider` already accepted `base_url`.

**The first live turn check.** Two runs, both worth recording:

1. *Through the real protocol, against OpenRouter.* Spawned the sidecar,
   `ping`, `bind_provider {name: openrouter, model: <a custom id>}`, `send`.
   The custom model id round-tripped exactly, `message.started` streamed, and
   then `turn.failed` carried the provider's own error verbatim (`403 Key limit
   exceeded (total limit)`, and for free slugs `rate_limit`). The core path is
   *sound*; the failure was billing. This is the first time the whole sidecar
   turn path has been driven against a live endpoint.
2. *A complete successful turn, against a local mock.* Stood up a tiny
   OpenAI-compatible SSE server and bound the `custom` provider to it through
   the new `base_url` field (with a dummy in-memory key, so the OS keyring was
   never touched). The full lifecycle ran: `turn.started` -> `message.started`
   -> six `message.delta`s -> `message.completed` -> `turn.finished`, and the
   deltas reassembled into the expected text. That is the new endpoint feature
   working end to end, and the turn machinery proven to *complete*.

Still missing: one successful reply from a **hosted** model. That needs the
user to raise or replace the OpenRouter key; it is the only remaining gap in
this phase (see section 5 item 10).

### 1.8 Checking the packaged app, and what that found

The release build was verified by running it, not by trusting the suite. MSI
48.36 MiB / NSIS 47.43 MiB, then `tonyagent-app.exe` launched with
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9333"` and read
over CDP. Confirmed *in the packaged build* rather than in `vite dev`:

- sidecar spawns, `state` reports `openrouter / openrouter/auto` -- the Phase 5
  startup bind and the empty-model fix, working from the embedded binary;
- the Settings modal carries the free-text Model input with its `datalist` and
  the Base URL row; `Remove` is present, so a real key is in the keyring;
- `document.fonts` reports Inter and JetBrains Mono as **loaded**, so the
  `font-src 'self'` CSP entry still works after packaging -- worth re-checking
  every time, because a missing font-src fails silently as a system-font
  fallback rather than as an error;
- `markdown.ts` and the `.md-*` rules are present in the shipped
  `dist/assets` bundle and CSS;
- a real turn: the request reached OpenRouter and was rejected with
  `Key limit exceeded (total limit)`, and the error surfaced with a message
  about the user's own key. That is the send path verified live; the only
  thing still unproven live is a **successful** assistant reply.

That last point is why the empty-bubble bug above is worth recording: it was
invisible to 54 TypeScript tests and to a real turn, and appeared only because
the app was actually run against a failing key.


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
| `state` | — | `{provider, model, base_url, busy, messages, project}` |
| `send` | `{text}` | `{turn_id}` |
| `cancel` | — | `{cancelled}` |
| `clear` | — | `{cleared}` |
| `bind_provider` | `{name, model?, base_url?}` | `{provider, model, base_url}` |
| `providers.list` | — | `{providers: [{name, models, has_credentials, ...}]}` |
| `key.save` | `{provider, api_key}` | `{provider, saved}` |
| `key.delete` | `{provider}` | `{provider, deleted}` |
| `search` | `{pattern, path?, include?, case_sensitive?, max_results?, context_lines?}` | `{matches, output}` |
| `mode.list` | — | `{mode, modes: [{name, label, description, writes}]}` |
| `mode.set` | `{mode}` | `{mode, label, description, writes}` |
| `sandbox.start` | `{path?}` | `{running, project}` |
| `sandbox.stop` | — | `{running}` |
| `sandbox.stats` | — | stats dict |
| `confirm.respond` | `{id, confirmed}` | `{id, confirmed}` |
| `trust.set` | `{project, trusted}` | `{project, trusted}` |

### Artifacts inside a `tool.completed` result

`result.artifacts` is a list. One type is load-bearing for the UI:

```json
{"type": "file_change", "data": {"path": "src/app.py", "added": 12, "removed": 3}}
```

Emitted by `write_file`, `edit_file` and `delete_file`, and by nothing else.
`read_file` deliberately emits nothing, so a file the agent merely looked at
gains no row in the Files tree. `added`/`removed` are a real `difflib` line
diff, and a `0/0` pair means the write was a no-op -- the sidebar hides that
rather than showing a badge claiming an edit that did not happen.

**A failed tool emits no artifact.** Nothing changed on disk, and a badge the
filesystem contradicts is worse than no badge.

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
    IconRail.tsx            left rail (new chat, clear, stop, placeholders)
    TopBar.tsx              toggle, conversation tab, new chat
    styles.css              dark-only tokens sampled from the Freebuff app
    backend.ts              the protocol client (13 tests)
  src-tauri/
    tauri.conf.json         productName, window, CSP, externalBin, icons
    capabilities/default.json
    Cargo.toml, build.rs, src/main.rs, src/lib.rs
    icons/                  generated from icons/icon.svg
    binaries/               PyInstaller sidecar output (gitignored)
```

### Visual design

Every value is sampled from a full-resolution screenshot of the Freebuff
desktop app (2879x1714, ~2x DPI), not eyeballed. **A partial capture is not
enough** — the first pass here was built from one and got the accent colour
wrong, because the chromatic element was outside the captured region.

```
--bg       #0a0a0a   rail and transcript, the dominant colour
--chrome   #0f0f0f   top bar — a hair lighter, so the window is not one flat field
--surface  #171717   composer field, files sidebar
--input    #1c1c1c   filter fields, inset wells
--raised   #212121   tab pill, user bubbles
--hover    #292929   the active rail well
--fg       #ebebeb   body text
--fg-dim   #9e9e9e   secondary (file tree)
--fg-mute  #7a7a7a   metadata
--accent   #bacda9   the ONE chromatic element
```

**The accent is a desaturated sage, not a brand colour.** Do not "tidy" it
towards saturation — the reference is almost monochrome and the single quiet
hue is deliberate. A purple was tried first and was wrong.

Layout: `70px | 1fr | 425px` grid, 42px top bar, transcript inset to 860px.

**Dark only.** The reference is dark-only and a light theme would need a second
full palette to be worth shipping. The Tkinter UI keeps its own light/dark
system, so the two clients no longer match on this point — a deliberate trade,
recorded here rather than left to be discovered.

The composer is **two rows in one field**: textarea on top, controls beneath
(Build/Plan/Mission/Skills, model chip, Continue). Putting the buttons beside
the input would steal line length. Mode pills are presentation-only — there is
no protocol method to set a mode, and inventing one client-side would let the
UI claim a capability the core lacks.

The Files sidebar is populated from tool events the core reported, not by
walking the filesystem from the UI. The core owns the sandbox and the folder;
a second source of truth about that state is how the Tkinter UI drifted.

**The Files panel is closed by default; the icon rail is open.** A 425px panel
was eating the transcript on a normal window before the agent had touched a
single file, so `filesOpen` starts `false` and the collapsed panel leaves a
small folder button at the top-right to reopen it. The rail stays open: it is
the app's only navigation, and the reference design keeps it visible.
`railOpen` and `filesOpen` are independent, and each has its own button (the
top-bar "Toggle sidebar" and the panel's own hide/show).

### CSS traps hit here

- **Rule order beats intent at equal specificity.** `.btn-accent` and `.btn`
  are both single-class selectors, so the later rule wins. `.btn-accent` was
  declared first and the grey `.btn` background silently overrode it — the
  button rendered grey with no error anywhere. Variants must come after the
  base rule.
- **The rail must be pinned with `grid-column: 1` and `.main` with
  `grid-column: 2`.** Otherwise removing the rail makes `.main` the first grid
  item, so it auto-places into the collapsed zero-width track and the
  transcript vanishes entirely.
- Collapsing the rail needs `grid-template-columns: 0 ...` too, or the 70px
  track stays reserved.

### Typography

`Inter` (body) and `JetBrains Mono` (paths, diff stats, log strip), self-hosted
as woff2 in `app/src/fonts/`. Do not go back to `system-ui`: the whole point of
a desktop app is that the layout someone tuned is the layout a user gets, and
the system stack rendered differently per machine. The fonts ship inside the
binary, so there is no offline first-launch gap and no CDN to wait on.

Details that are deliberate, not incidental:

- **latin + latin-ext only.** Google's per-script split is kept, so a latin-ext
  character pulls in the second file only when one actually appears. Verified
  live: adding `ężł` flipped the second Inter face to `loaded`.
- **One variable file per family per script.** Weights 400/500/600 are all used,
  and a variable font covers the range in one download.
- **`font-display: block`, not `swap`.** A flash of light Segoe before Inter
  arrives is worse on a dark UI than a brief blank, and the fonts are local, so
  the block period is a disk read rather than a network wait.
- **`font-src 'self'` had to be added to the CSP.** `default-src 'self'` does
  not cover fonts, so without it every face silently fails to load and the app
  quietly falls back to the system font - which looks like "the change did
  nothing" rather than like an error.
- **`tabular-nums` on the status bar and rail badge.** Both show values that
  change while you watch, and proportional figures make the whole line twitch.
- The system fonts stay in the stack as a last resort, so a woff2 that fails to
  decode degrades to readable text instead of nothing.

Cost: 176 KB of fonts, and the installer grew 0.16 MiB.

### Do not test `key.save` against a provider that has a real key

`key.save` writes to the **real OS keyring**. A canary value typed into a live
provider slot overwrites the user's actual credential, and the damage is silent
until a real request 401s. This happened here: a canary written to `groq` broke
`test_chat_path_streams_end_to_end[groq]` with "The groq key does not start with
'gsk_'", which is the only reason it was caught.

The pytest suite is safe - `test_the_key_never_appears_on_stdout` and friends
monkeypatch a fake `keyring`, so no OS store is touched. Anything run by hand
against `python -m tonyagent.headless.server` is **not**. Use a provider with no
stored key (`ollama`, `custom`) and delete it afterwards, or just read the
code. The UI check was done against `ollama` with `dummy-not-a-real-key`.

### Launchers

Two, and they reach different clients:

- `Start TONYAgent.bat` — Tkinter UI (`python -m tonyagent`). Unchanged.
- `Start TONYAgent (Tauri).bat` — Tauri + React UI. Checks python, node, npm
  and cargo; adds `%USERPROFILE%\.cargoin` to PATH if cargo is missing
  (rustup registers it in the USER path, which a process launched from Explorer
  does not always inherit); builds the sidecar if it is absent; then
  `npm run tauri:dev`.

The sidecar check globs `app\src-tauriinaries	onyagent-core-*.exe` because
the filename carries a target triple that differs per machine. It only tests
existence — if you change the Python core, delete the exe and re-run.

**Note the parentheses in the filename.** They are cmd metacharacters, so
`call "Start TONYAgent (Tauri).bat"` from another batch file fails with
`is not recognized as an internal or external command`. Double-clicking from
Explorer is unaffected. Invoke it from a script with `Start-Process` instead.

### Inspecting the UI

`scripts/probe_webview.py` evaluates JS in the running webview and can
screenshot it:

```bash
# launch with a debug port
WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9333" ./tonyagent-app.exe
python scripts/probe_webview.py -e "document.title"
python scripts/probe_webview.py --screenshot shot.png
```

Prefer this over a Win32 screenshot. `PrintWindow` on a WebView2 window only
paints regions the app recently invalidated, so it returns large black bands
that look exactly like a broken layout -- which sent me chasing a non-existent
CSS bug. `Page.captureScreenshot` asks the compositor for the real frame.

Note that `vite build` alone is not enough to see a change in the packaged app:
`tauri build` embeds `dist/` into the binary.

The Rust side is deliberately tiny: it opens a window and registers the shell
and dialog plugins. All protocol logic is in `src/backend.ts`, already covered
by tests.

**The native folder dialog cannot be driven over CDP.** `pickFolder()` opens a
real OS dialog, which blocks the webview and is invisible to
`probe_webview.py` - a call to it just times out. To test the paths behind it,
either drive the protocol directly (`sandbox.start` with a path) or render the
panel against a stub. Do not conclude the picker is broken from a probe
timeout.

**The preview panel will not composite an image-only page.** Serving a bare
`<img>` of a screenshot through `register_preview` rendered a blank frame
several times this session; inlining it as a data URI in a tiny HTML file
worked once and then stopped. When it misbehaves, verify the UI through
computed styles via `probe_webview.py` instead - that is dependable and was
enough to confirm every token.

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

**REBUILD THE SIDECAR AFTER EVERY PYTHON CHANGE.** This is the single most
expensive trap here, and it cost two wrong diagnoses this session. The
`Start TONYAgent (Tauri).bat` launcher only checks that the sidecar *exists*,
not that it is current, so:

- You edit `server.py`, add a protocol method, restart `tauri dev`, and the
  method comes back `unknown_method` - or, worse, keeps its old behaviour.
- Meanwhile `python -m tonyagent.headless.server` (which runs from **source**)
  works perfectly, so a CLI test passes and proves nothing about the app.

If a protocol change "isn't taking effect", rebuild before investigating
anything else. Same applies to the Rust side: `tauri dev` does rebuild that
itself, so the Python side is the asymmetric one.

```bash
cd app && python ../scripts/build_sidecar.py    # ~40s
```

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
9. **There is no working groq key any more.** Phase 2 overwrote the real one
   with a canary while testing `key.save` by hand, and it was deleted rather
   than restored. So `test_chat_path_streams_end_to_end[groq]` fails with
   "The groq key does not start with 'gsk_'". **Ask the user to re-enter it in
   Settings, or ignore that one test.** An environment gap, not a regression -
   do not "fix" it in code.
10. **A real end-to-end turn now has its first live exercise (Phase 5), but no
   successful hosted reply yet.** The sidecar turn path was driven against
   OpenRouter with a custom model id and reached the provider, which answered
   `403 Key limit exceeded (total limit)` (free slugs: `rate_limit`) -- a
   provider error surfaced correctly, not a code failure. A *successful*
   complete turn was then proven against a local mock OpenAI-compatible
   endpoint bound through the new `base_url` field. What remains is a
   successful reply from a hosted model: raise or replace the OpenRouter key
   (item 6) and re-run. The full Python suite is green (244 passed, including
   the groq chat test, which stubs its transport).

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

### 7.1b Phase 5: custom model and endpoint

`bind_provider` now takes `{name, model?, base_url?}` and echoes `base_url`
back; `state` reports it too, so a reloaded window reopens the panel
pre-filled. The settings panel's model field became a free-text input with a
`<datalist>` of the provider's known ids instead of a `<select>`, and an
optional Base URL row sits under it. This is what makes the `custom` provider
usable: it raises `ValueError` without a `base_url`, and the handler now turns
that into a clean `rejected` reply instead of an opaque internal error. Three
new tests in `test_headless_core.py` cover the arbitrary model id, the
`base_url` round trip through `state`, and that rejection.

### 7.2 Next, in the Tauri UI

**Done across Phases 1-4** (see 1.3-1.6): folder picker, settings panel,
sandbox start/stop, API keys, search, the four composer modes, and Markdown
rendering. All five rail buttons are live and no control is
presentation-only any more.

1. ~~**Project folder picker.**~~ Done (Phase 1) - `@tauri-apps/plugin-dialog`,
   wired to `sandbox.start({path})`, reachable from the rail and the Files panel.
2. ~~**Settings panel.**~~ Done (Phase 1) - `SettingsPanel.tsx`, driven by
   `bind_provider`, `sandbox.start`/`.stop` and `trust.set`.
3. ~~**API key entry.**~~ Done (Phase 2) - `key.save` / `key.delete` plus a
   password field. See the security note in 1.4 before touching it.
4. ~~**Sandbox controls.**~~ Done (Phase 1) - start/stop in the settings panel.
5. ~~**Search.**~~ Done (Phase 2) - `SearchPanel.tsx` over the core `search`.
6. ~~**`events.ts` has no tests.**~~ Done (Phase 3) - 15 tests, which found the
   reducer mutating its input. 35 frontend tests total.
7. ~~**Composer modes.**~~ Done (Phase 3) - see 1.5. Enforced in the
   orchestrator, not just the prompt.
8. ~~**Markdown rendering.**~~ Done (Phase 4) - see 1.6. Parser + renderer +
   16 tests, no new dependency.

**Still open, in the order I would do them:**

1. **Run one real end-to-end turn.** *Partially done (Phase 5).* The turn
   machinery now has its first live exercise: spawn the real sidecar, `ping`,
   `bind_provider` with a custom OpenRouter model id, `send`, and read the
   streamed events. It reached `message.started` and then `turn.failed` with
   the provider's own error surfaced verbatim -- the core path is sound, the
   failure was billing (`403 Key limit exceeded (total limit)`), not code. A
   complete *successful* reply was then proven separately against a local mock
   OpenAI-compatible SSE endpoint bound through the new `base_url` field: the
   full lifecycle ran (`turn.started` -> `message.started` -> deltas ->
   `message.completed` -> `turn.finished`). **What is still missing is a
   successful reply from a real hosted model**, which needs the user to raise
   or replace the OpenRouter key. See section 5 item 10. (Markdown rendering,
   section 1.6, is verified down to the token tree, the type checker and a
   served render; it still wants one look at a live transcript.)
2. **The composer's model chip and Attach button are still disabled**, and
   the `/` skills and `@` threads hints in the placeholder are not
   implemented. Either wire them or remove the hints - a placeholder that
   advertises syntax nothing handles is the same class of problem as the
   presentation-only mode pills were.
3. **The Files tree has no grouping.** Paths are a flat list; a real tree
   wants directory rows. The `TreeEntry.kind` field already carries `"dir"`
   and the collapse logic is written, so this is a change to how entries are
   built in `App.tsx`, not new infrastructure.

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

Re-confirmed again during Phase 3: it also failed one full run there while
passing in isolation and on the immediate re-run. A *different* test in the
same file (`test_key_entry_is_empty_not_prefilled`) failed once in the same
way. So the file is flaky as a file, not just that one test - re-run before
diagnosing anything.

Re-confirmed during Phase 5: `check_all.py --fast` reported FAIL from a third
distinct test (`test_ghost_buttons_are_transparent_not_white`), which passed on
its own immediately afterwards, while a plain `pytest tests -q` on the same
tree was green (244 passed). Same signature: the Tk-root churn in one process,
not a regression. Root cause on this machine is that Tcl is not installed
properly (`invalid command name "tcl_findLibrary"`), so any test that builds a
real window can lose the race.

**`test_chat_path_streams_end_to_end[groq]` fails until the user re-enters
their groq key.** Phase 2 destroyed it; see section 5 item 9. The other
provider cases in that file pass. (In the Phase 5 runs the whole file passed,
which is expected: that test stubs its transport rather than using a stored
key, so its result does not depend on the keyring.)

**`RuntimeWarning: coroutine ... was never awaited`** in
`tests/unit/test_tool_sandbox_routing.py:875` — two occurrences, pre-existing.

---

## 9. Decisions made, and why

- **Keep the Python core, replace only the UI.** A survey of comparable
  projects found the closest precedent is Goose (Block): a native core plus a
  TypeScript UI. A full core rewrite would discard 238 tests and 22 tools.
- **JSONL over stdio, not a local HTTP server.** Tauri owns the sidecar
  lifecycle, so it starts and dies with the app. No port to collide with, no
  auth, no CORS, and a dead pipe is an unambiguous failure signal.
- **Events plus request/reply, not one or the other.** The UI must both ask
  questions and receive unsolicited progress.
- **Exact per-provider `key_length`.** A prefix check plus a 20-char floor let
  a truncated key through and produced a baffling server-side error.
- **Injectable transport in the TS client.** Keeps the protocol verifiable
  without the build toolchain, and keeps Tauri out of the business logic.
- **The frontend asks the core what exists; it never hardcodes a list.**
  `providers.list` and `mode.list` exist so provider names and mode labels
  cannot drift from the registries behind them. Both were worth it: the
  mode test immediately caught `http_request` being in no allow-list.
- **Search delegates to the agent's grep rather than scanning again.** Two
  scanners means two sets of skip rules and path confinement, and the search
  a user runs slowly stops matching the search the agent runs.
- **A mode is a permission, not a prompt.** Enforced in the orchestrator
  before argument validation and before the confirmation dialog, because a
  prompt produces a model that claims compliance and then writes the file.
- **No protocol method returns a secret.** There is no `key.get`, and a test
  fails if one is added. A method that returns a secret is a method whose
  secret can reach a screenshot.
- **Self-hosted fonts.** The system stack renders differently per machine,
  which defeats the point of tuning a desktop layout.



