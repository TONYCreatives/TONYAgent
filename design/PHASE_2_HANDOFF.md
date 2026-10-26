# Workspace refine — Phase 2 handoff

**Landed:** 2026-10-23
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §6.1–6.5, §9 Phase 2
**Scope:** the desktop window (`app/`), not the core protocol.

Phase 2 of Direction B (Mission Control) is in the tree. The core protocol,
tool semantics and the desktop pet are untouched.

---

## What shipped

### The view switch moved into the nav

- `ViewSwitch` is a labelled segmented control (`Agent | Code | Trajectory`)
  in the nav's head — the surface that is *about* where you are — and the same
  control in Code's explorer head, which is Code's nav until Phase 5. Settings
  renders none: its back control is the way out and the three workspaces are
  not "views of" it.
- `RailViewButton` is the compact form: at 64px, one button showing the current
  workspace's glyph and a portalled menu with the three. It sits directly under
  the sidebar toggle, first in the strip. **Without it Trajectory had no exit at
  1100 and below** — the switch lived in a nav you had to open first.
- Code is disabled with no folder, and says why on its tooltip, in both forms.
- `TopBar` no longer imports or draws the switch. Its left region is the 64px
  mark and the tab strip, so the strip still starts at x=64 at every width.

### Nav content

- **New chat** (row, `+` glyph) and **Skills** (row, `/` mark) sit under the
  pane tabs, above the list. Rows rather than stadiums: the panel's one loud
  object stays the conversation you are in.
- Skills writes `/` into the composer — the field's own menu lists, filters and
  inserts, so a second list in 288px would be a second place for them to
  disagree. From Trajectory it returns to Agent first, and below 1101 it closes
  the overlay it just wrote underneath.
- The foot is the whole rail: Search, Usage (toggle), pet (toggle), Settings
  (with the update dot), each carrying `aria-pressed` where it is a toggle.
- The nav is **open by default on a window that can dock it** (≥1101) and
  closed below, unless a stored preference says otherwise. `data-nav` is the
  state; the stylesheet sizes column 1 from it.

### Status pill

- `StatusPill` replaces the status strip's busy word: Idle / Working /
  Waiting / Error, the orb the run card draws, and the running tool's name.
  In Agent it is present while idle, because it is the run panel's handle.
- In Code, Trajectory and Settings it is **absent when idle** and a **28×24
  dot** (6px orb) while a turn runs; pressing it returns to Agent. Nothing
  that reports a turn you cannot see is drawn.
- Colour transitions over `--motion-fast` rather than snapping between states;
  the label is written out (`Working, read_file. Show the run panel`) because
  the detail is hidden at 720 and the word at 560.

### Composer: one mode chip

- `ModeChip` replaces the row of mode pills: the mode in force, a caret, and a
  menu of the modes the core offers for this track with their descriptions.
  One mode (a chat-track conversation) is a static label, not a menu. The menu
  opens upward from the composer's control row.
- The chip reports; the window still applies what the core replies with.
  Pressing the mode already in force is a no-op.
- `Composer` gained a `prefill` request (`{text, nonce}`), applied once and
  acknowledged, so the launchpad's suggestions and the nav's Skills row write
  into the field instead of sending.

### Launchpad

- Replaces the old first-run panel inside the empty conversation: the mark,
  the wordmark, one line of orientation, the setup card, four suggestions and
  the last three chats. Recent rows are newest-first, skip the open
  conversation and skip empty ones.
- The setup card lists only what is actually missing — no folder, no provider,
  no model. The model row has no button (the menu is in the title bar); the
  folder row and the provider row have the control that fixes them. When the
  folder is missing the card owns that row, so the panel never says it twice.
- Suggestions **prefill, never send**, and there is no send prop on the
  component at all. With no core they are not drawn, because a prefill into a
  disabled field is a promise the window cannot keep.

### Trajectory gets the nav dock

- Trajectory is a workspace beside Agent, not a page that replaces the window:
  the rail and the conversation list are mounted, the log takes the centre, and
  the tab strip and the context strip are not reserved. `trajectory.css` no
  longer rewrites the shell's columns or moves `.main` — those rules put the
  log in the nav's track once the dock existed.

### Shell

- The nav can be docked at 1101+ (`data-docked`), as an opaque 288px track with
  no scrim, no shadow and no slide; below 1101 the same panel is the overlay it
  was. `--nav-w` is sized by `data-nav`.
- At ≤900 the rail floats for Trajectory as it does for Agent (one-column
  shell, rail absolute, page inset) — and Trajectory's inset is the full
  `--rail-w`, because the log has no centred column to carry `--column-edge`
  inside itself.

---

## Measured gates

Read from the running page in Chromium at 1400×900, 1101×800, 1100×800,
901×700, 900×700, 720×640 and 640×600:

| Width | `grid-template-columns` | Nav | Centre | Composer |
|---:|---|---:|---:|---:|
| 1400 (both docks) | `288px 824px 288px` | dock 288 | **824** | 760 @ x=320 |
| 1101 | `288px 765px 48px` | dock 288 | **765** | 701 @ x=320 |
| 1100 (nav open) | `64px 988px 48px` | overlay 288 + scrim | **988** | 760 @ x=178 |
| 901 | `64px 789px 48px` | rail 64 | **789** | 725 @ x=96 |
| 900 | `900px` | rail 64, floating | **900** | 760 @ x=78 |
| 720 | `720px` | rail 64, floating | **720** | 608 @ x=64 |
| 640 | `640px` | rail 64, floating | **640** | 528 @ x=64 |

- Nav head at 288: toggle 36 + switch 184 = 252 inside 287, no overflow.
- Top bar at 640 with a simulated 3×38px caption cluster: `scrollWidth` equals
  `clientWidth`; the spacer absorbs the difference (160px left).
- Trajectory at 1400 with the dock: `288px 1112px`, log at x=288, no tab strip.
- Trajectory at 720: log at x=64 (was x=32, with the head's text at x=48 under
  the 64px rail), head text now x=80.
- The status pill in Trajectory is 28×24 and draws no text; its `aria-label`
  still names the state and the tool.

---

## Deliberate deviations from the plan

1. **New chat and Skills are rows, not a 40px accent button plus a search row.**
   The dock already has the pane tabs as its first row; a filled accent button
   under them would make starting a chat the loudest object in a panel whose
   subject is the chat you are already in. Search stayed in the foot, where the
   rail also keeps it, so the two states of the sidebar cannot disagree.
2. **The dock head keeps the toggle beside the switch.** Phase 1's test pins the
   head to the toggle, and the head is the same control in both states of one
   sidebar. The switch joins it rather than replacing it.
3. **The rail gained a view button.** The plan's rail list does not include one,
   but once Trajectory has the dock and the switch lives in the nav, a closed
   nav in Trajectory leaves no control that changes the workspace. One button
   and a menu is the form that fits 64px.
4. **Trajectory's ≤900 inset is `--rail-w`, not `--rail-w - --column-edge`.**
   That subtraction is correct where a centred column carries the edge itself;
   the log has no such column, so it put the first 16px of every row under the
   rail.
5. **The pill is a dot, not a compact text pill, where there is no panel.** The
   plan says "a compact dot that returns to Agent"; the state word is already
   the transcript's, one mode away.

---

## Verification

- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1043 tests, 1043 pass** (1013 after Phase 1).
  New suites: `ViewSwitch.test.tsx`, `StatusPill.test.tsx`,
  `Launchpad.test.tsx`; `TopBar`, `App`, `Composer`, `ConversationList`,
  `IconRail` and `layout` updated for the moved switch, the chip and the dock.
- `cd app && npm run build` — clean; `dist/` rebuilt.
- `python -m pytest -q` — **1685 passed, 24 skipped, 1 failed**. The failure is
  `tests/integration/test_docker_backend.py::test_start_ping_exec_stop`, which
  cannot reach a Docker daemon on this machine; it is environmental.
- `python scripts/audit_reduced_motion.py` — clean.
- `layout.test.ts`'s transition audit is clean: the pill's state colour now
  transitions, and the two instant rules it flags are listed with their reason
  (the rail leaving the grid at 900, in both modes).

No screenshots were captured: the gates above are measurements, and visual
review is the user's.

---

## What is not here yet (Phases 3–7)

- Plan / Activity / Files cards in the context panel, per-turn token counts and
  the elapsed clock's remaining wiring (Phase 3).
- Run spine, tool-row rewrite and inline approvals (Phase 4).
- Code-mode explorer/assistant unification; the nav's Explorer/Chats tabs
  (Phase 5).
- Signal hue, opaque docks' final material, display type and motion (Phase 6).
- Screenshots, README and `NEXT_SESSION.md` updates (Phase 7).

## Files touched

```
app/src/App.tsx
app/src/Composer.tsx
app/src/MessageList.tsx
app/src/TopBar.tsx
app/src/ConversationList.tsx
app/src/StatusBar.tsx
app/src/IconRail.tsx
app/src/Launchpad.tsx               (new)
app/src/ModeChip.tsx                (new)
app/src/StatusPill.tsx              (new)
app/src/ViewSwitch.tsx              (new)
app/src/relativeTime.ts             (new)
app/src/useDismiss.ts
app/src/nested-preview.tsx
app/src/styles.css
app/src/styles/composer.css
app/src/styles/conversation-list.css
app/src/styles/launchpad.css        (new)
app/src/styles/reduced-motion.css
app/src/styles/shell.css
app/src/styles/statusbar.css
app/src/styles/topbar.css
app/src/styles/trajectory.css
app/src/styles/transcript.css
app/src/styles/viewswitch.css       (new)
app/src/App.test.tsx
app/src/Composer.test.tsx
app/src/ConversationList.test.tsx
app/src/IconRail.test.tsx
app/src/Launchpad.test.tsx          (new)
app/src/MessageList.test.tsx
app/src/StatusPill.test.tsx         (new)
app/src/TopBar.test.tsx
app/src/ViewSwitch.test.tsx         (new)
app/src/layout.test.ts
design/PHASE_2_HANDOFF.md           (new)
```
