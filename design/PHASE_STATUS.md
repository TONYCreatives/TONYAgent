# Workspace refine — phase status, 27 October 2026

Where `design/AGENT_WORKSPACE_REFINE.md` stands in the tree, checked
against the code rather than against the handoffs. Written 26 October because
Phases 0–3 were landed by a previous pass that stopped without committing, so
"done" needed re-establishing from evidence; updated 27 October when Phases
4–8 landed in `d374f9e`, `9b0bd9e`, `8e9b800` and `1f27eb1`.

## Headline

**Phases 0–8 are in the tree and committed.** The three holes the 26 October
audit named are closed: per-turn tokens ride `turn.usage` (Run card renders
in/out, strip shows the turn total, `unknown` where the provider reported
nothing); the nav has its project block (folder, `Change…`, up to three recent
files) and its skills block (count from `list_skills`, `Manage` into
Settings); Phase 0's baselines were captured and re-captured at the end of
the pass. Details per phase live in the handoffs, not here.

| Phase | Status | Evidence |
|---|---|---|
| 0 — contract, data, baselines | done | tokens, wireframe, `plan.get` types, turn clock, `activity.ts`, `design-preview/baseline/` at five widths |
| 1 — shell, status strip, docks | done | grid measured at 1400 / 1101 / 1100 / 901 / 900 |
| 2 — nav, top bar, launchpad, mode chip | done | `ViewSwitch`, `StatusPill`, `Launchpad`, `ModeChip`, project + skills blocks |
| 3 — context panel | done | `ContextPanel`, Run/Plan/Activity/Files, `turn.usage` wiring |
| 4 — run spine, tool rows, inline approval | done | `PHASE_4_HANDOFF.md`: spine in the air gutter, one-line rows, `ApprovalCard` |
| 5 — Code mode unification | done | `PHASE_5_HANDOFF.md`: three-column shell, `@container 1247px` assistant collapse |
| 6 — signal, material, display type, motion | done | `PHASE_6_HANDOFF.md`: breathing orb, dim secondary text, contrast table |
| 7 — docs, screenshots, handoff | done | `PHASE_7_HANDOFF.md`: README, baselines, `NEXT_SESSION.md`, live turn |
| 8 — icon system | done | `PHASE_8_HANDOFF.md`: `icons.tsx`, `ICONS.md`, `icons-sheet.png` |

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

Closed 27 October: `design-preview/baseline/` holds five widths, re-captured
at the end of the pass, so the published captures are the finished window.

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

Closed 27 October: the project block (folder, `Change…`, up to three recent
files — branch is not on the wire and stays omitted) and the skills block
(count from `list_skills`, `Manage` into Settings → App).

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

Closed 27 October: `turn.usage` is on the wire (emitted at turn end, summed
from the turn's requests); the Run card renders in/out and the strip shows the
turn total, `unknown` where the provider reported nothing.

## Phases 4–8 — landed 27 October

- **Phase 4:** run spine in the 22px air gutter, one-line tool rows, inline
  approval card above the composer (modal kept for destructive), streaming
  caret, error banner linking to Diagnostics. See `PHASE_4_HANDOFF.md`.
- **Phase 5:** shell owns all three tracks in both modes; assistant floats at
  `@container 1247px`; explorer docked to 901. See `PHASE_5_HANDOFF.md`.
- **Phase 6:** signal spent (breathing orb, working edges, dim secondary
  text, composer bloom), display type, ambient motion shared with the pet.
  See `PHASE_6_HANDOFF.md`.
- **Phase 7:** README, screenshots, `NEXT_SESSION.md`, live turn. See
  `PHASE_7_HANDOFF.md`.
- **Phase 8:** one registry, one weight, no duplicated paths. See
  `PHASE_8_HANDOFF.md` and `ICONS.md`.

## Test state, 27 October

- `tsc --noEmit` — clean.
- `npm test` — **1215 pass, 0 fail** (was 1076/1074+1 cancelled at the audit;
  the flaky transition audit is green in-suite now).
- `python scripts/audit_reduced_motion.py` — clean.
- Python suite: **1690 passed, 24 skipped, 1 failed** — only the pre-existing
  Docker-daemon integration failure (`test_start_ping_exec_stop`, needs a
  daemon this machine does not run).

## What remains

The refine is done. What the next session should know is in `NEXT_SESSION.md`
("2026-10-27: workspace refine complete"): a hosted-model turn needs a key in
Settings first, and `verify_window.py` opens a real window. Open threads that
predate this pass — the WSL `exclude`/`force` flags, the Tkinter-era
`verify.log` at the repo root, the `custom:` keyring entry with no configured
provider behind it — are untouched on purpose and listed there or in the code
where they live.
