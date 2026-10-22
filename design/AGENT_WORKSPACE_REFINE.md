# TONYAgent — Agent Workspace Refine

**Status:** proposal for review. No product code has been changed for this plan.
**Date:** 2026-10-22
**Scope:** the desktop window (`app/` + `src/tonyagent/window/`), not the core protocol.
**Goal:** make the window read as a modern *agent workspace* rather than a chat
client with agent features — without throwing away the design system that already
works.

---

## 0. How to read this

This is a plan, not a mood board. Every proposal is tied to something that exists
in the current window, says what moves, says what it costs, and says which tests
have to change. The three directions in §3 are the decision; §4 onward is the
detailed spec for the recommended one.

The one thing I am **not** proposing is a rewrite. The current CSS is unusually
disciplined: two ladders, one accent, stadiums for controls, boxes for
containers, a 760px reading column shared by construction, and a test suite that
holds all of it. That is an asset. The refine should use the system harder, not
replace it.

---

## 1. What exists today

### 1.1 Shell

```
row 1  ┌──────────────────────────────────────────────────────────────┐
       │ topbar: mark · tabs · + · model chip · ─ □ ×                 │ 52px
row 2  ├──────┬───────────────────────────────────────────────────────┤
       │ rail │ main                                                  │
       │ 64px │ transcript + composer + statusbar                     │
       │      │                                                       │
       └──────┴───────────────────────────────────────────────────────┘
```

- `--rail-w: 64px`, `--list-w: 288px`, `--measure: 760px`, `--topbar-h: 52px`,
  `--statusbar-h: 26px`.
- The conversation list is an **overlay** over the transcript, not a column.
- Code mode replaces the shell: `--code-side-w: 268px` explorer + editor +
  `--code-helper-w: 400px` assistant.
- Settings is a full-window page; Usage replaces the main column; Trajectory is
  its own view.
- The status bar lives *inside* `.main`, so it stops at the editor's edge in Code
  mode (a deliberate existing decision, but a shell-level strip would be more
  honest).

### 1.2 Visual language

- Achromatic depth ladder: `#1a1a1a` → `#202020` → `#262626` → `#2b2b2b` →
  `#333333` → `#3d3d3d`; text ladder `#ececec` / `#a8a8a8` / `#8a8a8a`.
- White accent (`--accent: #fff`), status chroma only: green success, red
  danger, amber warning.
- Glass: `--glass-chrome`, `--glass-panel`, `--glass-field`, 22px blur, grain
  sheen, two low-alpha field glows.
- Type: Inter 10/11/12/13/14/16/20px; JetBrains Mono for literal code only.
- Shape: `6/12/16/24/999` radius; controls are stadiums, containers are boxes,
  rows tile a column.
- Motion: 110/160/240ms, `rise-in`, `pop-in`, `slide-in-left`, full
  `prefers-reduced-motion` cancellation enforced by `audit_reduced_motion.py`.

### 1.3 What is already strong

- The contrast maths is real and tested, not decorative.
- The composer and transcript share one column by construction.
- Tool calls already carry status, summary, path, added/removed, budget, and
  nested subagent work — the data a timeline needs exists.
- `usage.summary`, `plan.get`, `sandbox.status`, `confirmation.*` and
  `user.asked` already exist on the wire.
- The desktop pet is a genuine differentiator; it should become the agent's
  presence, not a separate toy.

### 1.4 What makes it still read as a chat client

1. **The agent's work is buried.** Plan, current tool, files touched, approvals
   and token spend live in transient cards or in Settings. There is no persistent
   surface that answers "what is the agent doing right now?".
2. **The sidebar is an overlay.** On a desktop-sized window that is a phone
   pattern: conversations disappear when you stop looking at them, and the
   transcript never gains a stable left edge.
3. **Horizontal space is wasted.** At 1600–2000px the window is one 760px column
   with empty air on both sides. The app has the width for a workspace, not just
   a reading column.
4. **Two mode systems compete.** Agent/Code/Trajectory/Settings in the top bar and
   Chat/Build/Plan/Mission/Skills in the composer are both drawn as equal pill
   groups, but they answer different questions.
5. **The top bar is a browser.** Tabs are useful, but the bar says nothing about
   whether the agent is idle, working, waiting, or blocked.
6. **The first run is passive.** Mark, wordmark, one line, two hints. It does not
   teach the three things a new install needs (folder, key, model) and it does
   not show recent work.
7. **Tool cards are flat.** They are readable, but they do not form a run: no
   spine, no duration, no current step, no sense of progress.
8. **The status bar is a footnote.** 11px text in 26px, with the most important
   fact — the agent's state — represented by a small busy word.

---

## 2. What "futuristic" should mean here

Not neon. Not a cockpit of fake gauges. The window is a tool someone keeps open
all day; futurism that costs legibility is costume.

Five principles:

1. **Agent-first, not chat-first.** The conversation stays central, but the
   agent's state is always visible in the same frame.
2. **One workspace, three panes.** Navigation on the left, work in the centre,
   context on the right. Each pane can collapse; the centre never reflows under
   the pointer.
3. **Two mode axes, made legible.** *Workspace* (Agent / Code / Trajectory /
   Usage / Settings) is navigation. *Agent mode* (Chat / Build / Plan / Mission /
   Skills) is how the agent works. They get different visual weight and different
   homes.
4. **Calm surface, one signal.** Keep the achromatic base. Add exactly one
   "live" hue, used only where the agent is actually doing something. Colour
   stays meaning.
5. **Motion tells the story.** A pulse for life, a caret for speech, a spine for
   work. Short, cancellable, and never in the way of typing.

---

## 3. Three directions

### Direction A — Quiet Instrument (low risk)

Dock the existing sidebar, add a right-hand activity summary, improve type and
spacing, keep the current top bar. Feels like Linear or Arc: modern, calm, but
still recognisably a chat app.

- **Cost:** ~4–5 days.
- **Risk:** low; most components stay.
- **Ceiling:** it will look better, not *different*. It does not solve the
  "agent workspace" information problem.

### Direction B — Mission Control (recommended)

A three-pane agent workspace: persistent left navigation, centre conversation,
persistent right context/run panel, command bar on top, telemetry strip at the
bottom. Agent modes become a single chip with a popover; workspaces become the
top-level switch. The transcript gains a run spine and a launchpad.

- **Cost:** ~10–12 working days, phased.
- **Risk:** medium; the shell and `layout.test.ts` change, the core protocol does
  not.
- **Payoff:** the window finally matches what the product is — an agent doing
  work — and uses the width it already has.

### Direction C — Spatial Canvas (high concept)

Conversation as a node graph: each turn a node, tool runs branches, a scrubber
through time. Visually striking, genuinely futuristic.

- **Cost:** high; new rendering model, new interaction grammar, poor fit for long
  prose.
- **Risk:** high; readability and accessibility both suffer.
- **Verdict:** not for the primary window. Keep it as a future "Trajectory"
  experiment, not the daily surface.

**Recommendation: B.** It is the smallest change that actually changes the
category of the app. A is the fallback if the schedule is tight; C is a different
product.

---

## 4. Target layout (Direction B)

### 4.1 Wireframe — Agent workspace, wide window

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◈  TONYAgent   [ Agent ][ Code ]     session tabs …  +      ⌘K   model  ◉ — □ × │ 56
├───────────────────┬──────────────────────────────────────────┬───────────────┤
│  +  New chat      │  Chat / Build · TONYAgent                │  ● Working    │
│  Search…          │                                          │  00:42        │
│                   │  You                                     │  ─────────    │
│  TODAY            │  Refactor the provider registry…         │  Plan   2/5   │
│  ▸ Chat A         │                                          │  ✓ read …     │
│  ▸ Chat B         │  TONYAgent                               │  ● edit …     │
│                   │  ┌ run spine ──────────────────────────┐ │  ○ test …     │
│  YESTERDAY        │  │ ● read   providers/base.py   0.8s ✓ │ │               │
│  ▸ Chat C         │  │ ● edit   providers/base.py  +12 −3  │ │  Files (3)    │
│                   │  │ ○ grep   "chat_only"         …      │ │  base.py +12  │
│  PROJECT          │  └─────────────────────────────────────┘ │  session.py   │
│  TONYAgent        │                                          │               │
│  Skills  4        │  The registry now treats chat-only …     │               │
│                   │                                          │               │
│  ─────────────    │  ┌ composer ───────────────────────────┐ │               │
│  Usage            │  │ Ask TONYAgent…                      │ │               │
│  Settings         │  │ +   Build ▾     budget 3/10    ➤    │ │               │
│                   │  └─────────────────────────────────────┘ │               │
├───────────────────┴──────────────────────────────────────────┴───────────────┤
│ ● Connected │ openrouter / … │ Build │ sandbox stopped │ 12.4k tok │ Logs     │ 30
└──────────────────────────────────────────────────────────────────────────────┘
```

Widths: navigation **248px** expanded / **64px** collapsed; centre flexible;
context **320px** expanded / **48px** collapsed. Reading column stays 760px.
The status strip now spans the whole window, not just `.main`.

### 4.2 Panes and behavior

| Pane | Wide (≥1440) | 1180–1439 | 900–1179 | <900 |
|---|---|---|---|---|
| Navigation | docked 248 | docked 248 | rail 64 | overlay 288 |
| Context | docked 320 | strip 48 (toggle) | overlay 320 | overlay 320 |
| Centre | ≥760 | ≥760 | flexible | full |

- Docked panes have fixed widths; only the centre flexes. Toggling a pane must
  never animate a grid track (that reflows text). The overlay forms slide.
- The navigation pane is **context-sensitive**:
  - Agent: New chat, Search, conversation list, project, skills, Usage, Settings.
  - Code: Explorer / Chats tabs, then the file tree.
  - Trajectory / Usage: hidden or replaced by the view's own rail.
  - Settings: the section nav (the existing settings nav, restyled).
- The context pane is **Agent** in Agent mode, **Assistant / Activity** in Code
  mode, and hidden in Settings/Usage/Trajectory until asked for.
- On <900 the nav and context are overlays with a scrim, reusing the existing
  `useDelayedUnmount` + `data-state` pattern.

### 4.3 Two mode axes

- **Workspace switch** (top bar): `Agent | Code` as a proper segmented control
  with icons. Trajectory, Usage and Settings move to the navigation pane's foot
  and a `⋯` workspace menu. This removes three competing top-level items from the
  tab strip's row.
- **Agent mode** (composer): one chip — `Build ▾` — with a popover listing Chat,
  Build, Plan, Mission, Skills and one sentence each. The selected chip carries a
  dot in the mode's own tone (neutral for Chat/Build, signal for Plan/Mission,
  amber for Skills? decide in phase 2). No five-pill row.
- Tracks stay as they are: a Chat conversation draws only Chat; a Build
  conversation draws the four working modes. Switching tracks still mints a new
  conversation; nothing is converted.

---

## 5. Visual language

### 5.1 Palette: add one signal, keep the rest

Keep every existing neutral. Add:

| Token | Value | Use | Contrast on `--bg` |
|---|---|---|---|
| `--signal` | `#78e3ff` | live agent state, busy ring, streaming caret, run spine node, context meter | **11.79:1** |
| `--signal-dim` | `#4aa8c2` | inactive/complete nodes, secondary live text | **6.36:1** |
| `--signal-wash` | `rgb(120 227 255 / 0.12)` | selected activity row, focused context card | — |
| `--signal-glow` | `rgb(120 227 255 / 0.22)` | pulse behind the status orb, composer focus bloom | — |

Measured on the other surfaces it may land on: `--signal` is 8.56:1 on `--raised`
(#333) and 7.36:1 on `--chip` (#3d3d3d), so it is safe for small text anywhere.
`--signal-dim` is 4.62:1 on `--raised` and **3.97:1 on `--chip`**, so it is for
graphics and for text on `--bg`/`--surface` only; it must not carry small text on
the raised chip.

Rules:

- `--accent` remains white and remains the fill of primary controls. Signal is
  **not** a button colour; it is a state colour.
- Signal is never used for body text below 12px without checking the surface it
  lands on; `--signal-dim` has the one failing pairing above.
- `--warn` (amber) stays the approval colour. A pending approval is the one
  thing allowed to pull the eye away from signal.
- Success/danger/warn keep their current values. No new status hues.
- Update the token comment: the window is still achromatic *except* meaning —
  signal is the agent's meaning, not a brand colour.

Mint alternative if cyan reads too "sci-fi": `#7ef0c8` (mint). Amber is not
recommended for live state because it collides with warning.

### 5.2 Material and depth

- Keep the glass. Extend it to the new panes so the window has one material:
  chrome glass for top bar, nav, context and status; panel glass for overlays;
  field glass for the composer.
- Add a **lit inner edge** to the focused pane:
  `box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.06)` already exists on panels;
  the active pane gets `inset 0 0 0 1px var(--glass-edge)` and a 1px signal line
  on its inner edge only while the agent is working. No outer glow on whole
  panes — that reads as a website.
- Background: add a static, very low-contrast **dot grid** behind the centre
  pane, masked to the empty/launchpad area only. 2% white, 24px pitch, no image
  request. It gives the field a sense of space without touching text contrast.
- Composer focus: a signal-tinted bloom (`box-shadow: 0 0 0 1px var(--signal)`,
  `0 0 48px var(--signal-glow)`) plus the existing white border. This is the one
  place a glow is allowed to be visible.

### 5.3 Typography

- Base **14px** (from 13), prose **15px / 1.65**, UI labels **12px / 1.3**,
  metadata **11px / 1.25**, code **12.5px**.
- Add two display steps: `--text-2xl: 28px`, `--text-display: 36px` for the
  launchpad headline and the dashboard totals.
- Headlines: Inter 600, `letter-spacing: -0.015em`.
- Section labels: 11px, 700, uppercase, `letter-spacing: 0.09em`, `--fg-mute`
  (already the panel-head style; reuse it instead of inventing a second).
- Mono is extended from "literal code" to **literal identifiers**: tool names,
  model ids, paths, token counts. Not prose. This is a small, defensible widening
  of the current rule.
- Keep `--measure: 760px`; prose at 15px gives ~70 characters per line. Code
  viewer keeps its own measure.

### 5.4 Shape and iconography

- Keep the existing radius ladder. Controls stay stadiums; rows stay boxes.
- New icons are 1.6–1.8px strokes, 16/18/20px, same family as the rail. No filled
  icons except status dots and the send glyph.
- The navigation pane's sections use a 1px rule + label, not cards. Cards are
  reserved for the context panel's three facts (Run, Plan, Files).

### 5.5 Motion

| Name | Where | Duration | Reduced motion |
|---|---|---|---|
| `signal-breathe` | status orb while working | 3.2s infinite | static |
| `caret-blink` | streaming text caret | 1s steps(2) | static |
| `node-in` | tool step arrival | 160ms | none (instant) |
| `spine-grow` | run spine progress | 240ms | none |
| `pane-reveal` | context panel overlay | 240ms | none |
| existing `rise-in` / `pop-in` / `slide-in-left` | as today | as today | as today |

No animation on a grid track. No parallax. No animation on the launchpad after
its first arrival.

---

## 6. Component plan

### 6.1 Top command bar

- Height 56px (`--topbar-h: 56px`), spans the window, same drag-region rules.
- Left: 40px mark + `Agent | Code` segmented control.
- Centre: session tabs (existing behavior, restyled):
  - 34px tall capsules with a 6px status dot (idle/working/approval), title,
    close on hover/active.
  - Busy tab: signal dot pulses; width unchanged.
  - New tab `+` after the strip; `⋯` menu for Trajectory/Usage/Settings.
- Right: a compact **status pill** (`● Working · read_file`), model chip, caption
  buttons. The status pill opens the context panel if it is collapsed.
- Search: a `⌘K` ghost button between the tabs and the model chip, opening the
  existing SearchPanel as a command palette (phase 2; the keyboard shortcut is a
  later decision).
- No duplicate mode pills here. The agent mode lives in the composer.

### 6.2 Left navigation dock

- 248px wide, glass chrome, 16px inset (`--pad-panel`).
- Header: wordmark? The top bar already has the mark; the dock starts with
  `+ New chat` (full-width, 40px, accent fill, black ink) and a search row.
- Conversation list: reuse `ConversationList` internals — date groups, row menu,
  rename, duplicate, delete, filter. Remove the overlay/scrim behavior on wide
  screens; keep it for <900.
- Project block: folder name, `Change…`, branch if available, recent files (max
  3). Clicking a file opens Code at that file.
- Skills block: count + `Manage` (opens Settings → Skills).
- Foot: Usage, Settings, connection dot, pet toggle. The rail's actions move
  here when docked; the 64px rail remains the collapsed state.
- In Code: a two-tab head — `Explorer` / `Chats`. Explorer reuses `FilesPane`;
  Chats reuses the conversation list. This is the one place the two sidebars
  merge, and it removes the current mode-specific left column.

### 6.3 Centre: transcript

- Keep the 760px reading column and the shared inset.
- User turns: right-aligned capsule, max 560px, `--raised`; same as today.
- Assistant turns: full-width prose, but with an **agent gutter**:
  - 24px column on the left holding the run spine and status nodes.
  - Prose starts at the shared column inset.
  - This is where the "agent did work" story is drawn; the text itself stays
    untouched.
- **Run spine**: a 1px vertical line from the first tool step to the last, with
  8px nodes:
  - hollow ring = pending/queued
  - signal dot with pulse = running
  - check = ok
  - × = failed
  - amber ring = waiting for approval
  - The spine only exists while a turn has tool activity; a pure prose answer has
    no spine.
- **Tool row** (replaces the current card body):
  - leading node, tool name in mono, one-line summary, duration, chevron.
  - Expanded: args/result, diff, nested subagent block (existing `SubagentWork`).
  - Running row: the summary is the live action ("Running read_file · 0.8s").
  - Clicking a row does not navigate; it expands. A `path` chip opens Code.
- **Approval**: an inline card pinned above the composer (see 6.4), plus the
  existing modal for destructive confirmation. The inline card is the primary
  affordance; the modal remains for Enter/Escape parity.
- **Streaming**: assistant text gets a 2px signal caret at the end; the composer's
  status pill says "Writing". No full-width progress bars.
- **Error**: one banner row at the bottom of the transcript, same as today, with
  a "Diagnostics" link to Settings.

### 6.4 Centre: composer

```
┌───────────────────────────────────────────────────────────────┐
│  Ask TONYAgent…                                               │
│                                                               │
│  +   Build ▾        budget 3/10        [context 18%]     ➤    │
└───────────────────────────────────────────────────────────────┘
```

- Keep the glass field and the 24px radius. Min height 64px, max 280px.
- Row 1: textarea, placeholder changes by mode ("Describe the change…" for Build,
  "Ask anything…" for Chat).
- Row 2:
  - `+` attach (existing).
  - Mode chip with popover (one control, not five pills).
  - Budget chip (existing popover).
  - Context meter: a 48px-wide 2px bar + percentage, only when a turn is running
    or context > 60%. Tooltip explains it.
  - Send/Stop disc at the right.
- Focus: white border + signal bloom. No second focus ring (existing rule).
- Approval card, when pending, sits directly above the field, full column width:
  `Allow` (accent), `Always`, `Deny`, plus the tool name and one-line risk. It
  must not cover the transcript.
- Mode hint line stays below, 11px `--fg-mute`, one sentence.

### 6.5 Centre: launchpad (first run / empty chat)

Replace the centred mark block with a **launchpad** that fits the same column:

```
        ◈  (breathing signal glow)
        What should we build?

        TONYAgent · C:\work\project

  ┌────────────────────┐  ┌────────────────────┐
  │ Explore the project│  │ Fix a failing test │
  └────────────────────┘  └────────────────────┘
  ┌────────────────────┐  ┌────────────────────┐
  │ Plan a feature     │  │ Review changes     │
  └────────────────────┘  └────────────────────┘

  Recent: Chat A · Chat B · Chat C
  [ Change project folder… ]
```

- Four suggestion cards are prefilled prompts, not fake actions. They insert text
  into the composer; they never send.
- Recent conversations come from the existing list (max 3).
- If no folder is chosen, the first card becomes `Choose a project folder…` and
  the grid collapses to one column.
- If no provider key, a slim setup card appears below the headline with a
  `Open Keys` button (existing `needsProvider` state).
- The dot grid and signal glow live here, not behind the transcript.
- Reduced motion: no breathing; the mark is static.

### 6.6 Right context panel — "Agent"

320px, glass panel, collapsed to a 48px strip with a vertical label and the
status orb. Three stacked sections:

1. **Run** (top card)
   - status orb + one word: Idle / Working / Waiting / Error.
   - elapsed timer for the current turn.
   - model + mode as two chips.
   - token in/out for the turn (when available) and context percentage.
   - Stop button while working; "Open Trajectory" link.
2. **Plan** (from `plan.get` / `todo_write`)
   - goal line (if any), progress `2/5`, five rows max with status glyphs.
   - rows are read-only here; clicking scrolls to the tool call that wrote them.
   - empty state: "No plan yet — ask for one."
3. **Activity** (derived from the current message's tool calls)
   - last 6 calls, newest first or chronological? **Chronological, newest at the
     bottom**, so it reads as a log and the live row is nearest the composer.
   - each row: status, tool name (mono), summary, duration.
   - a `View all` expands to the full turn.
4. **Files touched** (footer, collapsible)
   - path, +/− counts, click opens Code at the file.
   - max 5, then `+ N more`.

Data: everything except token counts and plan comes from `events.ts` today.
`plan.get` exists on the wire but is not in the frontend types — phase 0 adds
the type and a `plan.refresh()` call on turn start/finish. Token counts need one
of: a per-turn usage event, or a `usage.turn` RPC; decide in phase 0 (see §8).

### 6.7 Bottom telemetry strip

- 30px, spans the full window (`grid-row: 3`), glass chrome.
- Left: connection dot + `Connected` / `Offline`.
- Provider / model (click opens the model picker).
- Agent mode chip (`Build`).
- Sandbox state (click opens Settings → Sandbox).
- Right: token count for the turn, context %, `Logs` toggle.
- At <560, drop the word beside the dot and the sandbox, exactly as today.
- This replaces the current status bar; its existing tests move with it.

### 6.8 Settings, Usage, Trajectory

- **Settings** keeps the full-window page. Its left nav becomes the same 248px
  dock (visually), with sections as rows and a `Back to chat` at the top. Content
  width stays ~720px; cards get 16px insets.
- **Usage** gets the display type step, a 4-up stat row, and a 1px grid. No new
  charts in this pass.
- **Trajectory** becomes the "deep run" view: the same spine, but full-width with
  filters (tools only / errors / approvals). This is where the future canvas
  experiment can live without touching the main window.

### 6.9 Desktop pet

- Phase 1: leave it alone.
- Phase 5: make the pet the **same presence** as the status orb. The orb in the
  top bar/context panel is the in-window face; the pet is the out-of-window face.
  Same states, same signal hue, same breathing rhythm. Do not add a second
  character or a second status vocabulary.

---

## 7. Responsive ladder

The current ladder is 720 / 560 / 420 and `layout.test.ts` enforces it. The
three-pane layout needs its own steps. Proposed ladder:

| Step | What changes |
|---|---|
| **1440** | context panel docks at 320; nav at 248 |
| **1180** | context collapses to 48px strip |
| **900** | nav collapses to 64px rail; context becomes an overlay |
| **720** | existing chrome squeeze: tab caps, model chip ellipsis, caption 38px |
| **560** | status drops secondary facts; tab caps floor |
| **420** | tab strip hides; controls that must remain win |

Six steps, each with one job. `layout.test.ts`'s media-query guard is updated to
this list in the same commit that introduces the first new query. Container
queries stay for the code viewer only.

---

## 8. Data wiring: what exists, what is missing

| Surface | Source | Status |
|---|---|---|
| Conversation list, tabs | `conversations.*` | exists |
| Messages, streaming | `message.*`, `reasoning.*` | exists |
| Tool rows, status, summary, path, +/− | `tool.*`, `file_change` artifact | exists |
| Nested subagent work | `parent_call_id`, `SubagentChild` | exists |
| Approvals / questions | `confirmation.*`, `user.*`, `pendingConfirm`, `pendingAsk` | exists |
| Sandbox, connection, model, provider | `state`, `sandbox.status` | exists |
| Plan | `plan.get` handler | exists on the wire, **not typed in `app/src`** |
| Usage history | `usage.summary` | exists (per window) |
| Per-turn tokens / cost | — | **missing**; add `usage.turn` or a `turn.usage` event |
| Turn elapsed | — | **missing**; client-side timer from `turn.started`, or add `started_at` |
| Goal | `get_goal` tool result | **not exposed** as state; derive from the last `get_goal`/`update_goal` card or add `goal.get` |
| Files touched | tool calls with `path` | exists; needs a selector |

Phase 0 is a short audit commit: add the missing types/selectors and the one
usage/timer source, with no visual change. This keeps the visual phases from
blocking on protocol work.

---

## 9. Implementation phases

Each phase is independently shippable and testable. No phase changes core tool
semantics.

### Phase 0 — Data and baselines (1 day)
- Add `plan.get` to the frontend protocol types; one `plan.refresh()` call on
  turn start/finish.
- Decide per-turn usage: prefer a `turn.usage` event over a new RPC (one
  publisher, no polling).
- Add a client-side turn clock in `events.ts` / `App.tsx` (derived, no protocol).
- Add `activity.ts`: selectors for current turn's tool list, files touched,
  elapsed, status.
- Capture baseline screenshots at 1600×1000, 1280×800, 900×700, 560×700 into
  `design-preview/` (not `.shots/`, which is scratch).
- **Acceptance:** no visual change; all tests green; new selectors unit-tested.

### Phase 1 — Shell restructure (2–3 days)
- Three-pane grid; status bar moves to shell row 3.
- Nav dock at 248/64; conversation list docks on wide screens.
- Context panel shell (empty cards) at 320/48; collapse behavior.
- Responsive ladder + overlay behavior for <900.
- **Files:** `App.tsx`, `styles/shell.css`, `styles/rail.css`,
  `styles/conversation-list.css`, `styles/statusbar.css`, new `styles/context.css`,
  `styles/nav.css`; `layout.test.ts`.
- **Acceptance:** no reflow when toggling panes; keyboard order matches visual
  order; all existing behavior reachable; screenshots at four widths.

### Phase 2 — Command bar and launchpad (2 days)
- Top bar: workspace switch, session capsules, status pill, `⌘K`.
- Move Trajectory/Usage/Settings into the nav/`⋯`.
- Launchpad with suggestions, recent chats, setup card.
- **Files:** `TopBar.tsx`, `Composer.tsx` (mode chip), new `Launchpad.tsx`,
  `styles/topbar.css`, `styles/composer.css`, `styles/launchpad.css`.
- **Acceptance:** every current top-bar action still reachable; suggestion cards
  only prefill; no fake buttons; first-run path with no folder/key/model.

### Phase 3 — Context panel data (2–3 days)
- Run card, Plan card, Activity feed, Files touched.
- Wire `plan.get`, usage/turn clock, file selector.
- Click-through: activity row → transcript; file → Code at path; approval →
  inline card.
- **Files:** new `ContextPanel.tsx`, `RunCard.tsx`, `PlanCard.tsx`,
  `ActivityFeed.tsx`, `FilesTouched.tsx`; `activity.ts`, `events.ts`,
  `styles/context.css`; tests.
- **Acceptance:** the panel is correct during a live turn, after restore, during
  an approval, and with no provider; no duplicate state.

### Phase 4 — Transcript and tool timeline (2 days)
- Agent gutter + run spine; tool row redesign; inline approval card; streaming
  caret.
- Keep `MessageList`'s ordering by `startedAtChars` exactly.
- **Files:** `MessageList.tsx`, `events.ts`, `styles/transcript.css`,
  `styles/tool-calls.css`, `styles/confirm-modal.css`.
- **Acceptance:** captured child-frame fixture still renders correctly; long
  runs, failures, parallel batches, and nested subagents all keep their shape.

### Phase 5 — Visual polish and motion (1–2 days)
- Signal tokens, typography steps, dot grid, composer bloom, breathing orb,
  pane lit edges.
- Reduced-motion audit for every new animation.
- Contrast checks for signal on every surface it lands on.
- **Acceptance:** `audit_reduced_motion.py` clean; `layout.test.ts` contrast
  assertions; no raw hex outside tokens.

### Phase 6 — Docs and verification (1 day)
- Update README screenshots/feature notes, `NEXT_SESSION.md`, this plan's status.
- Re-run Python 1685 / TypeScript 996, plus new suites; `verify_window.py`
  measurements at four widths.
- **Acceptance:** green tree; screenshots committed; handoff current.

**Total:** ~10–12 working days. Direction A would be ~4–5; Direction C is not
estimated because it is a different product.

---

## 10. Test plan

The existing suite is the reason this can be done safely. It stays green
throughout, with deliberate updates only where the design changes.

### Python
- No core changes expected except the optional `turn.usage` event (schema test).
- `tests/unit/test_window_host.py::PAGE_API` changes only if a bridge method is
  added. None planned.
- `scripts/verify_window.py` gains measurements: nav width, context width,
  status strip span, composer focus bloom, no reflow on toggle.

### TypeScript
- `layout.test.ts`:
  - new shell rows/columns; status bar spans the window;
  - pane widths fixed, centre flexes;
  - new breakpoint ladder;
  - signal contrast table (≥4.5:1 for small text, ≥3:1 for graphics);
  - token-only colours; no raw lengths the scale owns;
  - stadium/box rules unchanged;
  - reduced-motion coverage for every new animation.
- New `activity.test.ts`: derive files/status/elapsed from a captured turn.
- New `launchpad.test.ts`: suggestions prefill, never send; states for no
  folder/key/model.
- `App.test.tsx`: shell landmarks, keyboard order, pane toggles, session tabs.
- `MessageList.test.tsx`: spine nodes for ok/failed/running/approval; nested
  subagent cards unchanged.
- `backend.test.ts`: unchanged (protocol contract).
- `motion.test.ts` + `reducedMotion.test.ts`: new names, no leaks.

### Manual / visual
- Four screenshots per phase at 1600×1000, 1280×800, 900×700, 560×700.
- One live turn with a real provider: text stream, tool batch, approval, stop.
- Code mode: explorer + file + assistant; open externally.
- Settings: every tab, keyboard-only.
- Reduced motion: OS setting on; no pulse, no slide, no caret blink.

---

## 11. Risks and non-goals

### Risks

1. **Scope creep in the context panel.** It can become a second app. Keep it
   read-only in this pass; actions stay in the transcript/composer.
2. **Shell rewrite vs. tests.** `layout.test.ts` is large and intentionally
   brittle. Change the assertions in the same commit as the CSS, never after.
3. **Animation of layout tracks.** Never animate grid columns; text reflow under
   the pointer is the failure the current design already avoids.
4. **Signal colour overuse.** One hue, one meaning. If it appears on buttons,
   links, selected rows and badges, it stops being a signal.
5. **Density regression.** 14px base and a 320px panel can crowd a 1280px
   window. The 1180 breakpoint collapses the context first; verify at 1180.
6. **Data gaps.** Per-turn tokens and goal are not on the wire today. Phase 0
   must close them or the Run/Plan cards will be decorative.

### Non-goals

- No light theme.
- No new UI framework or state library.
- No changes to tool permission semantics.
- No canvas/node-graph main view.
- No voice input, no fake AI controls.
- No mobile layout; the window is desktop-first, with narrow-window fallbacks.
- No changes to the desktop pet in phases 0–4.

---

## 12. Decisions needed before implementation

1. **Direction:** B (Mission Control) recommended; A as fallback; C as a future
   Trajectory experiment.
2. **Signal hue:** cyan `#78e3ff` recommended; mint `#7ef0c8` alternative; stay
   monochrome if you want zero new chroma.
3. **Navigation:** dock the conversation list on wide screens (recommended) or
   keep the overlay at every width.
4. **Density:** 14px base / 15px prose (recommended) or keep 13px.
5. **Context panel actions:** read-only summary (recommended for this pass) or
   include approvals and stop controls.
6. **Tabs:** keep the browser-style tab strip, restyled (recommended), or replace
   it with a single session switcher + command palette.
7. **Schedule:** all six phases, or stop after Phase 2 (shell + launchpad) and
   reassess.

---

## 13. Appendix: token delta

```css
/* geometry */
--nav-w: 248px;
--nav-w-collapsed: 64px;      /* equals --rail-w */
--context-w: 320px;
--context-w-collapsed: 48px;
--topbar-h: 56px;             /* was 52 */
--statusbar-h: 30px;          /* was 26 */

/* type */
--text-2xl: 28px;
--text-display: 36px;

/* signal */
--signal: #78e3ff;
--signal-dim: #4aa8c2;
--signal-wash: rgb(120 227 255 / 0.12);
--signal-glow: rgb(120 227 255 / 0.22);

/* motion */
--motion-ambient: 3200ms;     /* breathing only; not for UI state */
```

Every new step is used by at least one rule, because `layout.test.ts` asserts
that; the table above is the contract for the change.

---

## 14. What happens after approval

1. Phase 0 lands as a no-visual-change commit with selectors and baselines.
2. Phase 1 lands behind no feature flag: the shell is the change, and the old
   overlay behavior remains for <900.
3. Each phase ends with screenshots and a handoff note; you review before the
   next one starts.
4. If Direction B is too much, we stop after Phase 2: the window has the new
   shell, command bar and launchpad, and the context panel remains a later
   addition.
