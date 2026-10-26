# Workspace refine — Phase 3 handoff

**Landed:** 2026-10-25
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §9 Phase 3
**Scope:** the desktop window (`app/`), not the core protocol.

Phase 3 of Direction B (Mission Control) is in the tree: the context pane is now
the run, the plan, the feed and the files rather than a Run card alone. The core
protocol, tool semantics and the desktop pet are untouched.

---

## What shipped

### The pane's three forms, unchanged

- Closed: a 48px strip with the status orb and a vertical `Run` label.
- Docked at ≥1400: a 288px column, `288px 824px 288px` at the gate width.
- Overlay below 1400: the same 288px surface floats left over the centre, with a
  scrim covering the centre only. The centre keeps its width; only the panel's
  width changes, and no grid track is transitioned.
- The head is the pane's title and its one way shut; the strip is hidden while
  it is open. Escape is not bound here — the scrim and the head's × are the two
  deliberate exits, and the strip returns the moment it closes.

### Run card (`RunCard.tsx`)

- State (Idle / Working / Waiting / Error), the turn clock, the live sentence
  and the context meter, in that order.
- **No model or mode.** Both stay where they are changed: the title bar's model
  menu and the composer's mode chip. A third copy is a third thing to drift.
- The clock is the card's own `setInterval`, started only while a turn runs, so
  a tick re-renders one card rather than the transcript. It is not a live
  region: a region that changes every second never stops talking.
- The meter has three honest states: `unknown` with no bar when nothing was
  measured, `62.4k used` when usage is known but the window is not, and
  `62.4k / 124k · 50%` only when both numbers are real. A bar is never filled
  from an invented denominator.
- `Stop` appears only while working; `Open Trajectory` is always there.
- The sentence is the pane's **only** live region (`aria-live="polite"`). The
  activity rows deliberately have none: a region per row would read the whole
  feed aloud at every tool call.

### Plan card (`PlanCard.tsx`)

- Goal, its state (`done` / `blocked` when the core says so), progress in the
  section head (`2/7`), and five rows with `+N more in the transcript`.
- **Read-only.** The rows are not checkboxes: ticking one here would change the
  plan behind the agent's back, and the next `todo_write` would undo it.
- A row scrolls to the call that wrote the plan — but only when that call is in
  the transcript. A plan restored from disk has no tool events, so its rows are
  plain text rather than buttons that scroll nowhere.
- `aria-label="Plan, 1 of 7 done"` on the list, so the count is read even when
  the marks are only glyphs.

### Activity feed (`ActivityFeed.tsx`)

- Chronological, oldest first, **the newest six** and `View all N` / `Show
  fewer`. Newest at the bottom keeps the live row nearest the composer and stops
  every row from moving on every call.
- Status mark, tool name, the core's summary and the measured duration. A
  summary equal to the tool's name is not repeated (`grep grep`).
- A call whose duration the window never saw — every row in a restored
  conversation — draws no number rather than an invented one.

### Files (`FilesTouched.tsx`)

- Five rows, a remainder line, and `+N · −N` from the core's `file_change`
  artifact, summed per path (three passes at one file are one row, not three
  overstated ones).
- The file's name leads and its directory is context beside it, in one text run
  so a long path truncates as a path rather than as two halves.
- Pressing a row opens Code at the **whole** path, not the part drawn.

### Panel behaviour (`ContextPanel.tsx`)

- **An accordion, one section at a time.** At 288px, four open sections are a
  document; one is a glance. Opening while a turn runs starts on Activity,
  opening idle starts on Plan. A reader's choice survives the next tool call;
  a new run is a new moment and brings Activity back.
- The Run card is sticky at the top of the pane's one scroller. The pane is a
  place to answer "is it still working", and a card that scrolled under the
  plan would make the reader hunt for it.
- The pane reports; it does not own data. Every press calls back into `App`,
  which is the only place that decides what the run is.

### Wiring (`App.tsx`, `activity.ts`, `events.ts`)

- `turnActivity(state)` derives the run state, this turn's steps, the files,
  counts and elapsed time in one pass; the window memoises it on the fields that
  can change it.
- `events.ts` stamps `turnStartedAt` on `turn.started` (cleared on every end
  path) and `startedAt` / `endedAt` on each tool call. Both are this window's
  clock, not the core's: the numbers describe what the user watched. `endedAt`
  is stamped once, so a duplicate completion cannot lengthen a row.
- `plan.get` is read at boot, on a conversation change and at a turn boundary;
  it is re-read when a `todo_write` / `create_goal` **completes**, which is the
  only moment it can differ. No per-tool polling.
- `context.get` is read at the same edges **only while the pane is open** — a
  number nobody can see is not worth a request per turn.
- A plan row closes the overlay first (below 1400) and scrolls on the next
  frame, so it is not scrolling a container that is about to be hidden. No
  smooth behaviour: a scripted smooth scroll would ignore `prefers-reduced-motion`.
- A touched file switches to Code and opens it through the same path the
  explorer uses.
- The scrim is mounted only for the overlay form, after `.main` in the DOM so
  the tab order stays nav → centre → context → strip.

### Styles (`styles/context.css`, imported from `styles.css`)

- Section heads, the accordion body, the plan rows and marks, the activity rows,
  the file rows, the run card's line / sentence / meter / actions, the sticky
  wrapper and the overlay form. Status colours transition over `--motion-fast`;
  no state repaint is instant, which is what the layout guard checks.

---

## Measured gates

Read from the running window in Chromium, with a fake core playing a seven-call
turn (plan 7 items, 3 files, context 62.4k / 124k):

| Width | `grid-template-columns` | Context | Centre | Composer |
|---:|---|---:|---:|---:|
| 1400 | `288px 824px 288px` | dock 288 @ x=1112 | **824** | 760 @ x=320 |
| 1100 | `64px 988px 48px` | overlay 288 @ x=812 | **988** | 760 @ x=178 |
| 900 | `900px` | overlay 288 @ x=612 | **900** | 760 @ x=78 |

- **Docked (1400):** panel 287 inside the 288 track; run card 255 wide; the
  meter's 69px bar filled 35px at 50%; activity 6 rows + `View all 7` at 19px
  each; plan 5 rows + `+2 more`; files 3 rows at 255px with `+12 −3`, no
  horizontal overflow anywhere.
- **Sticky:** with a 900px probe added to the scroller and `scrollTop=468`, the
  run card held at y=112 while the first section moved to y=-234.
- **Overlay (1100):** panel 288, scroller 287 with no scrollbar while content
  fits, scrim 988 wide starting at x=64. The scrim closed the panel and the
  centre stayed 988.
- **Overlay (900):** rail floats at x=0, scrim spans all 900, panel still 288.
- **Reveal:** from `scrollTop=500`, pressing a plan row scrolled the transcript
  back to the writer call at overlay width, closed the panel and removed the
  scrim. At 1400 the panel stayed docked and the transcript scrolled.
- The 7-row plan's `2/7` head, `+2 more`, and the 7-call feed's `View all 7`
  were all read from the live page, not inferred from props.

---

## Deliberate deviations from the plan

1. **The pane is an accordion, not four stacked cards.** The plan lists four
   sections; at 288px, stacking them puts the plan, the feed and the files in
   one long scroll and none of them in a glance. One open at a time is the same
   information with a decision about which one is the question now.
2. **The meter says `unknown` rather than hiding the row.** Phase 0 allowed
   hiding the token row if no measurement exists. Hiding it makes the feature
   look absent; `unknown`, with no bar and `data-known="false"`, says the
   provider did not report it. Neither shows a zero.
3. **Every plan row reveals the same call.** The plan has no per-row call id —
   a `todo_write` replaces the list whole — so a press takes the reader to the
   most recent writer, which is the call whose result the card is showing. Rows
   are only pressable when that call is in this transcript.
4. **The activity feed can show all of a run.** The plan says the last six; the
   six stay the default, and `View all N` is a press away for the turn that
   needs reading. It is still a glance by default.
5. **The Stop button uses the window's existing `cancel` call.** No new
   protocol and no optimistic state: the turn leaves Working when the core says
   it did, which is the same rule the status pill follows.

---

## Verification

- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1076 tests, 1076 pass** (1043 after Phase 2).
  New suite: `ContextPanel.test.tsx` (30). `activity.test.ts` gained the run
  clock's text and the turn-stamp cases; `App.test` gained the boot read, the
  writer-triggered re-read and the touched-file → Code path.
- `cd app && npm run build` — clean; `dist/` rebuilt.
- `python -m pytest -q` — **1685 passed, 24 skipped, 1 failed**. The failure is
  `tests/integration/test_docker_backend.py::test_start_ping_exec_stop`, which
  cannot reach a Docker daemon on this machine; it is environmental and was
  failing before Phase 3.
- `python scripts/audit_reduced_motion.py` — clean.
- `layout.test.ts`'s transition audit is clean for the new panel. Its first run
  caught the Run card's four state colours repainting with no transition; the
  card now transitions `color` with the rest of the pane.

No screenshots were captured: the gates above are measurements, and visual
review is the user's.

---

## What is not here yet (Phases 4–7)

- Run spine, tool-row rewrite and inline approval cards (Phase 4).
- Code-mode explorer/assistant unification; the nav's Explorer/Chats tabs
  (Phase 5).
- Signal hue, opaque docks' final material, display type and motion (Phase 6).
- Screenshots, README and `NEXT_SESSION.md` updates (Phase 7).

## Files touched

```
app/src/App.tsx
app/src/events.ts
app/src/activity.ts
app/src/ContextPanel.tsx             (new)
app/src/RunCard.tsx                  (new)
app/src/PlanCard.tsx                 (new)
app/src/ActivityFeed.tsx             (new)
app/src/FilesTouched.tsx             (new)
app/src/styles.css
app/src/styles/context.css           (new)
app/src/App.test.tsx
app/src/ContextPanel.test.tsx        (new)
app/src/activity.test.ts
design/AGENT_WORKSPACE_REFINE.md
design/PHASE_3_HANDOFF.md            (new)
```
