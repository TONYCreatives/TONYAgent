# Workspace refine — phase status audit, 26 October 2026

Where `design/AGENT_WORKSPACE_REFINE.md` actually stands in the tree, checked
against the code rather than against the handoffs. Written because Phases 0–3
were landed by a previous pass that stopped without committing, so "done" needed
re-establishing from evidence.

## Headline

**Phases 0–3 are in the working tree. Phases 4–7 are not started. Nothing is
committed.** `git log` still ends at `f27125d`, the commit that added the plan
itself; all 2,344 inserted lines across 30 files and 25 new files are
uncommitted.

| Phase | Status | Evidence |
|---|---|---|
| 0 — contract, data, baselines | **done except baselines** | tokens, wireframe, `plan.get` types, turn clock, `activity.ts` |
| 1 — shell, status strip, docks | **done** | grid measured today at 1400 / 1100 / 760 |
| 2 — nav, top bar, launchpad, mode chip | **done, two blocks short** | `ViewSwitch`, `StatusPill`, `Launchpad`, `ModeChip` |
| 3 — context panel | **done except per-turn tokens** | `ContextPanel`, `RunCard`, `PlanCard`, `ActivityFeed`, `FilesTouched` |
| 4 — run spine, tool rows, inline approval | **not started** | no `run-spine`, no gutter, no inline approval, no caret |
| 5 — Code mode unification | **not started** | still `--code-side-w: 268`, `--code-helper-w: 400`, no `AssistantPanel.tsx` |
| 6 — signal, material, display type, motion | **not started** | no `--signal` token; palette still achromatic |
| 7 — docs, screenshots, handoff | **not started** | `NEXT_SESSION.md` last written 22 Oct; `design-preview/` still 4 Oct |

## Phase 0 — contract, data, baselines

Present:

- `--dock-w: var(--list-w)` with `--nav-w`, `--context-w` and
  `--context-w-collapsed: 48px` reading from it (`styles/tokens.css`).
- The six-step ladder 1400 / 1100 / 900 / 720 / 560 / 420, with each step's job
  written beside it.
- `design/workspace-wireframe.html` (boxes at 1400 / 1100 / 900).
- `Plan` / `PlanItem` / `PlanReply` typed in `backend.ts`; `plan.get` read at
  boot, on conversation change and at turn boundaries.
- `turnStartedAt` stamped in `events.ts`; `activity.ts` with `turnActivity()`
  and its unit tests.

Missing:

- **The baselines.** Phase 0 asks for captures at 1600×1000, 1400×900,
  1100×800, 900×700 and 560×700 into `design-preview/`. Every file in
  `design-preview/` is dated 4 October and shows the old blue-accent design.
  Nothing was captured, so there is no "before" to compare the redesign
  against — and the folder now actively misleads, because those images are what
  the README still shows.

## Phase 1 — the three-column shell

Verified by rendering today's build, not by reading the handoff:

| Width | `grid-template-columns` | Centre |
|---:|---|---:|
| 1400 | `288px 824px 288px` | 824 |
| 1100 | `64px 988px 48px` | 988 |
| 760 | `760px` | 760 |

Also present: the status strip as shell row 3 spanning all columns, the nav dock
at 1101+, the context dock at 1400, the one-overlay controller in `App.tsx`
(opening one pane closes the other only where both would be overlays), and the
`.app > .chatlist[data-docked]` state.

Deviation, harmless: the plan names `styles/nav.css`; the implementation put the
nav's rules in `conversation-list.css` and `context.css`. Nothing reads that file
name, so this is a plan/code naming drift, not a missing piece.

## Phase 2 — nav content, top bar, launchpad, mode chip

Present: `ViewSwitch.tsx` (labelled segmented control in the nav head, plus the
railless `RailViewButton` menu form), `StatusPill.tsx`, `Launchpad.tsx` (mark,
wordmark, setup card for what is missing, four prefill-only suggestions, last
three chats), `ModeChip.tsx` (one chip plus popover, replacing the five pills),
the top bar reduced to mark + tabs + track toggle + pill + model + caption,
Trajectory carrying the nav dock, and `relativeTime.ts`.

Missing against §6.2, both deliberate:

- **The project block.** The nav has a folder row that opens the picker and
  nothing else: no branch, no recent files (max 3). Branch is not on the wire,
  so this needs a data decision before it can be built.
- **The skills block.** The nav has a `Skills` row that writes `/` into the
  composer. The plan's version shows a count and a `Manage` control into
  Settings. The row is the more useful half; the count is not there.

Also short of the plan, and already recorded as a Phase 2 deviation: Search
stayed in the nav's foot rather than becoming a row under the switch, `New chat`
is a row rather than a 40px accent button, and there is no `NavDock.tsx` — the
dock is assembled from `ConversationList` plus the rail's foot inside `App.tsx`.

## Phase 3 — context panel

Present and working: the 48px strip at every width below 1400, the docked 288px
column at 1400, the overlay form with a scrim that dims only the centre, the
sticky Run card with its three honest meter states, the Plan / Activity / Files
accordion, `aria-live` only on the run sentence, and the boot / turn-boundary
reads for `plan.get` and `context.get`.

Missing against §6.6 and the phase's own exit gate:

- **Per-turn tokens.** There is no `turn.usage` event and no `usage.turn` RPC in
  the tree — `grep` finds neither. The Run card can therefore show the context
  meter only when the core reports a window, and never shows in/out for the
  turn. The phase's exit gate ("correct during a live turn") is met for state,
  plan, activity and files, and unmet for tokens.
- The status strip's token count and context percentage (§6.7) depend on the
  same missing event, so the strip reports connection, provider and sandbox
  only.

## Phases 4–7 — nothing in the tree

- **Phase 4:** no run spine, no agent gutter in the 22px air, no tool-row
  rewrite, no inline approval card above the composer, no streaming caret, and
  the error banner does not link to Diagnostics. Tool calls are still the flat
  cards they were before this pass.
- **Phase 5:** Code still uses its own row — `268px` explorer, editor,
  `400px` assistant — and there is no `AssistantPanel.tsx`. The context panel is
  not rendered in Code.
- **Phase 6:** `--signal` does not exist. The palette is the achromatic ladder
  plus white accent, so the working state has no colour of its own, the docks
  are not yet given their final material, and the display type steps
  (`--text-2xl`, `--text-display`) are absent.
- **Phase 7:** `NEXT_SESSION.md` (22 Oct) predates every phase; the README still
  describes and shows the old design; no screenshots were captured at any point
  in the pass. The plan's own handoff rule — "screenshots committed, handoff
  current" — is unmet.

## Test state today

- `tsc --noEmit` — clean.
- `npm test` — **1076 tests, 1074 pass, 1 cancelled**. The cancelled one is the
  transition audit in `layout.test.ts` ("no interactive state repaints itself in
  a single frame"), cancelled at 40 ms under full-suite concurrency; it passes
  in isolation in 372 ms. Flaky under load, not a failing assertion.
- `python scripts/audit_reduced_motion.py` — clean.
- Python suite not re-run here; the previous handoffs record 1685 passed,
  24 skipped, 1 environmental Docker failure.

## What has to happen next, in order

1. **Commit Phases 0–3.** 2,344 lines and 25 new files are one `git clean`
   away from gone, and the last three handoffs are untracked too.
2. **Decide per-turn usage.** Either a `turn.usage` event from the core or a
   `usage.turn` RPC; until one exists the Run card's token row and the strip's
   token count cannot be finished. This is the only unfinished item inside
   Phases 0–3.
3. **Phase 4.** The transcript is now the least finished surface in the window,
   and the run panel beside it reports on work the transcript draws flat.
4. **Phase 5**, then **Phase 7** (screenshots, README, `NEXT_SESSION.md`, and
   removing the 4 October captures from `design-preview/`), and **Phase 6**
   last — polish is the cheapest thing to redo and the most expensive to redo
   twice.
5. Optional, small: the project block needs a branch source before it can be
   built; the skills block needs a count from `list_skills`.
