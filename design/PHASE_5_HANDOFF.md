# Workspace refine — Phase 5 handoff

**Landed:** 2026-10-27
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §4.2, §6.6, §9 Phase 5
**Scope:** Code mode's shell only. No core protocol change, no tool semantics,
no mode allow-lists, no viewer behavior.

Phase 5 is in the tree: Code mode is the same three-column shell Agent has —
the explorer in the nav's column at `--dock-w`, the editor in the middle, the
assistant in the context column at 400px. The `code-split` flex row inside
`.main` is gone, and with it the mode's private two-column template.

---

## What shipped

### The unified grid (`styles/shell.css`, `styles/tokens.css`)

- `.app[data-mode="code"]` reads
  `var(--explorer-w) minmax(0, 1fr) var(--helper-w)`, where `--explorer-w` is
  `--dock-w` and `--helper-w` is `--code-helper-w` (400px). Three numbers, three
  columns, one grid — the assistant is a column of the *window* rather than a
  row inside one of its panes.
- `--code-side-w: 268px` is deleted. The explorer used to have a number of its
  own, sized by the longest path; it is `--dock-w` now, and 288 rather than 268
  means no path that fitted yesterday starts truncating today. One dock width
  for the whole window — the `--dock-w: var(--list-w)` alias owns it, never a
  second 288.
- The assistant's put-away state is `--context-w-collapsed` (48px), not
  `--rail-w` (64px). Code's strip used to be a 64px rail while Agent's was a
  48px one, four pixels apart at the same edge of the same window; the assistant
  and the context panel are the same column in two modes, so their compact
  forms are one number.
- This was possible at all because the status strip spans the window since
  Phase 1: the old flex row existed so the bar would stop at the editor's edge,
  and that reason is gone.

### The collapse policy: container query, not window breakpoint

- The assistant floats over the file at `@container (max-width: 1247px)`,
  where 1247 is `--dock-w` (288) + `--code-helper-w` (400) + 560 − 1: at 1248
  the editor is exactly 560 with both panels docked, and one pixel under that
  the assistant keeps its 400px as a cast panel instead of taking a column.
- The query container is `#root`, the shell's parent. A grid *track* is a
  property of the shell, so the query has to be answerable where the shell
  lives — the editor's own `container-type` (see `code-viewer.css`) cannot
  restyle its sibling column, which is why the container is one level up and
  the threshold carries the docks with it. The number derives from the editor's
  560px floor plus the two panels beside it; change either dock's width and it
  changes with them.
- No new `@media` step, so the window ladder stays six. `layout.test.ts`
  asserts `@container 1247` exists and `@media 1247` does not.
- Floated, the assistant keeps its toggle and its shadow and gains no scrim:
  it is the file's companion, and dimming the file to read the question about
  it is the wrong way round.

### The explorer's 900 step (`shell.css`, `App.tsx`)

- Code's explorer is the mode's primary pane and holds its 288 dock down to
  901 — the 1100 Agent nav collapse does not apply here. At 900 it becomes a
  floating 288 panel over the editor, with a 48px `.code-strip` holding its
  toggle in the column it used to fill and a scrim shared with nothing else.
- All three (strip, tree, scrim) render at every width; the stylesheet decides
  which form is live. The tree's *contents* are App state (entries, changes,
  filter), so putting the panel away loses nothing, and a JS branch on the
  window's width would be a second copy of a breakpoint that already exists.
- While the floating panel is open the strip hides itself: two toggles for one
  state is one toggle too many. Choosing a file closes the panel where it is a
  panel (below 900) and changes nothing above, where the tree is a column.

### The assistant as column 3 (`App.tsx`)

- The `.helper` aside moved out of `.main` to after it: nav → centre →
  assistant → context scrim, the same order Agent keeps for its run panel.
  The header stays when the panel is away, so the control that put it away is
  never unmounted with it; what goes away is the body, which is why reopening
  starts at the end of the conversation.
- `data-helper` and `data-explorer` join `data-nav`/`data-context` as shell
  attributes for the same reason: column widths are properties of the grid.
- `code-preview.tsx`'s embedded `@media` copy of the old template now names
  the three tracks, so the design-review page draws the same window.

---

## Measured gates

Read from the built `app/dist` in headless Chrome over CDP with
`scripts/capture_window.py --preview` (the Code button pressed once, then the
five widths resized under the mode):

| Width | `grid-template-columns` | Editor | Assistant / explorer |
|---:|---|---|---|
| 1600 | `288px 912px 400px` | 912 docked | assistant docked 400 |
| 1400 | `288px 712px 400px` | 712 docked | assistant docked 400 |
| 1100 | `288px 812px` | 812 | assistant floated, 400 absolute |
| 900 | `48px 852px` | 852 | explorer floated 288, strip behind it |
| 560 | `48px 512px` | 512 | both floated; no docked pane under 560 |

- **Editor ≥560px whenever the assistant is docked.** The docked range bottoms
  out at 1248 → 560 exactly; at 1247 the container query floats the panel.
- **No file/tree state loss.** Entries, changes, filter, open file and dirty
  buffer all live in App state above the panels; collapsing unmounts the
  assistant's body only, and the tree never unmounts.
- **Tabs stay out of Code.** The rail, conversation overlay and tab strip are
  unmounted in Code mode (asserted in `App.test.tsx`, unchanged).
- **Open-external and read-only unchanged.** `CodeViewer` is untouched; the
  phase moved the panel, not the file.
- `cd app && npm run typecheck` — clean.
- `cd app && npm test` — **1117 pass, 0 fail** (same count as Phase 4; the
  ladder test now pins four `@media` widths plus the 1247 `@container`).
- `python scripts/audit_reduced_motion.py` — clean, including the explorer's
  `slide-in-left` and the scrim's `scrim-in`.
- Python suite — re-run at commit; only the pre-existing Docker daemon failure
  expected.
- `.shots/phase5-code/` holds the five code-mode captures for the record;
  Phase 7 decides what is published.

---

## Deliberate deviations from the plan

1. **No `AssistantPanel.tsx`.** §9 names it as a new file; the implementation
   reuses the existing `.helper` aside and moves it to column 3 instead. A new
   module for a panel that already exists would be a rename for the plan's
   sake, and the moved panel's comments now say what the new file would have.
2. **The container's address.** §7 asks for the query "on the editor"; the
   container is `#root` and the threshold carries the docks (1247 = 288 + 400
   + 560 − 1) instead. A container cannot restyle its own grid track from a
   descendant, so "on the editor" is not an address a track query can have —
   the editor's container styles the header *inside* it (see the 440px rule),
   while the shell's container styles the tracks beside it. The property the
   plan wanted — one threshold derived from the editor's floor, no seventh
   window breakpoint — is what shipped.
3. **The explorer's strip is 48px, like the run panel's, not 64px like the
   rail's.** §6.2's Code tab names Explorer/Chats; the strip says Files and
   holds the tree's toggle. It is the same object as the context strip at the
   other edge, which is why it is the same width.

---

## What is not here yet

- **Phase 8** — the icon system. This phase added one new 14px folder glyph
  and kept the 17px helper toggle; both collapse to the ladder in Phase 8.
- **Phase 6** — signal contrast table, dock material, dot grid, display type,
  motion set, pet presence.
- **Phase 7** — README, screenshots, `NEXT_SESSION.md`, shortcut table.

## Files touched

```
app/src/App.tsx
app/src/code-preview.tsx
app/src/layout.test.ts
app/src/styles/shell.css
app/src/styles/tokens.css
app/src/styles/reduced-motion.css
design/PHASE_5_HANDOFF.md             (new)
```
