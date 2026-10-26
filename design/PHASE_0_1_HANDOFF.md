# Workspace refine — Phase 0 and Phase 1 handoff

**Landed:** 2026-10-23
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §9, Phases 0–1
**Scope:** the desktop window (`app/`), not the core protocol.

Phase 0 and Phase 1 of Direction B (Mission Control) are in the tree. The core
protocol, tool semantics and the desktop pet are untouched.

---

## What shipped

### Phase 0 — contract, data, baselines

- `--dock-w: var(--list-w)` is the single 288px literal; `--nav-w` and
  `--context-w` read from it. `--context-w-collapsed: 48px` is the new compact
  step. `--topbar-h: 52`, `--statusbar-h: 26`, `--measure: 760` and
  `--text-base: 13` are unchanged.
- The ladder in `tokens.css` now names six steps: **1400, 1100, 900, 720, 560,
  420**, each with its job. 1400 and 1101 are written as `min-width` floors
  because they are the first widths that can hold a dock; `layout.test.ts`
  asserts both the max-width set and the two floors.
- `design/workspace-wireframe.html` is the box-only proof at 1400, 1100, 900 and
  the overlay order.
- `plan.get` is typed in `backend.ts` (`Plan`, `PlanItem`, `PlanReply`). The Run
  pane does not read it yet — Phase 3 owns the Plan card — but the window can
  call it without a second shape.
- `ChatState.turnStartedAt` is set in `turn.started`, cleared on every terminal
  event and on a restore. The Run card's clock reads it; no protocol change.
- `activity.ts` derives the run state, the turn's tool steps, the files touched
  (deduplicated, counts summed), the status counts and elapsed time. Unit tests
  in `activity.test.ts`, including the waiting/error precedence and the
  three-passes-one-file case.

### Phase 1 — the three-column shell

```
topbar (row 1, spans all)
nav 288/64  |  centre minmax(0, 1fr)  |  context 288/48   (row 2)
status strip (row 3, spans all)
```

- `.app` is a three-row grid. The status strip is a direct child of the shell,
  spans `1 / -1`, and therefore no longer stops at the editor's edge in Code
  mode. `StatusBar` moved out of `.main`.
- **Nav dock**: at ≥1101 an open nav is a docked 288px column and the rail is not
  mounted beside it; below 1101 the rail stays and the same panel is the
  existing overlay. In the docked state there is no scrim and no slide
  animation — the panel *is* the column. `ConversationList` carries `docked`.
- **Context dock**: a 48px strip (status orb + vertical RUN) at every width below
  1400; at ≥1400 an open panel is a 288px column. Below 1400 the open panel is a
  288px overlay that leaves the 48px track in place. It is the Run card only:
  orb, state word, live clock, Stop, Open Trajectory.
- **One-overlay controller**: below 1101 and 1400 both panes are overlays, so
  opening either closes the other, and an effect closes the context pane when a
  resize makes both overlays at once. At 1101–1399 the nav is docked and the
  context may open over the centre without closing it.
- **≤900**: the rail and the strip leave the grid and float over the full-width
  centre; the centre reserves only the part of their width the reading column was
  not already holding (`--rail-w - --column-edge` and
  `--context-w-collapsed - --column-edge`), so the  760px column is untouched at 900 and the composer stays 14px clear of both panes.
- Settings keeps its own 196px section nav and single-column template.
  Trajectory keeps its full-window presentation. Code keeps its current
  explorer + editor + assistant row until Phase 5; the context pane is not
  rendered there.

---

## Measured gates

Read from the running page in Chromium at 1400×900, 1101×800, 1100×800,
901×700 and 900×700 with both panes open where the width allows:

| Width | `grid-template-columns` | Centre |
|---:|---|---:|
| 1400 | `288px 824px 288px` | **824** |
| 1101 | `288px 765px 48px` | **765** |
| 1100 | `64px 988px 48px` | **988** |
| 901 | `64px 789px 48px` | **789** |
| 900 | `900px` | **900** |

At 900 the rail is 64 at x=0, the strip 48 at x=852, and the composer is 760 at
x=78 — 14px clear of both. At 720 (the narrow check) the composer is 608 at
x=64, flush with the rail and the strip and not under either; before the reserve
it started at x=32 and the rail painted over its first 32px.

`scripts/verify_window.py` gained `probe_workspace`, which reports the same
geometry from the real WebView2 window. Last run at 1187×765 (the window was
887px tall after the caption area): rows `52px 687px 26px`, columns
`288px 851px 48px`, nav docked at 288, context strip 48, strip parent `.app`
with `1 / -1 / 3`; opening the context pane produced a 288px absolute panel
over an 851px centre, and closing it restored the strip.

---

## Deliberate deviations from the plan

1. **≤900 keeps the column's 760px measure.** The plan's table gives the centre
   the full window at 900 and says the compact forms become overlays. Taken
   literally with no reserve, the 64px rail covered the first 32px of the
   composer at 720. The shell now reserves the strips' widths *minus* the
   column's own air, which preserves the gate's centre number and keeps the text
   clear down to the 640px window minimum.
2. **DOM order is nav → centre → context.** The context pane is rendered after
   `.main`, so the tab sequence follows the visual order rather than reaching the
   right pane before the composer.
3. **The status strip keeps its "Working..." word for now.** Removing it is part
   of Phase 2's status pill, where the live state gets its one home. Phase 1
   moves the strip without changing what it reports.

---

## Verification

- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1013 tests, 1013 pass** (996 before the change).
- `cd app && npm run build` — clean; `dist/` rebuilt.
- `python -m pytest -q` — **1685 passed, 24 skipped, 1 failed**. The failure is
  `tests/integration/test_docker_backend.py::test_start_ping_exec_stop`, which
  cannot reach a Docker daemon on this machine; it is environmental, not
  introduced by this pass.
- `python scripts/audit_reduced_motion.py` — clean (no new animations).
- `python scripts/verify_window.py --no-core` — page mounts, the shell probe
  passes, the sidebar and composer probes pass. The model-menu probes report
  `.modelpicker is not on screen` because the run has no core and no bound
  model; that is the pre-existing `--no-core` state, not a shell regression.

No screenshots were captured: the gates above are measurements, and visual
review is the user's.

---

## What is not here yet (Phases 2–7)

- View switch, New chat and Search inside the nav header; the top bar's status
  pill; the launchpad; the single mode chip (Phase 2).
- Plan / Activity / Files cards and per-turn token counts (Phase 3; `plan.get`
  and `activity.ts` are ready for them; per-turn usage still needs a
  `turn.usage` event).
- Run spine, tool-row rewrite and inline approvals (Phase 4).
- Code-mode explorer/assistant unification (Phase 5).
- Signal hue, opaque docks' final material, display type and motion (Phase 6).
- Screenshots, README and `NEXT_SESSION.md` updates (Phase 7).

## Files touched

```
app/src/App.tsx
app/src/ContextPanel.tsx            (new)
app/src/ConversationList.tsx
app/src/activity.ts                 (new)
app/src/activity.test.ts            (new)
app/src/backend.ts
app/src/events.ts
app/src/useMediaQuery.ts            (new)
app/src/styles.css
app/src/styles/context.css          (new)
app/src/styles/shell.css
app/src/styles/conversation-list.css
app/src/styles/statusbar.css
app/src/styles/tokens.css
app/src/App.test.tsx
app/src/ConversationList.test.tsx
app/src/layout.test.ts
design/workspace-wireframe.html     (new)
scripts/verify_window.py
```
