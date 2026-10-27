# Workspace refine — Phase 6 handoff

**Landed:** 2026-10-27
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §5 + §9 Phase 6
**Scope:** the window's finish only — tokens, keyframes, pane edges, the pet's
presence. No layout, no protocol, no behavior.

Phase 6 is in the tree: the signal family from Phase 4 now does the whole job
it was seeded for. The working orb breathes, the composer blooms while a turn
runs, the launchpad has a hero and a field, the dashboard totals are display
type, and the pet is the same presence as the orb. Values seeded by Phase 4
are unchanged — this phase spends them, it does not re-pick them.

---

## What shipped

### Signal, spent (tokens, orb, edges)

- `--signal` and `--signal-dim` keep their values; the token comment now says
  the window is achromatic *except meaning*.
- The run orb and the status pill's orb draw `--signal` while working, on
  `signal-breathe` — one 3.2s ambient loop (`--motion-ambient`, new), shared
  with the pet. Under reduced motion the orb is a still lit dot.
- The run card's working edge and the context dock's inner edge carry 1px of
  signal while a turn runs (`.app[data-run]` is the new shell attribute both
  read, from the same `activity.run` the pill draws). Idle, every edge is the
  same `--border-soft` — a line that never goes out stops being a signal.
  Code's assistant column carries the same line. Both ease in over 110ms, so
  the transition audit holds them.
- Secondary live text is `--signal-dim`'s one job: the pill's tool name (on
  `--chrome`, 5.53:1) and the run card's token numbers (on `--surface`,
  5.95:1), both while working only. `layout.test.ts` pins the two call sites
  as the exact set — small text in dim on a chip (3.97:1) is a pairing the
  test forbids by name.

### Motion, completed

- `signal-breathe` (orb, 3.2s infinite), `node-in` (tool step arrival, 160ms),
  `spine-grow` (run line, 240ms from the top), `pane-reveal` (context overlay,
  240ms). No animation on a grid track: the reveal belongs to the floating
  panel only, and the docked toggle still reflows instantly.
- `node-in` stands aside for live nodes (`:not([data-status="running"])`) —
  a later equal-specificity rule would otherwise still the running pulse, and
  the pulse is already the arrival signal for a mounting live call.
- `audit_reduced_motion.py` clean; all four selectors cancelled in both
  reduced-motion blocks (the orb keeps its fill, the node its place, the spine
  its line, the panel its overlay).

### Launchpad, composer, dashboard

- The empty state carries a 2% white 24px dot grid (`--dot-grid`, new token —
  the colour audit owns every raw colour, so the grid is a token too), masked
  to `.empty` only. The mark's white glow was already there and stays static:
  no pulse on an idle surface.
- The headline takes the display steps: `clamp(var(--text-2xl), 4vw,
  var(--text-display))`, Inter 600, `-0.015em` — 34px on a wide column,
  24px before a narrow one takes it.
- `--text-2xl` (28px) and `--text-display` (34px) are the two steps above the
  20px the app topped out at, used by exactly the two surfaces that are
  dashboards rather than reading: the headline and the usage tiles' totals.
- The composer's running bloom: the white border stays, with 1px of signal
  and 48px of `signal-glow` over the resting shadow (`data-busy` on the
  composer). A focused-but-idle field stays white — signal means live, not
  focused.

### The pet, as the orb's presence

- Working dot in signal, on `--motion-ambient` — the same 3.2s the orb
  breathes. Idle breathing joins it (3.4s → 3200ms): one rhythm in two places.
  Waiting and asleep keep their own.
- No test pinned the old durations or the white dot, so none changes with
  them; the contract is the rhythm and the hue, stated in the stylesheet.

---

## Measured gates

- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1215 pass, 0 fail** (1214 before + shell `data-run`
  assert).
- `python -m pytest -q` — **1690 passed, 24 skipped, 1 failed**: only the
  pre-existing Docker daemon failure.
- `python scripts/audit_reduced_motion.py` — clean, including the four new
  animations.
- Signal contrast asserts in `layout.test.ts`: 11.79 / 8.56 / 7.36 for
  `--signal` on bg/raised/chip; 6.36 / 4.62 / 5.95 / 5.53 for `--signal-dim`
  on bg/raised/surface/chrome; chip pairing forbidden — all green.
- No raw hex outside tokens — the colour audit green (the dot grid is a token
  for exactly this reason).
- Working state, read from the live build in headless Chrome over the preview
  host with motion forced on: `run=working`, orb `signal-breathe 3.2s`, orb
  fill signal, context inner edge signal, composer bloom 1px + 48px glow.
  With the OS preference at reduce: still lit dot, no animation.
- Headline 34px at 1400 (clamp ceiling); dot grid on `.empty` in computed
  style (2% is at the perception threshold on purpose — space, not texture).
- No jank: no transition on any grid track (dock toggles instant, overlays
  slide); the one loop is the orb/pet breath, and it is off under reduced
  motion.

---

## Deliberate deviations from the plan

1. **No new 1px-token.** §5.2's `inset 0 0 0 1px var(--glass-edge)` for the
   active pane arrives as the dock's existing hairline plus the signal line
   while working, not as a second ring: a full ring on a 288px dock reads as a
   website, which is the failure the plan itself names two sentences later.
2. **`signal-dim`'s first uses are pill detail + run tokens, not plan/activity
   rows.** The complete nodes stay neutral grey per Phase 4 (a column of dim
   checks would compete with the one live node); dim carries secondary *live*
   text only, where the 4.5 floor holds.
3. **Composer bloom keeps the white border.** The plan's "plus the existing
   white border" is read literally: signal ring + glow *over* the accent edge,
   so the field never stops saying where typing goes.

## What is not here yet

- **Phase 7** — README, screenshots, `NEXT_SESSION.md`, shortcut table, plan
  status. The `design-preview/baseline/` captures predate this phase; Phase 7
  decides the published set.

## Files touched

```
app/src/styles/tokens.css        (--text-2xl/display, --motion-ambient, --dot-grid)
app/src/styles/motion.css         (signal-breathe, node-in, spine-grow, pane-reveal)
app/src/styles/context.css        (orb signal+breathe, working edges, dim tokens, pane-reveal)
app/src/styles/topbar.css         (pill detail dim)
app/src/styles/composer.css       (running bloom)
app/src/styles/shell.css          (assistant signal edge)
app/src/styles/transcript.css     (dot grid, display headline)
app/src/styles/usage.css          (tile display totals)
app/src/styles/pet.css            (signal dot, ambient rhythm)
app/src/styles/reduced-motion.css (four new cancellations, both blocks)
app/src/Composer.tsx              (data-busy)
app/src/App.tsx                   (data-run on the shell)
app/src/layout.test.ts            (ladder, h1, signal contrast, chroma)
app/src/App.test.tsx              (shell data-run)
design/PHASE_6_HANDOFF.md         (new)
```
