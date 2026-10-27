# Workspace refine — Phase 8 handoff

**Landed:** 2026-10-27
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §5.6 + §9 Phase 8
**Scope:** the interface glyphs only. No layout, no protocol, no behavior.

Phase 8 is in the tree: every interface glyph lives in one registry,
`app/src/icons.tsx`, as `<Icon name size />`. Thirty-two ad-hoc `<svg>`
blocks across thirteen components are one module; five shapes defined two to
four times (close ×3, plus ×3, folder ×4 counting the launchpad's variant,
search ×2, back chevron ×2) are one entry each; eight sizes are four, and
four frame strokes drawing 0.97–1.67px are one drawn weight.

---

## What shipped

### The registry (`app/src/icons.tsx`, new)

- 23 names, each a concept: `search close plus back folder file eye eyeOff
  trash send agent code trajectory usage pet dockOpen dockClosed
  assistantOpen assistantClosed forward gear stop menu`.
- One grid: 24-unit frame, 1.5 units padding, strokes on whole or half units,
  1-unit radius, 0/45/90° angles.
- One drawn weight: **1.5px absolute** at every size, via the table
  12→3.0, 14→2.57, 16→2.25, 20→1.8. Constant absolute, not constant relative:
  the sheet's 12px comparison (1.0 vs 1.5) shows 1.0 washing out on `--bg`
  while 1.5 holds at 100% and stays calm at 200%. The 20px rail moves 1.67 to
  1.5 with it; no box measurement depends on a stroke width, so the earlier
  phases' numbers stand — confirmed by re-running the headless measurements
  below.
- Two families: stroked for actions, solid for exactly two transport marks
  (`stop`, `menu`), each with its written reason. Everything else that was
  solid is stroked, including the gear (below) and the launchpad's folder
  (unified into `folder`; `FolderIcon` deleted).
- Four sizes, enforced by the type: 12 / 14 / 16 / 20. The 10-unit caption set
  stays the OS's own in `WindowControls.tsx`.
- One colour: inherited `currentColor`. No icon carries a fill of its own.

### The conversions

- **Gear: solid → stroked.** The teeth stay part of the edge — the same
  one-path cog outline, hub as second subpath — which is the property the
  filled form proved and the property stroking preserves. The failure it was
  converted away from (two rings reading as a sun) is asserted against in
  `IconRail.test.tsx` in its stroked form. Never drawn below 16px; the sheet
  confirms the teeth clear the grid at 100% and 200%.
- **Launchpad folder: second geometry → `folder`.** It was already stroked;
  what it was not was the same drawing. Deleted.
- **Stop: two drawings → one mark.** The rail's stroked outline square and the
  composer's filled rounded square were one concept twice. Both are the filled
  `stop` now — the button that interrupts, always beside the send position it
  replaces. `Composer.test.tsx`'s filled-square assertions still pass
  unchanged.
- **Dead weight dropped.** `PATHS.terminal` was defined and never used; it
  does not come along. `Gear.tsx`, `FolderIcon`, `EyeIcon`, `TrashIcon`,
  `DropIcon`, the rail's `glyph()` frame and `PATHS` are deleted with their
  last call sites.
- **Sizes collapsed.** 13→12 (tree, filter, kebab, explorer heads, nav
  folder), 15→14 (attach, send, eye), 17→16 (helper toggle, budget gear).
  Nothing else moves: row heights are text-led, and the suites below confirm
  it.

### Enforcement (`app/src/icons.test.tsx`, new — 97 tests)

- Every entry at every size: 24-frame, declared stroke, `currentColor`,
  `aria-hidden`, and drawn weight within ±0.1px of 1.5, read from the DOM.
- `<svg>` in exactly four files: registry, `AppMark`, `petcard`,
  `WindowControls`. (The test's own source avoids the literal so the gate
  holds literally.)
- No path data defined twice (the eye's outline/pupil are shared constants,
  which is what makes variants legal).
- No width/height outside the ladder and no `strokeWidth` outside the
  registry.

### The sheet and the manual

- `design-preview/icons-sheet.png`: every icon at 12/14/16/20 on `--bg`,
  `--raised` and `--chip`, at 100% and doubled to 200%, plus the 1.0-vs-1.5
  comparison at 12px and old-solid vs new-stroked gear at 16/20.
  Regenerable: `python scripts/gen_icons_sheet.py` (parses the registry, so
  the sheet can never show a glyph the app does not draw). Committed through a
  new `.gitignore` exception: the folder ignores scratch captures, and the
  sheet is evidence, not scratch.
- `design/ICONS.md`: the drawing manual — grid, table, families, naming, and
  the four steps to add an icon.
- §5.4's icon sentence replaced by a pointer to §5.6, as the phase requires.

---

## Measured gates

- `grep -l '<svg' app/src/*.tsx` → **AppMark.tsx, WindowControls.tsx,
  icons.tsx, petcard.tsx. Four files.**
- No path data defined twice — asserted by test, green.
- Every icon within ±0.1px of 1.5 at 12/14/16/20, measured from the rendered
  DOM — asserted by test, green (92 weight assertions).
- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1214 pass, 0 fail** (1117 before + 97 new).
- `layout.test.ts` — **untouched** (`git status` shows no modification).
- Headless re-measurement over the preview host: Agent columns identical to
  the Phase 5 numbers at all five widths (288/1264/48 at 1600, 288/1064/48
  at 1400, 64/988/48 at 1100, full 900, 448 composer at 560) — the weight
  change moved no box. Live-window review at 1400: one coherent family, no
  broken / missing / mismatched glyph.
- Sheet reviewed at 200%: 1.5 clearly more legible than 1.0 at 12px without
  heaviness; stroked gear reads as a gear at 16 and 20; matrix uniform.

---

## Deliberate deviations from the plan

1. **`stop` and `menu` stay solid, in writing.** §5.6 rule 4 reserves solid
   for the app's own marks; the plan's phase body names only the gear and the
   launchpad folder for conversion-or-reclassification. The two survivors are
   reclassified in the registry with reasons a drawing can be checked against:
   at 12px a stroked menu-dot ring is a blob, and an outlined stop square
   reads as a checkbox. A third solid needs its own written reason.
2. **The rail's `rect` guard now names the mark's canvas, not the element.**
   `IconRail.test.tsx` used "no `rect` in the rail" to mean "no mark in the
   rail"; the unified `stop` is a rect, so the guard asserts no 1024-unit
   canvas instead. Same intent, precise address.
3. **`scripts/gen_icons_sheet.py` is an extra file.** The phase lists the
   sheet as an artefact; the generator is committed beside it so the sheet is
   reproducible rather than a one-off PNG.

## What is not here yet

- **Phase 6** — signal tokens, opaque docks, lit pane edges, launchpad dot
  grid, display type, breathing orb (the `--signal` values seeded by Phase 4
  are unchanged by this phase).
- **Phase 7** — README, screenshots, `NEXT_SESSION.md`, shortcut table.
- `app/icons/` + `logo/` asset decision (original vs derived) — carried, as
  the phase body asks, but the rasters are untouched by this commit.

## Files touched

```
app/src/icons.tsx                    (new)
app/src/icons.test.tsx               (new)
app/src/Gear.tsx                     (deleted)
app/src/IconRail.tsx
app/src/IconRail.test.tsx
app/src/ConversationList.tsx
app/src/FileSidebar.tsx
app/src/Composer.tsx
app/src/ContextPanel.tsx
app/src/TopBar.tsx
app/src/Launchpad.tsx
app/src/SettingsPanel.tsx
app/src/App.tsx
app/src/ToolBudgetControl.tsx
scripts/gen_icons_sheet.py           (new)
design/ICONS.md                      (new)
design/icons-sheet: design-preview/icons-sheet.png (new)
design/AGENT_WORKSPACE_REFINE.md     (§5.4 pointer)
design/PHASE_8_HANDOFF.md            (new)
```
