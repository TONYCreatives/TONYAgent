# TONYAgent — GUI review, 26 October 2026

What the window is, what it looks like today, what it can do, and where the
redesign has actually got to.

## How this was produced

- **Rendered, not remembered.** `app/dist` (built 25 Oct 19:15) was served on
  loopback and captured in headless Chrome over CDP. The page is built to run
  hostless — `bridge.ts` resolves to `null` by design — so the shell, the
  launchpad, the status bar and the run panel in the captures are the real
  components with real CSS. Captures: `.shots/live/01..09`.
- **Read** for the states that need a live core to reach: `README.md`,
  `design/AGENT_WORKSPACE_REFINE.md`, `PHASE_0_1` / `PHASE_2` / `PHASE_3`
  handoffs, and the component sources (`App.tsx`, `ContextPanel.tsx`,
  `ViewSwitch.tsx`, `Composer.tsx`, `SettingsPanel.tsx`, `CodeViewer.tsx`,
  `modes.py`, `skills.py`, `attachments.py`).
- **Checked:** `tsc --noEmit` is clean on the current tree.
- **Not rendered:** Settings, Code with a project open, and a transcript with
  messages. All three are gated on a connected core, so what follows about them
  is from source, and is labelled as such.

## 1. What it is

A local-first desktop coding agent: a Python core that owns conversations,
tools and permissions, and a React interface in a native window (`pywebview`
hosting WebView2 on Windows). The window is not the app — it owns the core as a
child process and talks to it in newline-delimited JSON over stdio. Three
processes, one product.

What separates it from a chat client with tools attached: the agent's work is
supposed to be visible in the same frame as the conversation. That is what the
current redesign is for, and three of its phases are in the tree.

## 2. The frame, as it renders today

Measured from the live page, not from the design notes:

| Width | `grid-template-columns` | Nav | Run pane |
|---:|---|---|---|
| 1400 | `288px 824px 288px` | docked column | docked column |
| 1100 | `64px 988px 48px` | 64px rail + overlay | 48px strip, panel overlays |
| 760 | `760px` | floating rail | floating strip |

Three rows:

1. **Top bar, 52px** — app mark in the first 64px, conversation tab strip with
   `+`, a spacer, then on the right: the **track** toggle (`Chat | Build`), the
   **status pill** (`Idle` / `Working` / `Waiting` / `Error`), the **model
   chip** (`No model` when unbound), and the caption buttons.
2. **Body** — nav / centre / context.
3. **Status bar, 26px, full width** — `Disconnected · No provider · Sandbox:
   Stopped` on the left, `Logs` on the right. Green or red dot leads it.

### Nav

At 1400 it is a real 288px column: header row with the sidebar toggle and the
`Agent | Code | Trajectory` segmented switch, then `Chats | Files` tabs, then
rows for `New chat` and `Skills`, then the conversation list. Its foot is the
old icon rail folded in: search, usage, pet, settings.

Below 1101 it collapses to the 64px icon rail, and the view switch becomes one
button plus a menu (`View: Agent`), because three view buttons do not fit 64px
alongside the rest.

### Centre

Empty state is the **launchpad**: the mark, `TONYAgent`, one line of
orientation, the project row (`No project folder` + `Choose folder…`), and two
keyboard hints (`/` for skills, `@` for threads or files). With a core and no
setup complete it also shows a "Before the first turn" card listing only what
is actually missing, four suggestions that **prefill and never send**, and the
last three chats.

The **composer** is one rounded box at the bottom of a 760px reading column
that the transcript shares: textarea, attachment strip, and a control row with
the attach button, the **mode chip**, and the **tool-budget** control (the gear
— it sets how many tool calls one turn may make). Below it: `Enter to send ·
Shift+Enter for a new line`. `Enter` sends; `Shift+Enter` breaks the line.

### Context (the right pane)

Closed: a 48px strip with a status orb and a vertical `RUN`. Open at ≥1400: a
docked 288px column. Open below 1400: the same 288px panel floats over the
centre with a scrim that dims only the centre — visible in
`.shots/live/07-run-panel-1100.png`, and the centre keeps its full width.

Its contents are the Phase 3 work and they are the best thing in the window
right now:

- **Run card** (sticky) — state, live clock, one live sentence, context meter,
  `Stop` only while working, `Open Trajectory` always. The meter has three
  honest states: `unknown`, `62.4k used`, `62.4k / 124k · 50%`. It never draws
  a bar from a denominator it was not given; today, with no turn, it says
  `CONTEXT unknown`.
- **Plan** — goal, `2/7` progress, five rows, read-only, `+N more in the
  transcript`. Empty today: `No plan yet — ask for one.`
- **Activity** — chronological, newest six, status / tool / summary /
  duration, `View all N`.
- **Files** — five rows with `+N −N` summed per path, press to open in Code.

It is an accordion: one section open at a time, Activity when a turn is
running, Plan when idle.

## 3. Workspaces

| Workspace | What it is | Reachable when |
|---|---|---|
| **Agent** | nav + transcript + run pane | always |
| **Code** | project explorer, editor, assistant panel — a whole-window shell, not a pane | a project folder is open |
| **Trajectory** | every event of a turn: calls, arguments, outputs, diffs | always |
| **Settings** | full-window page with its own 196px section nav | a core is connected |
| **Usage** | requests / tokens / reasoning / spend over a window, per-day chart, plus a button that opens the provider's own account pages in a browser the app owns | a core is connected |

Settings has four sections: **Behavior** (permission ladder, thinking effort,
command allow/deny lists), **Project** (folder, trust, sandbox),
**Keys** (stored keys, add a key, base URL), **App** (desktop pet, motion,
version/update, diagnostics, logs).

Code mode is the odd one out: it still replaces the window rather than joining
the shell (268px explorer + editor + 400px assistant). Phase 5 is the fix and
has not shipped.

## 4. The two mode axes

They are now deliberately different shapes, which was one of the goals:

- **Workspace** — where you are: nav switch, top of the left pane.
- **Agent mode** — how the agent behaves: one chip in the composer.

| Mode | Writes | Tools | Intent |
|---|---|---|---|
| Chat | no | none — no project, shell or browser | plain conversation |
| Build (default) | yes | full set incl. shell and screen | do the work |
| Plan | **refused, not discouraged** | read-only | investigate and propose |
| Mission | yes | mutating set, no stopping to ask | one long objective to completion |
| Skills | no | read-only + `list_skills` / `run_skill` | explain, and load `/name` skills |

The allow-list is enforced in the orchestrator, not just in the schema — the
file's own comment is right that prompt text is a request and the allow-list is
a fact.

## 5. What you can actually do with it today

1. **Make a change in a real project.** Point it at a folder, pick a model,
   stay in Build, describe the change. It reads, edits, runs commands in the
   sandbox, and reports. 41 tools across file, search, shell/jobs, network,
   browser (10), and planning/utility.
2. **Read the code first.** Code workspace: tree with a filter, editor with
   three palettes (Dark+, Light+, Monokai), images and Markdown and CSV
   rendered by type, read-only by default with a per-file edit toggle, and
   locked while a turn runs so the agent and you cannot write the same file at
   once. `Ctrl+S` saves atomically and tells the agent which file and lines
   changed.
3. **Propose without touching.** Plan mode, then read the plan card in the run
   pane and approve.
4. **Hand it something long.** Mission mode: an objective rather than a
   question, and it is told not to stop and ask.
5. **Watch what it did.** Trajectory for the full event log; Activity for the
   last six steps with durations; Files for the diffstat per path.
6. **Understand the codebase without changing it.** Skills mode, or `/name` to
   load a skill from `<project>/.tonyagent/skills/` or the user-level skills
   folder.
7. **Delegate.** Subagent tools: spawn, fork, list, message, interrupt.
8. **Keep an eye on it from another window.** The desktop pet is a small
   always-on-top circle that says what the turn is doing, never takes focus,
   blinks, types while the agent types, hops when it needs you, sleeps when
   idle, and returns you to the app when clicked.
9. **See the spend.** Usage dashboard per window, and a real account page for
   the provider rather than only this app's own count.

Limits worth knowing: local sandbox mode refuses `execute_command` and
`execute_js` on purpose; Windows Sandbox is a stub, not an isolation backend;
AirLLM is Chat-only; the run pane's token meter needs a provider that reports
usage.

## 6. Where the redesign stands

`AGENT_WORKSPACE_REFINE.md` is an eight-phase plan for Direction B ("Mission
Control"). Four are in the tree:

- **Phase 0** — tokens, breakpoint ladder (1400/1100/900/720/560/420),
  `plan.get` typed, turn clock, `activity.ts` derivation.
- **Phase 1** — three-row grid, status strip spans the shell, nav dock, context
  dock, one-overlay controller.
- **Phase 2** — view switch into the nav, nav content, status pill, single mode
  chip, launchpad, Trajectory gets the dock.
- **Phase 3** — the run pane: run card, plan, activity, files.

Still missing, and visible as missing:

- **Phase 4** — transcript run spine, tool-row rewrite, inline approvals. The
  transcript is still flat cards and approvals are still a modal, so the
  busiest part of the window is the part that has changed least.
- **Phase 5** — Code mode unification: it keeps its own shell.
- **Phase 6** — the one "live" signal hue, dock material, display type, motion.
  Today the palette is strictly achromatic with white as the only accent, which
  is calm but gives the working state no colour of its own.
- **Phase 7** — docs and screenshots.

The plan itself says Phase 2 is a natural stopping point. Phases 0–3 are a
coherent place too: the shell and the run pane no longer read as a chat client,
but the transcript still does.

## 7. Assessment

**Strong**

- The design system is real, not decorative: two ladders, one accent,
  stadiums for controls, boxes for containers, one 760px measure shared by
  composer and transcript, and a test suite (1076 frontend tests at Phase 3,
  1685 Python) that holds the geometry.
- Honest empty states everywhere — `unknown` instead of a zero, no bar without
  a denominator, no plan rows that scroll nowhere, no invented durations in a
  restored conversation.
- The run pane answers "is it still working, on what, at what cost" without
  opening anything.
- Accessibility is treated as a design constraint: one live region per pane,
  `aria-pressed` on toggles, written-out labels where the visual is a glyph.
- The pet is a genuine differentiator and is engineered properly (window
  region plus shadow removal, no focus theft).

**Weak**

1. **Settings is gated on the core being connected.** The one page that
   explains a missing key, a dead sandbox or a broken provider is unreachable
   in exactly the state where you need it. This is the first thing I would
   change; it is a one-line gate.
2. **The README's shortcut table is fiction.** It documents `Ctrl+N`,
   `Ctrl+O`, `Ctrl+,`, `Ctrl+Shift+P` and `Ctrl+Enter`. The frontend
   implements none of them except `Ctrl+S` in the editor; there is no command
   palette. Escape (close sidebar, leave settings, dismiss menus) and Enter /
   Shift+Enter are the real keyboard surface.
3. **The transcript is the laggard.** The run pane reports on the work; the
   work itself is still a stack of flat tool cards with no spine, no duration
   drama, no inline approval. Phase 4 is the highest-value remaining work.
4. **Two shells to learn.** Code mode's explorer and assistant sit in different
   places and widths from the Agent pane's nav and run pane. It is not broken,
   it is duplicated.
5. **The status bar is a footnote** — 11px at the bottom carrying the state the
   whole window is about, though the status pill now duplicates it in the top
   bar.
6. **Housekeeping is drifting.** `design-preview/` still holds 4 October
   captures of a blue-accent design that no longer exists, `README.md` still
   shows that design, `.shots/` holds ~80 files and 21 MB of process, and the
   repo root carries a dozen `.tmp-*.json` files. Anyone reviewing the window
   from the docs would see the wrong one.

**Next, in order:** ungate Settings; Phase 4; Phase 5; then Phase 7 (regenerate
screenshots, fix the shortcut table, prune `.shots` and `.tmp-*`) before
Phase 6's polish — polish is the cheapest to redo and the most expensive to
redo twice.
