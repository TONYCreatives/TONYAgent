# Workspace refine — Phase 4 handoff

**Landed:** 2026-10-26
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §6.3, §9 Phase 4
**Scope:** the transcript, the approval prompt and the error banner. No core
protocol change, no tool semantics, no mode allow-lists.

Phase 4 is in the tree: a turn now reads as work rather than as a log. Every tool
call is one line with a node in the gutter, the calls a turn made are joined by a
1px spine that lives outside the measure, and a permission request is a card
above the composer instead of a dialog over the whole window.

---

## What shipped

### The tool row (`MessageList.tsx`)

- **One line, collapsed.** Status node (gutter), tool name in mono, one-line
  summary, tool budget, measured duration, caret. Pressing the line opens the
  body; pressing it again closes it.
- **The body is opt-in.** Arguments, then Error (red rule) or Diff (line by line,
  added and removed coloured), then Result — and Result is replaced by Diff when
  the core computed one, rather than repeating what the diff already says. Output
  is capped at 4000 characters on the way in, and the cap is stated in the text
  it truncates.
- **A row with no body is not a button.** A call whose tool reported no
  arguments and no output renders its line with `disabled`, because a control
  that does nothing on press is worse than a line that never offered.
- **The duration is the window's clock**, the same `startedAt`/`endedAt` stamps
  the activity feed reads. A running row draws no number at all.
- **The path chip is outside the toggle.** Opening a file in Code and folding a
  row are two acts four pixels apart; one hit area around both would fold the row
  on a press meant for the file. The chip opens the whole path, and carries the
  `+N −N` the core reported.
- **`SubagentWork` is unchanged**, markup and all: the child's rows keep their
  `+ * !` marks and their left rule, because nested work is a different register
  from the parent's spine and the brief says to leave it alone.

### The spine

- A 1px line in the **22px of air outside the measure**, drawn per run of
  consecutive calls. A turn that speaks, calls something, speaks again and calls
  something else gets two segments, which is the shape of what happened; a run of
  one call has no line, because there is nothing to connect.
- Nodes are 8px and sit in the `--column-inset` band, never in the text column.
  Measured: node 8px at x=446, text at x=459, line 1px at x=449 — the line runs
  through the node's centre, and the prose below shares the 459.
- Five statuses: filled `--signal` with a pulse (running), a neutral grey dot
  (done), a red ring with a drawn cross (failed), an amber ring (blocked on a
  person), and a hollow `--border-strong` ring (queued — see the deviations).
- The fill transitions over `--motion-fast`, because a node does change status in
  place while the reader is looking at it.

### The approval card (`ApprovalCard.tsx`, new)

- Above the composer, the column's own box: **measured at 1400 as 760 @ x=440 —
  the composer's box exactly — and its kicker on x=459, the paragraph's first
  character.** Same at 900 (760 @ 78) and 560 (448 @ 64).
- `NEEDS PERMISSION`, the tool name in mono, the call's arguments quoted on one
  line, then `Allow` (accent fill) and `Deny`. A 2px amber rail is the whole of
  the colour: this is the one moment allowed to pull the eye away from signal,
  and a filled amber card would teach people to dismiss these without reading.
- **Enter allows, Escape denies**, with capture and stopPropagation — the same
  guard the modal keeps. Enter is left alone inside a text field and inside the
  card's own buttons, so it cannot answer the opposite of the button under the
  finger.
- The `useAnswerOnce` hook now owns "answer exactly once" for both surfaces.

### The modal, narrowed

- `ConfirmDialog` is mounted only for `destructive: true`. Everything else is the
  card. The modal's own rules — deny by default, Escape denies, a click outside
  does nothing — are unchanged, because that is the one prompt where a misclick
  has consequences.

### The streaming caret (`MarkdownText.tsx`)

- 2px of `--signal` inside the last paragraph of the last prose run, blinking on
  `steps(1)`. Absent when the turn is between passes (a caret under finished
  prose claims the model is writing) and absent while a prompt is up (the pill
  says Waiting; the caret would say the opposite).

### The banner's way out (`App.tsx`)

- The error banner is a row now: message, then a `Diagnostics` link that opens
  Settings on the App tab, where providers, keys, sandbox and the log folder are.
  The banner used to name a failure and leave the reader to find the page.

---

## Measured gates

Read from the built `app/dist` in headless Chrome over CDP, with
`scripts/preview_host.js` replaying a seven-call turn (parallel batch, a failure,
a nested subagent, an edit with a diff):

| Width | Composer | Approval card | Kicker x | Paragraph x | Node x | Line |
|---:|---|---|---:|---:|---:|---|
| 1400×900 | 760 @ 440 | **760 @ 440** | 459 | 459 | 446 | 1px @ 449, h=208 |
| 900×700 | 760 @ 78 | **760 @ 78** | 97 | 97 | — | — |
| 560×700 | 448 @ 64 | **448 @ 64** | 83 | 83 | — | — |

- **Alignment holds.** `--measure` 760, `--column-inset` 19, `--topbar-h` 52,
  `--statusbar-h` 26, `--text-base` 13 — all unchanged; `layout.test.ts`'
  alignment block still passes.
- **The spine is outside the text column.** Node 446..454, line 449, text 459.
  Nothing in the transcript moved 1px right to make room for it.
- **Row height 22** (25 with the 3px run gap), which is what the spine's
  `top: 10px; bottom: 10px` is measured against: the line spans 208 of the run's
  228, from the first node's centre to the last.
- **No grid track changed.** Phase 4 touched the centre only.
- `cd app && npm test` — **1117 tests, 1117 pass** (1091 before this commit).
  New: `ApprovalCard.test.tsx` (7), and 18 in `MessageList.test.tsx` /
  `App.test.tsx` covering the row, the body, the chip, the spine's five statuses,
  the caret's three absences and the two prompt surfaces.
- `python -m pytest -q` — 1687 passed, 22 skipped, 6 failed. The six are
  environmental and pre-existing: the Docker daemon, two terminal-colour tests
  (`TERM=dumb` in this shell), a Windows symlink case, and two headless-core tests
  that cannot open `%APPDATA%\TONYAgent\logs\tonyagent_2026-10-26.log` because the
  installed app is running and holds it. None is in a file this commit touches.
- `python scripts/audit_reduced_motion.py` — clean, including the two new
  animations (`spine-pulse`, `caret-blink`).
- `layout.test.ts`'s repaint audit is clean. Its first run caught three real
  omissions — the banner link's opacity, the node's fill, and the error block —
  which are now transitions; two structural selectors (`data-spine`,
  `data-tone`) were added to the deliberate-instant list with their reasons.

The committed `design-preview/baseline/` images predate this phase and are left
as they are: they are the "before" for Phase 4–7, and re-capturing them would
erase the only record of the transcript this phase replaced. Phase 7 decides what
the published screenshots become.

---

## Deliberate deviations from the plan

1. **No `Always` on the approval card.** §6.4 asks for `Allow / Always / Deny`.
   The wire takes a boolean — `confirm.respond {id, confirmed}` — and the
   permission ladder has no scope to grant. A third button would have been a
   promise this window cannot keep, and teaching the core a scope is a change to
   the permission model, which the brief forbids for this phase.
2. **No queued node in practice.** §6.3 lists a hollow ring for pending calls.
   The rule exists (`.tool-node`'s base fill is exactly that ring), but nothing
   ever renders in it: the core emits `tool.started` when a call begins, so a row
   that has not started does not exist. A pending *call* would need a
   `tool.queued` event, which is protocol rather than design.
3. **The amber node covers every running row, not one call.** The confirmation
   payload carries the prompt's own id, not the call id it belongs to, so the
   window cannot say which running row is the blocked one. Marking all of them is
   the honest reading: the turn is blocked, whatever each call was doing.
4. **`--signal` landed here, not in Phase 6.** The spine's live node and the
   caret are the first things that need the hue, and a white "live" node is the
   confusion the token exists to prevent. Phase 6 still owns the contrast table's
   assertions and the rest of the family's uses; the four values here are the
   plan's own, unchanged.
5. **The caret is suppressed while a prompt is up.** Not in the plan, and the
   reason it is a rule rather than an omission: `busy` is true while the core is
   blocked, so the naive test drew a blinking caret under prose that had finished
   arriving, in the same frame the pill said Waiting.
6. **Two additions to the layout audit's instant-on-purpose list.**
   `[data-spine]` and `[data-tone]` are discriminators chosen at render, not
   states the element transitions between; requiring an animation for them would
   have meant two transitions that can never run.

---

## What is not here yet

- **Phase 5** — Code mode: explorer into the nav dock at `--dock-w`, assistant
  into the context column, the container-query collapse.
- **Phase 6** — the signal family's contrast table, opaque docks' final material,
  the launchpad dot grid, the two display type steps, the full motion set, and the
  pet as the status orb's presence.
- **Phase 7** — README, screenshots, `NEXT_SESSION.md`, and the shortcut table
  that currently documents five bindings that do not exist.
- The rail's Settings button is still `disabled: !connected`, so the page that
  explains a missing key is unreachable in exactly the state that needs it. Folded
  in "whenever it fits"; it did not.

## Files touched

```
app/src/MessageList.tsx
app/src/MarkdownText.tsx
app/src/events.ts
app/src/App.tsx
app/src/ConfirmDialog.tsx
app/src/ApprovalCard.tsx              (new)
app/src/useAnswerOnce.ts              (new)
app/src/styles.css
app/src/styles/tokens.css
app/src/styles/tool-calls.css
app/src/styles/thinking.css
app/src/styles/markdown.css
app/src/styles/motion.css
app/src/styles/banner-log.css
app/src/styles/reduced-motion.css
app/src/styles/approval.css           (new)
app/src/layout.test.ts
app/src/MessageList.test.tsx
app/src/ApprovalCard.test.tsx         (new)
app/src/App.test.tsx
scripts/capture_window.py             (--press, --ask)
scripts/preview_host.js               (diff in the edit artifact, --ask branch)
design/PHASE_4_HANDOFF.md             (new)
```
