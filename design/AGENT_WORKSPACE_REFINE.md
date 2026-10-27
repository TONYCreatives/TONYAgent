# TONYAgent — Agent Workspace Refine

**Status:** Phases 0–8 landed (October 2026) — see
[PHASE_0_1_HANDOFF.md](PHASE_0_1_HANDOFF.md), [PHASE_2_HANDOFF.md](PHASE_2_HANDOFF.md),
[PHASE_3_HANDOFF.md](PHASE_3_HANDOFF.md), [PHASE_4_HANDOFF.md](PHASE_4_HANDOFF.md),
[PHASE_5_HANDOFF.md](PHASE_5_HANDOFF.md), [PHASE_6_HANDOFF.md](PHASE_6_HANDOFF.md)
and [PHASE_8_HANDOFF.md](PHASE_8_HANDOFF.md) for what shipped, the measured gates
and the deliberate deviations. The plan below is the record of what was built.
**Phase 8 (the icon system, §5.6) was added 2026-10-26** and ran after Phase 5 and before
Phase 7, because screenshots of glyphs that are about to be redrawn are wasted.
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
   a moving pointer (a dock toggle reflows once, instantly).
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

- **Cost:** ~13–17 working days, phased; Phase 2 is a natural stopping point.
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

Widths: navigation **288px** expanded / **64px** collapsed; context **288px**
expanded / **48px** collapsed. Reading column stays 760px. **Both docks are the
same width on purpose:** at 1400px the centre is exactly 824px, which is the
760px column plus its 22px air and 10px gutter on each side. The status strip
now spans the whole window, not just `.main`.

### 4.2 Panes and behavior

| Pane | ≥1400 | 1101–1399 | 901–1100 | ≤900 |
|---|---|---|---|---|
| Navigation | docked 288 | docked 288 | rail 64 | overlay 288 |
| Context | docked 288 | strip 48 (toggle) | strip 48 (toggle) | overlay 288 |
| Centre | 824 | 765–1063 | 789–988 | full |

The ranges are written so that the **compact state is the named step**, the
same convention the current ladder uses at 720/560/420: at exactly 1400 the
context is docked, at exactly 1100 the nav is a rail, at exactly 900 both
expanded forms are overlays. That avoids a one-pixel disagreement between the
table and the media query.

The rail and the strip **never disappear**: they are the compact forms at every
width. "Overlay" in the table means the *expanded* 288px form is an overlay
rather than a grid track. At ≥1400 the context is a dock; at 1101–1399 it is a
strip that opens an overlay; at 901–1100 the nav is a rail that opens an overlay;
at ≤900 both expanded forms are overlays over the full-width centre. "Docked" in
the table is the default: at ≥1400 the user can still collapse either dock to
its compact form, and expanding it again is a dock toggle because the centre can
afford it. That is a user state, not a breakpoint state.

This is the **Agent** table. Code reaches the same three-column shape in Phase 5;
until then it keeps its current explorer + editor + assistant row, so the new
shell does not ship an empty right-hand column in a mode that has not been
migrated.

- Docked panes have fixed widths; only the centre flexes. Toggling a pane must
  never animate a grid track (that reflows text). The overlay forms slide.
- **Docked panes toggle instantly, and that is a deliberate change from the
  overlay era.** A user who collapses the nav or context is asking for more room;
  the centre reflows once, with no transition on the grid track and with the
  transcript's scroll position preserved. The old "never reflow" rule belongs to
  the overlay and to animated tracks. A docked pane that cannot be collapsed is
  worse than a text column that re-wraps when the user asks it to. At 900 and
  below the overlay forms still slide and never move the text.
- **A collapsed pane opens as a dock only where the dock can fit.** The rail and
  the 48px strip are always present as the compact forms. Their toggle opens the
  288px surface as a *dock* only when the centre stays at or above 760: the nav
  at 1101 and above, the context at 1400 and above. Below those widths the same
  toggle opens the 288px surface as an **overlay**, so the centre never drops to
  565px just because someone asked to see the sidebar. This is the rule that
  makes the 1100 and 1400 steps meaningful rather than decorative.
- The navigation pane is **context-sensitive**:
  - Agent: view switch, New chat, Search, conversation list, project, skills,
    Usage, Settings.
  - Code: view switch, Explorer / Chats tabs, then the file tree.
  - Trajectory: view switch, then the conversation list (you can switch chats
    while reading a run).
  - Usage: stays a **tab** of Agent, not a workspace; the nav shows chats.
  - Settings: the app nav is not rendered. The page keeps its own 196px section
    nav; two simultaneous left navs would be the inconsistency this design is
    trying to remove.
- The context pane is **Agent** (Run / Plan / Activity / Files) in Agent mode,
  the **Assistant** (the same transcript and composer as Agent, in a 400px
  column) in Code mode, and hidden in Settings/Usage/Trajectory. The top-bar
  status pill is still shown **while a turn is running** in those views: there
  it is a compact dot that returns to Agent when clicked, so a long turn cannot
  disappear just because the user opened Settings. It is hidden when idle.
- Whenever both panes would be overlays — at 900 and below, and at 901–1100
  where the nav is a rail and the context is a strip — they share one scrim
  controller: opening one closes the other. Two stacked scrims would dim the
  window twice and make the second panel's edge ambiguous. A docked pane is not
  an overlay; at 1101–1399 the nav can stay docked while the context opens over
  the centre.

### 4.3 Two mode axes

- **Workspace switch** (**nav header**, not the top bar): `Agent | Code |
  Trajectory`, as a proper segmented control with icons and labels. At 64px it
  collapses to **one workspace button showing the current icon** that opens a
  three-item menu, not three stacked icons; the rail has to keep room for New
  chat, Search, Usage, the pet and Settings at a 560px-tall window. Settings is
  the page's own gear/back, and Usage is a tab, so neither is a workspace
  segment.
- **Agent mode** (composer): one chip — `Build ▾` — with a popover listing Chat,
  Build, Plan, Mission, Skills and one sentence each. The chip stays **neutral**:
  a mode is a choice, not a live state, and signal is reserved for the turn.
  The selected mode is carried by the label and the hint line; no five-pill row
  and no second colour vocabulary.
- **Track** (top bar): the existing Chat/Build toggle stays where it is. It is a
  property of the conversation, not of the agent's operating mode; moving it into
  the composer would put two different axes in one row.
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

- Keep the glass, but **do not put it on the two large docked panes**. A
  288×800 `backdrop-filter` is the expensive kind, and WebView2 pays for it on
  every frame that scrolls behind it. Docked nav and context use opaque
  `--chrome` / `--surface`; glass stays on the top bar, the status strip, the
  composer, and the overlays that actually float over content. The material
  contrast then means something: opaque docks, lit edges, floating glass.
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

- **Keep the 13px base and the current body size (14px).** A global type bump is
  a reflow of every control, tab, settings row and tool card; doing it after the
  shell phases would invalidate every measurement and screenshot those phases
  were accepted against. If a 14px base is wanted, it gets its own measured pass
  *before* Phase 1, not during polish.
- Prose stays 14px / 1.6. UI labels 12px / 1.3, metadata 11px / 1.25, code
  12.5px.
- Add two **display** steps only: `--text-2xl: 28px`, `--text-display: 34px`
  for the launchpad headline and the dashboard totals. They are used by one
  surface each, which keeps `layout.test.ts`'s "every step is used" rule honest.
- Headlines: Inter 600, `letter-spacing: -0.015em`.
- Section labels: 11px, 700, uppercase, `letter-spacing: 0.09em`, `--fg-mute`
  (already the panel-head style; reuse it instead of inventing a second).
- Mono is extended from "literal code" to **literal identifiers**: tool names,
  model ids, paths, token counts. Not prose. This is a small, defensible widening
  of the current rule.
- Keep `--measure: 760px`; the text column inside it stays 722px. Code viewer
  keeps its own measure.

### 5.4 Shape and iconography

- Keep the existing radius ladder. Controls stay stadiums; rows stay boxes.
- New icons are drawn in the registry (`app/src/icons.tsx`) at 12/14/16/20 in
  one stroked family — see §5.6 and `design/ICONS.md` for the grid, the weight
  table and the rules that replaced this sentence.
- The navigation pane's sections use a 1px rule + label, not cards. Cards are
  reserved for the context panel's facts (Run, Plan, Activity, Files).

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

### 5.6 Icon system

The mark has a spec; the glyphs do not. `app/icons/icon.svg` and
`logo/tonyagent-logo.svg` carry their geometry as a written contract — same
letter, different ground, and the comment says why the tile goes away for the
logo — while the thirty-odd interface glyphs are drawn ad hoc in whichever
component needed one. This section is the missing spec, and Phase 8 applies it.

**What is there today, measured from `app/src/*.tsx`:**

| | Today |
|---|---|
| `<svg>` elements | 31, across 13 components |
| Sizes | 10, 12, 13, 14, 15, 16, 17, 20 |
| Frame stroke (24-unit box) | 1, 1.7, 1.8, 2 — i.e. **drawn 0.97–1.67px** |
| Conventions | stroked 24-frame · filled silhouette (Gear, mark, folder) · 10-frame caption |
| Shared module | none |
| Duplicated paths | close ×3, plus ×3, folder ×3, search ×2, back chevron ×2 |
| Tests over the set | none; `IconRail.test` pins the gear's *filled* form |

So a 13px glyph beside a 20px one draws 0.97px against 1.67px — a 72% weight
difference between two icons in the same window — and the same shape is defined
three times with no mechanism that keeps the copies equal.

**The rules.**

1. **One module.** `app/src/icons.tsx` exports `<Icon name size />`. Every glyph
   lives in one registry. The only files allowed to draw `<svg>` besides it are
   `AppMark.tsx`, `petcard.tsx` and `WindowControls.tsx`, and each of those is a
   different kind of object: the app's mark, the pet, and the OS caption glyphs.
2. **One grid.** A 24-unit frame with 1.5 units of padding, so 21 units of live
   area. Strokes centred on whole or half units, a 2-unit minimum between
   parallel strokes, 1-unit corner radius, and angles at 0°, 45° or 90° — no
   30° lines, which read as neither vertical nor diagonal at 12px.
3. **One drawn weight.** The number that matters is the one on screen:
   `drawn = strokeWidth × size / 24`. The spread today is 0.97–1.67px and the
   phase collapses it to a single value ±0.1px across all four sizes, expressed
   as a per-size table in the registry and **chosen from evidence**: a sheet at
   12 / 14 / 16 / 20, at 100% and 200%, on `--bg` and `--raised`. Two policies
   are legitimate and the phase picks one and records why — constant absolute
   weight (every icon draws the same 1.4–1.6px, so small glyphs get relatively
   heavier) or constant relative weight (the weight scales with the box, so a
   12px icon draws ~1px). What is not legitimate is four values arriving by
   accident, which is what exists now.
4. **Two families, declared.** **Stroked** means action, control or object in a
   row. **Solid** is reserved for the app's own marks: `AppMark`, the pet, the
   tile. Under that rule the gear — an action, drawn solid today — and the
   launchpad's filled folder both become stroked, or the phase reclassifies them
   in writing. A solid glyph sitting in a row of stroked ones is the specific
   inconsistency this section exists to end.
5. **Four sizes.** 12, 14, 16 and 20 in the 24-unit frame; the 10-unit caption
   set is the OS's own and stays as it is. 13, 15 and 17 disappear.
6. **One colour.** `currentColor` and nothing else. No icon carries a fill
   colour of its own; disabled is inherited opacity, not a second grey.
7. **Names are concepts, not pictures.** `search`, not `magnifier`; `close`, not
   `x`. One name per concept, no aliases, so the registry cannot grow two
   entries for one meaning.
8. **One geometry, two grounds.** The mark's two SVGs are correct and are the
   model: the logo differs from the icon only in tile and ground, and says so.
   The risk is that they drift by comment alone — either derive the raster
   source from the logo at build time, or state which one is the original and
   make the other a generated artefact.
9. **Enforcement, not intention.** `icons.test.ts` renders every registry entry
   and asserts the frame, the declared stroke for its size, `currentColor` and
   `aria-hidden`; a second check scans `app/src/*.tsx` for `<svg` and for
   `width`/`height` outside the ladder, the way `layout.test.ts` scans the
   cascade. A spec nobody can fail is a comment.

---

## 6. Component plan

### 6.1 Top command bar

- **Keep 52px** (`--topbar-h: 52px`). The new 32px controls fit inside it; making
  it 56 would cascade into the tab shape, the sidebar's top, the drag region and
  every vertical measurement for no gain.
- Left: the 64px mark. Tabs start at the rail's right edge, exactly as they do
  today; the docked nav is *below* the bar and does not move the strip.
- Centre: session tabs in the **existing shape** — the bar's full height,
  rounded at the top and square where it meets the bar. The shape is already
  argued in `topbar.css`; turning it into a 34px capsule would make it a chip
  with a different number in it.
  - The existing 12px lead slot carries a 6px status dot (idle/working/approval);
    the title and close glyph stay where they are.
  - A dot is shown only on a **non-active** busy tab; the active turn's state
    belongs to the status pill, not to two places at once.
  - New tab `+` after the strip.
- Right: the existing Chat/Build track toggle, a compact **status pill**
  (`● Working · read_file`), model chip, caption buttons. The status pill opens
  the context panel if it is collapsed. In Settings/Usage/Trajectory, a running
  turn keeps a compact dot that returns to Agent; when idle, it is not rendered
  there because there is no panel to open.
- Search: the nav's search row opens the existing SearchPanel. A `⌘K` ghost
  button can join the strip later; it is not part of Phase 1.
- No duplicate mode pills here. The agent mode lives in the composer.

### 6.2 Left navigation dock

- **288px wide**, opaque `--chrome`, 16px inset (`--pad-panel`). It matches the
  conversation list's existing width so titles keep the line length the current
  design was measured for; 248 would truncate them a character early, which is
  the one thing `--list-w` was widened to prevent.
- Header: the `Agent | Code | Trajectory` view switch, then `+ New chat`
  (full-width, 40px, accent fill, black ink) and a search row. At 64px the switch
  becomes one current-workspace button opening a menu; the labels go.
- Conversation list: reuse `ConversationList` internals — date groups, row menu,
  rename, duplicate, delete, filter. The overlay/scrim behavior goes away only
  where the nav is docked (1101 and above in Agent). Between 901 and 1100 the
  rail's expanded form is an overlay; at 900 and below that overlay is the
  default expanded form. The rail itself stays underneath in both cases.
- Project block: folder name, `Change…`, branch if available, recent files (max
  3). Clicking a file opens Code at that file.
- Skills block: count + `Manage` (opens Settings → Skills).
- Foot: Usage, Settings, pet toggle. The rail's actions move here when docked;
  the 64px rail remains the collapsed state. **No connection dot here** — the
  telemetry strip already owns connection state, and two dots for one socket is
  exactly the kind of duplicate this pass removes.
- In Code: a two-tab head — `Explorer` / `Chats`. Explorer reuses `FilesPane`;
  Chats reuses the conversation list. This is the one place the two sidebars
  merge, and it removes the current mode-specific left column.
- **The conversation list is the flexible region.** New chat, search, project,
  skills and the foot are fixed; a 700px-tall window scrolls the list, not the
  whole dock. Project and Skills collapse to one line each when the workspace is
  short, so the list never disappears behind chrome.

### 6.3 Centre: transcript

- Keep the 760px reading column and the shared inset.
- User turns: right-aligned capsule, max 560px, `--raised`; same as today.
- Assistant turns: full-width prose, but with an **agent gutter**:
  - The spine lives in the **22px `--column-air` gutter, outside `--measure`**,
    not inside the text column. Put it inside and every message would start 24px
    right of the composer's placeholder, breaking the one alignment this design
    has protected through every pass.
  - The nodes are 8px and overlap the gutter slightly; the line is 1px.
  - Prose and tool rows keep the shared `--column-inset`, so the first character
    of a message still sits on the same pixel as the composer's text.
  - This is where the "agent did work" story is drawn; the text itself stays
    untouched.
- **Run spine**: a 1px vertical line from the first tool step to the last, with
  8px nodes:
  - hollow ring = pending/queued
  - signal dot with pulse = running
  - neutral check = completed (not green; a column of green checks would turn
    success into decoration and compete with the one live node)
  - danger × = failed
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
- Focus: the existing **white** border only; no second focus ring. While a turn
  is running the field gets a low signal glow / 1px signal top edge, because that
  is live state. A focused but idle field stays white; signal does not mean
  "focused".
- Approval card, when pending, sits directly above the field, full column width:
  `Allow` (accent), `Always`, `Deny`, plus the tool name and one-line risk. It
  must not cover the transcript.
- Mode hint line stays below, 11px `--fg-mute`, one sentence.

### 6.5 Centre: launchpad (first run / empty chat)

Replace the centred mark block with a **launchpad** that fits the same column:

```
        ◈  (static white glow, no pulse)
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
- At 720 and below the 2×2 grid becomes one column; the headline is
  `clamp(24px, 4vw, 34px)` so a 560px window does not get a 34px headline over a
  300px column.
- Recent conversations come from the existing list (max 3).
- If no folder is chosen, the first card becomes `Choose a project folder…` and
  the grid collapses to one column.
- If no provider key, a slim setup card appears below the headline with a
  `Open Keys` button (existing `needsProvider` state).
- The dot grid and the **white** accent glow live here, not behind the
  transcript. Signal is reserved for a live turn; an idle launchpad that pulses
  cyan would make the one colour mean "the app is on" instead of "the agent is
  working".
- Reduced motion: the mark is static; there is no launchpad animation after its
  first arrival.

### 6.6 Right context panel — "Agent"

**288px**, opaque `--surface`, collapsed to a 48px strip with a vertical label
and the status orb. It is the same width as the nav on purpose: at 1400px the
centre is then exactly the 824px the reading column needs. (The Code-mode
assistant keeps its 400px, because it holds a composer and the 288px panel does
not; that difference is by role, not a second design.) Three stacked sections:

1. **Run** (top card)
   - status orb + one word: Idle / Working / Waiting / Error.
   - elapsed timer for the current turn.
   - token in/out for the turn (when available) and context percentage.
   - Stop button while working; "Open Trajectory" link.
   - **No model/mode chips.** The top bar's model chip and the composer's mode
     chip are the controls; repeating them here is a third copy of two facts.
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

The panel scrolls as one column; the Run card is sticky at the top while the
rest scrolls under it. Plan, Activity and Files are collapsible, and only one of
them is open by default (Activity while a turn runs, Plan otherwise). A 288px
panel that tries to show all four sections at once is a wall of text, not a
glance.

Data: everything except token counts and plan comes from `events.ts` today.
`plan.get` exists on the wire but is not in the frontend types — phase 0 adds
the type and a `plan.refresh()` call on turn start/finish. Token counts need one
of: a per-turn usage event, or a `usage.turn` RPC; decide in phase 0 (see §8).

### 6.7 Bottom telemetry strip

- **Keep 26px** (`--statusbar-h: 26px`) for this pass; moving it to 30 would
  push the conversation panel, the overlay scrim, the log strip and the rail's
  foot by four pixels for no information gain. Revisit only if the token count
  genuinely does not fit.
- Spans the full window (`grid-row: 3`), glass chrome.
- Left: connection dot + `Connected` / `Offline`.
- Provider / model (click opens the model picker). The top-bar chip is the
  control; the strip repeats the pair as status, and in Code mode it is the only
  copy, because the chip is hidden there.
- Agent mode chip (`Build`).
- Sandbox state (click opens Settings → Sandbox).
- Right: token count for the turn, context %, `Logs` toggle.
- **No second "Working" word here.** The top-bar status pill is the live state;
  the context panel's Run card is the detail. The strip reports the environment,
  not the turn, so a turn start does not light up three surfaces at once.
- At <560, drop the word beside the dot and the sandbox, exactly as today.
- This replaces the current status bar; its existing tests move with it.

### 6.8 Settings, Usage, Trajectory

- **Settings** keeps the full-window page and its own 196px section nav. The app
  nav is **not** rendered here: two left navs would be the inconsistency this
  redesign is meant to remove. Content width stays ~720px; cards get 16px
  insets. The status strip stays, because it reports the environment.
- **Usage** stays a **tab of Agent**, not a workspace. It gets the display type
  step, a 4-up stat row, and a 1px grid. No new charts in this pass.
- **Trajectory** becomes the "deep run" view: the same spine, but full-width with
  filters (tools only / errors / approvals). It keeps the nav dock and hidden
  context panel, so the left edge does not jump. This is where the future canvas
  experiment can live without touching the main window.

### 6.9 Desktop pet

- Phases 1–5: leave it alone.
- Phase 6: make the pet the **same presence** as the status orb. The orb in the
  top bar/context panel is the in-window face; the pet is the out-of-window face.
  Same states, same signal hue, same breathing rhythm. Do not add a second
  character or a second status vocabulary.

---

## 7. Responsive ladder

The current ladder is 720 / 560 / 420 and `layout.test.ts` enforces it. The
three-pane layout needs three more steps. **The numbers are derived, not chosen:**

- **1400** — 288 nav + 288 context + 824 centre = 1400 exactly. The centre is
  the 760px column plus 22px of air and a 10px scrollbar gutter on each side.
  This is the first width at which the full reading column and both docks coexist
  with no compression.
- **1100** — at **1101**, the last width with the nav docked, the centre is
  1101 − 288 − 48 = **765**, still above the 760px column. At 1100 the nav
  collapses to the 64px rail, so the centre jumps to **988**; the breakpoint is
  where the dock stops being able to hold the reading column, not one pixel
  later.
- **900** — at **901**, the last width with the rail + strip, the centre is
  901 − 64 − 48 = **789**. At 900 both nav and context become overlays, so the
  centre is the full **900**. The panes give the conversation its width back at
  the step where their strips would start squeezing it.

| Step | What changes |
|---|---|
| **1400** | context panel docks at 288; nav at 288 |
| **1100** | Agent nav collapses to 64px rail; Code assistant collapses when the editor container falls below 560px |
| **900** | Agent context becomes an overlay; Code explorer becomes an overlay |
| **720** | existing chrome squeeze: tab caps, model chip ellipsis, caption 38px |
| **560** | status drops secondary facts; tab caps floor |
| **420** | tab strip hides; controls that must remain win |

Six steps, each with one job. **The 1100 nav step is Agent-only.** Code's
explorer is primary: it stays docked at 288 down to 901, then becomes an overlay
at 900. What gives way first in Code is the **assistant**, and it does so by a
container query on the editor, not by a window number. `layout.test.ts`'s
media-query guard is updated to this list in the same commit that introduces the
first new query. The container query is the one exception, and it is the same
pattern the code viewer already uses.

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

### 8.1 Layout audit: what the first draft would have broken

The first version of this plan had several numbers that looked fine on paper and
would have produced exactly the kind of inconsistency this app's tests exist to
catch. They are listed here because the fixes are now part of the contract, not
because the first draft is worth preserving.

| # | Tempting choice | What it would have broken | Resolution |
|---|---|---|---|
| 1 | Nav at **248px** | The current `--list-w` is 288 because 248 truncated conversation titles a character early. A docked nav at 248 reintroduces the defect. | Nav **288**. |
| 2 | Context at **320px** with nav 288 | At the 1400 dock point the centre would be 792px, 32px short of the 824px the reading column needs. | Context **288**, symmetric with the nav. |
| 3 | Dock at **1440** | With 288+288 the centre is 864 at 1440, but on a 1400 laptop the context would never dock. The exact fit is 1400. | Dock at **1400**. |
| 4 | Collapse nav at **900** | At 901px the centre would be 901 − 288 − 48 = 565px; at 900 it would be 788px. A one-pixel change would move the conversation 223px. | Nav collapses at **1100**; the last docked width, 1101, still leaves **765px**, and 1100 gives the space back. |
| 5 | Collapse Code's explorer at the same step as Agent's nav | The explorer is Code's primary pane; a 64px rail is not a file tree, and hiding it first removes the mode's reason to exist. | Code's **assistant** collapses first; the explorer becomes an overlay at 900. The assistant uses a **container query** on the editor, not a window number. |
| 6 | Reuse the app nav as Settings' section nav | Two left navs, or the settings nav collapses to icons and stops being a list of words. | Settings hides the app nav and keeps its own 196px section nav. |
| 7 | Treat **Usage** as a workspace | It is a tab today, with a close X and a "Back to chat". Making it a workspace changes what closing a tab means and gives it two homes. | Usage stays a **tab of Agent**. |
| 8 | Show session tabs in Code mode | `TopBar.onSelect` currently returns to Agent; tabs in Code would either switch the workspace or lie about which conversation the assistant shows. | Tabs stay **hidden in Code**; the assistant header gets a conversation switcher later. |
| 9 | Put the view switch, track toggle, tabs, model, status and caption all in the top bar | At 1100px the fixed controls would leave almost no tab strip, and the strip would be the first thing to become unreadable. | View switch moves **into the nav header**; the track toggle stays in the bar. |
| 10 | Raise `--topbar-h` to 56 and `--statusbar-h` to 30 | Both tokens cascade into the tab shape, the sidebar top, the drag region, the chatlist bottom, the log strip and every vertical measurement — for 8px. | Keep **52 / 26** for this pass. |
| 11 | Move the status bar to shell row 3 without auditing overlays | The rail was deliberately full-height; the chatlist, scrim, log strip and confirm/ask overlays all anchor to `bottom: 0` inside `.main`. The strip would overlap or be overlapped. | Phase 1 includes an explicit overlay audit: chatlist, scrim, logstrip, confirmation, question, banner. The token is the one owner. |
| 12 | Put the run spine **inside** the 760px measure | The first character of every message would move 24px right of the composer's placeholder, breaking the one alignment protected through every pass. | Spine lives in the **22px air gutter, outside `--measure`**. |
| 13 | Extend `backdrop-filter` glass to both 288×800 docks | Two large blurred layers over scrolling text are the expensive WebView2 case, and they would make the docks the most expensive surfaces in the app. | Docked panes are **opaque**; glass stays on chrome, the composer and overlays. |
| 14 | Show "Working" in the top bar, the context panel and the status bar | Three live indicators for one fact; the eye cannot tell which one to trust. | Top-bar pill is the **only live state**; context panel is the detail; the strip reports the environment. |
| 15 | Bump the base type from 13 to 14 in Phase 6 | Every earlier phase's measurements and screenshots would be invalidated at the end. | Keep **13px base / 14px body**; add display sizes only. |
| 16 | Ship the context panel before its data exists | Run/Plan/Activity would be decorative cards, which is worse than no panel. | Phase 0 wires `plan.get`, the turn clock and usage, or the card is hidden until Phase 3. |
| 17 | Pin the approval card above the composer without reserving height | It would cover the log strip and the transcript's last line, or push the composer out of the column. | The card is a child of the composer column with `flex: none`; the transcript's viewport shrinks; the log strip stays above the status strip. |
| 18 | Add a 7th breakpoint for Code's assistant | The window ladder would grow for one mode. | Code's split is a **container query** on the editor; the window ladder stays six steps. |
| 19 | Write 288 twice, for the nav and the conversation list | Two numbers that happen to agree are two numbers that will disagree. The existing `--list-w` already owns the conversation-list width. | One literal, `--list-w: 288px`; `--dock-w: var(--list-w)`, and the nav/context widths read from `--dock-w`. The arithmetic 288 + 288 + 824 = 1400 is then one number, not three. |

The rule this table encodes: **a pane's width is set by what it holds, and a
breakpoint is where that pane stops being able to hold it.** Not by a round
number, and not by matching the other mode for its own sake.

---

## 9. Implementation phases (v2)

Each phase is independently shippable and testable. No phase changes core tool
semantics. The gate after each phase is a measurement, not an opinion.

| Phase | Days | What ships | Gate |
|---|---:|---|---|
| **0** | 1–1.5 | tokens, wireframe, data selectors, baselines | no visual change; suites green |
| **1** | 2–3 | 3-column shell, status strip, dock frames | centre 824 at 1400, 765 at 1101, 789 at 901 |
| **2** | 2–3 | nav content, top bar (tabs keep their shape), launchpad, mode chip | every route reachable; first-run path |
| **3** | 2–3 | full context panel | correct live / restored / approval / no provider |
| **4** | 2–3 | run spine, tool rows, inline approval | alignment + child fixture unchanged |
| **5** | 2–3 | Code mode unification | editor ≥560 with assistant docked |
| **6** | 1–2 | signal, material, display type, motion | reduced-motion + contrast + no jank |
| **7** | 1 | docs, screenshots, handoff | green tree, measured at five widths |
| **8** | 1–2 | icon system: one module, one grid, one drawn weight, four sizes | no `<svg>` outside four files; drawn weight within ±0.1px at every size |

### Phase 0 — Contract, data and baselines (1–1.5 days)

**No visible change.**

- Freeze the layout contract in tokens: `--list-w: 288` stays the literal;
  `--dock-w: var(--list-w)` is the alias the nav and context read from;
  `--topbar-h: 52`, `--statusbar-h: 26`, `--measure: 760`, `--text-base: 13`.
  **Do not introduce a second 288.**
- Build a static `design/workspace-wireframe.html` at 1400 / 1100 / 900 widths.
  Boxes only, no colour: it exists to prove the arithmetic and the overlay
  order before a component is touched.
- Add `plan.get` to the frontend protocol types; one `plan.refresh()` on turn
  start/finish.
- Add a client-side turn clock (derived from `turn.started`; no protocol change).
- Decide per-turn usage: prefer a `turn.usage` event over a new RPC. If the
  event is not ready, the Run card hides the token row instead of showing zero.
- Add `activity.ts`: current-turn tool list, files touched, status, elapsed.
  Memoised selectors; the activity feed must not recompute on every token delta.
- Capture baselines at 1600×1000, 1400×900, 1100×800, 900×700, 560×700 into
  `design-preview/` (not `.shots/`).
- **Exit gate:** no visual change; Python 1685 / TypeScript 996 still green; new
  selectors unit-tested; wireframe measured at all three widths.

### Phase 1 — Shell, status strip and dock frame (2–3 days)

**The structural change. This is the highest-risk phase.**

- Three-column grid for **Agent**: nav 288 / centre `minmax(0, 1fr)` / context
  288. Status strip moves to shell row 3 and spans the window. Code keeps its
  current two-column template until Phase 5; the context column is not rendered
  empty there.
- Nav dock 288/64 with the existing conversation list docked on wide screens.
  The rail's expanded form is an overlay at 1100 and below; at 900 and below it
  is the default expanded form. The rail itself never unmounts.
- Context column 288/48 with a **Run card only** (status, elapsed, stop). It is
  functional on day one; Plan/Activity/Files wait for Phase 3.
- One overlay controller: whenever the expanded nav and expanded context would
  both be overlays (901–1100, and 900 and below), opening one closes the other.
  At 1101–1399 the nav is docked, so the context may open over the centre while
  the nav stays.
- Settings keeps its existing **single-column** template and its own 196px
  section nav; the three-column shell is for Agent and Code in this phase.
  Trajectory keeps its current full-window presentation until Phase 2, so Phase 1
  does not invent a nav for a view it has not redesigned.
- Audit every surface that anchors to the bottom: `.chatlist`, `.chatlist-scrim`,
  `.logstrip`, `.modal-backdrop`, `.banner`, the rail foot, the status strip.
- Breakpoints 1400/1100/900 (the rest of the ladder is untouched).
- **Files:** `App.tsx`, `styles/shell.css`, `styles/rail.css`,
  `styles/conversation-list.css`, `styles/statusbar.css`, new `styles/context.css`,
  `styles/nav.css`; `layout.test.ts`, `test_window_host.py` only if bridge
  changes (none expected), `scripts/verify_window.py`.
- **Exit gate (Agent):** at 1400 the centre measures **824**; at 1101 it is
  **765**; at 1100 (nav collapsed) it is **988**; at 901 it is **789**; at 900
  (both overlays) it is **900**. No grid track is transitioned; a dock toggle
  reflows instantly and preserves the transcript's scroll position; an overlay
  toggle moves no text. At 1101 the context toggle opens an overlay, not a dock;
  at 1400 it docks. All existing routes work; keyboard order matches visual
  order; screenshots at five widths.

### Phase 2 — Nav content, top bar and launchpad (2–3 days)

- Move the `Agent | Code | Trajectory` view switch into the nav header. The
  top bar keeps mark, tabs, Chat/Build track toggle, status pill, model and
  caption.
- Docked nav content (**Agent**): New chat, Search, project block, skills block,
  Usage, Settings, pet, connection. Collapsed rail: the same actions as icons.
  Code keeps its current explorer until Phase 5.
- Status pill: Idle / Working / Waiting / Error; opens the context panel when
  collapsed. In views without a panel, a running turn keeps a compact dot that
  returns to Agent; the pill is absent there when idle.
- Launchpad: four prefill-only suggestions, recent chats, setup card for
  missing folder/key/model.
- Composer: one mode chip with a popover, replacing the five-pill row. The
  Chat/Build track toggle stays in the top bar.
- Narrow rules: at 720 the status pill drops the tool name and keeps the state
  word; at 560 it is a dot with a tooltip. The track toggle keeps its two short
  labels but loses padding at 560, and becomes one icon/menu at 420. The view
  switch is already in the overlay nav there, so the top bar has the room.
- Trajectory gains the nav dock here, with the conversation list. Usage remains a
  tab and keeps the nav; Settings still has no app nav.
- **Files:** `TopBar.tsx`, `Composer.tsx`, new `NavDock.tsx`,
  `Launchpad.tsx`, `StatusPill.tsx`; `styles/topbar.css`,
  `styles/composer.css`, `styles/launchpad.css`, `styles/nav.css`.
- **Exit gate:** every current route reachable; no fake suggestion; first-run
  path works with no folder, no key and no model; 900/720 screenshots; the tab
  strip still starts at x=64.

### Phase 3 — Context panel complete (2–3 days)

- Run card detail: status, elapsed, token in/out, context %, stop, Open
  Trajectory. Model and mode stay in the top bar and composer; the card does not
  repeat them.
- Plan card from `plan.get` / `todo_write`: goal, progress, five rows max,
  read-only, click-to-scroll.
- Activity feed: chronological, last six, status/name/summary/duration. `aria-live`
  only on the one-line status, never on every row.
- Files touched: path, +/−, click opens Code at the file, max five.
- **Files:** new `ContextPanel.tsx`, `RunCard.tsx`, `PlanCard.tsx`,
  `ActivityFeed.tsx`, `FilesTouched.tsx`; `activity.ts`, `events.ts`,
  `styles/context.css`; tests.
- **Exit gate:** correct during a live turn, after restore, during an approval,
  with no provider, and with a restored conversation; no duplicate state.

### Phase 4 — Transcript, run spine and approvals (2–3 days)

- Agent gutter + run spine in the 22px air, outside the measure.
- Tool row: status node, mono tool name, one-line summary, duration, chevron;
  expanded result/diff; nested subagent work unchanged.
- Inline approval card above the composer; modal remains for destructive
  confirmation and Enter/Escape parity.
- Streaming caret; the error banner links to Diagnostics.
- **Files:** `MessageList.tsx`, `events.ts`, `styles/transcript.css`,
  `styles/tool-calls.css`, `styles/confirm-modal.css`.
- **Exit gate:** `startedAtChars` ordering unchanged; the captured child-frame
  fixture renders identically; parallel batches, failures, long runs and nested
  subagents keep their shape; composer alignment still measured.

### Phase 5 — Code mode unification (2–3 days)

- Explorer moves into the nav dock at `--dock-w` 288 (from its current
  `--code-side-w` 268; wider, so no path that fits today starts truncating);
  the assistant moves into the context column at its existing 400px. The current
  `code-split` row becomes the shell grid.
- The assistant's collapse is a **container query on the editor**, not a new
  window breakpoint. The explorer becomes an overlay at 900, after the
  assistant has already collapsed. **The 1100 Agent nav collapse does not apply
  here**: Code's explorer is primary and stays docked at 288 down to 901.
  `NavDock` takes its collapse policy from the workspace, not from one global
  media query.
- The assistant header gains the conversation title and a switcher; tabs stay
  out of Code.
- **Files:** `App.tsx`, `styles/shell.css`, `styles/code-viewer.css`,
  `CodeViewer.tsx` only if the container changes, new `AssistantPanel.tsx`.
- **Exit gate:** editor ≥560px whenever the assistant is docked; no file/tree
  state loss when the pane collapses; open-external and read-only behavior
  unchanged; screenshots at 1400/1100/900.

### Phase 6 — Visual polish and motion (1–2 days)

- Signal tokens, opaque docks, lit pane edges, launchpad dot grid/white glow,
  composer running-state bloom, display type, breathing orb while working.
- Only one ambient pulse at a time: the orb breathes; the caret blinks only
  while text streams; the tab dot is static.
- Reduced-motion audit for every new animation; contrast table for signal on
  every surface it lands on; WebView2 scroll performance check.
- **Exit gate:** `audit_reduced_motion.py` clean; `layout.test.ts` contrast
  assertions; no raw hex outside tokens; no dropped frames while a glass overlay
  scrolls over the transcript.

### Phase 7 — Docs and verification (1 day)

- Update README screenshots/feature notes, `NEXT_SESSION.md`, this plan's status.
- Re-run Python 1685 / TypeScript 996 plus the new suites; `verify_window.py`
  measurements at five widths; one live turn with a real provider.
- **Exit gate:** green tree, screenshots committed, handoff current, no
  uncommitted design work.

### Phase 8 — Icon system (1–2 days)

**Runs after Phase 5 and before Phase 7.** Phase 7 captures the screenshots, and
screenshots of glyphs that are about to be redrawn are wasted work. Phase 6's
polish comes after, and takes the weight table as given.

The spec is §5.6; this phase is applying it.

- **Registry.** `app/src/icons.tsx` with `<Icon name size />`, the size-to-stroke
  table, and every glyph in one place. Delete the duplicates: close ×3, plus ×3,
  folder ×3, search ×2, back chevron ×2. Convert `Gear` and the launchpad's
  folder to stroked, or reclassify them in writing; `IconRail.test`'s assertions
  about the gear's filled form change with it.
- **Sizes.** Collapse 10/12/13/14/15/16/17/20 to 12/14/16/20 plus the untouched
  10-unit caption set. The 20px rail icon is the reference the earlier phases
  were measured against: if the chosen weight moves it, re-run and quote every
  measurement that depended on it rather than assuming nothing did.
- **Weight.** Choose the target from the sheet described in §5.6 rule 3, write it
  in the table, and put the reason in the module comment — the rail's own
  comment already argues its 2/20 for the same kind of reason, and that argument
  is the standard to meet.
- **The sheet.** `design-preview/icons-sheet.png`: every icon at every size on
  `--bg`, `--raised` and `--chip`, with the grid and the weight table drawn
  beside it. This is both the review artefact and the thing the next person
  draws against.
- **Assets.** Decide which of `app/icons/icon.svg` and
  `logo/tonyagent-logo.svg` is the original and make the other derived, or state
  in both files that the difference is only the ground. Check whether the
  Tauri-era files in `app/icons/` (`icon.icns`, `128x128@2x.png`) are still
  needed by `packaging/TONYAgent.spec`; if not, remove them rather than shipping
  two rasters of one mark.
- **Docs.** §5.4's icon sentence is replaced by a pointer to §5.6, and
  `design/ICONS.md` is the drawing manual: the grid, the weight table, the two
  families, the naming rule, and the steps to add an icon.
- **Files:** new `icons.tsx`, `icons.test.ts`, `design/ICONS.md`,
  `design-preview/icons-sheet.png`; `IconRail.tsx`, `Gear.tsx`, `Composer.tsx`,
  `TopBar.tsx`, `ConversationList.tsx`, `FileSidebar.tsx`, `Launchpad.tsx`,
  `SettingsPanel.tsx`, `ContextPanel.tsx`, `App.tsx` (glyph call sites only);
  `IconRail.test.tsx`; `styles/*.css` only where an icon's own rule assumed a
  size.
- **Exit gate:** `<svg` appears in exactly four files under `app/src`; no path
  data is defined twice; every icon draws its declared weight within ±0.1px at
  12/14/16/20, measured from the rendered DOM (`stroke-width × size / 24`) and
  confirmed on the sheet; no size outside the ladder; `npm test` green,
  `layout.test.ts` untouched.

**Total:** ~15–19 working days. Phase 2 is a natural stopping point: the new
shell, nav and launchpad are visible and useful, and the context panel can be a
later pass. Direction A would be ~4–5 days; Direction C is not estimated because
it is a different product.

### What must not move

- `--measure: 760`, `--column-inset: 19`; composer and transcript stay one box.
- `--topbar-h: 52`, `--statusbar-h: 26` for this pass.
- `--text-base: 13`; no mid-pass retune.
- Tabs start at x=64; the tab is square where it meets the bar.
- Tool event order (`startedAtChars`), subagent routing by `parent_call_id`,
  and the `PAGE_API` allowlist.
- The code viewer's container query, read-only/locked behavior and palette.
- Settings' own nav and content width.
- The desktop pet's window behavior in phases 0–5.

---

## 10. Test plan

The existing suite is the reason this can be done safely. It stays green
throughout, with deliberate updates only where the design changes.

### Python
- No core changes expected except the optional `turn.usage` event (schema test).
- `tests/unit/test_window_host.py::PAGE_API` changes only if a bridge method is
  added. None planned.
- `scripts/verify_window.py` gains measurements: nav width, context width,
  status strip span, composer state, no transition on grid tracks, and scroll
  position preserved across a dock toggle.

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
- Five screenshots per phase at 1600×1000, 1400×900, 1100×800, 900×700, 560×700.
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
5. **Density regression.** 288px of nav plus 288px of context can crowd a small
   window. The 1100/900 steps give the space back in the order the workspace can
   afford; verify at 1100 and 900, not only at 1600.
6. **Data gaps.** Per-turn tokens and goal are not on the wire today. Phase 0
   must close them or the Run/Plan cards will be decorative. Hiding a card is
   acceptable; showing a fake zero is not.
7. **Code-mode cliff.** The assistant's collapse must be container-driven. If it
   is tied to the window ladder, one pixel can take the editor from 764px to
   413px. Measure the editor, not the window.

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
3. **Navigation:** dock the conversation list on wide screens at 288px
   (recommended) or keep the overlay at every width.
4. **Density:** keep 13px base / 14px body (recommended, avoids a late reflow) or
   schedule a separate measured pass for 14px before Phase 1.
5. **Context panel actions:** read-only summary (recommended for this pass) or
   include approvals and stop controls.
6. **Tabs:** keep the browser-style tab strip, restyled (recommended), or replace
   it with a single session switcher + command palette.
7. **Code mode:** migrate it in Phase 5 (recommended) or leave its current
   two-column layout for a later pass.
8. **Schedule:** all eight phases, or stop after Phase 2 (shell + nav +
   launchpad) and reassess.

---

## 13. Appendix: token delta

```css
/* geometry */
--list-w: 288px;              /* the one literal */
--dock-w: var(--list-w);      /* nav + context read from this */
--nav-w: var(--dock-w);
--context-w: var(--dock-w);
--code-side-w: var(--dock-w); /* Code's explorer joins the same dock */
--nav-w-collapsed: var(--rail-w);
--context-w-collapsed: 48px;
--topbar-h: 52px;             /* unchanged */
--statusbar-h: 26px;          /* unchanged */

/* type */
--text-2xl: 28px;
--text-display: 34px;

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
   overlay behavior remains at 900 and below.
3. Each phase ends with screenshots and a handoff note; you review before the
   next one starts.
4. If Direction B is too much, we stop after Phase 2: the window has the new
   shell, command bar and launchpad, and the context panel remains a later
   addition.
