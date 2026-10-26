# Handoff prompt — workspace refine, from Phase 3.5 to Phase 7

Copy everything between the two markers into a fresh session opened in
`C:\Users\iig2y\Desktop\TONYCreatives\TONYAgent`. The tail of this file, after
the second marker, is the checklist this session (the planning/verification
one) will use to check the result.

---

## BEGIN PROMPT

You are continuing work on TONYAgent, a local-first desktop coding agent: a
Python core owning conversations, tools and permissions, and a React interface
in a `pywebview` window (`WebView2` on Windows). The window talks to the core
over newline-delimited JSON on stdio. The design work you are picking up is a
phased redesign of that window, planned in
`design/AGENT_WORKSPACE_REFINE.md` ("Direction B — Mission Control").

**State at your start:** commit `d14df30`. Phases 0–3 of the plan are landed and
committed (`0e58172`). Phases 4–7 are not started. There are three known holes
inside the "finished" phases, and closing them is your first job.

### Read before you touch anything

1. `design/PHASE_STATUS.md` — the audit of what actually exists, per phase, with
   file-level evidence. Trust it over the phase handoffs, which were written
   from intent and have drifted from the tree before.
2. `design/AGENT_WORKSPACE_REFINE.md` — §4 (target layout), §5 (visual
   language), §6 (component plan), §9 (the phase list and each phase's exit
   gate). Read the section for the phase you are working on twice.
3. `design/PHASE_3_HANDOFF.md` — how the run panel was actually built, and the
   five deliberate deviations from the plan. Those deviations are decisions, not
   accidents; do not "fix" them back.
4. `app/src/App.tsx` — the shell, the overlay controller, the state that drives
   the nav and context panes. It is large; read the module comments first, they
   are the reasoning.
5. `app/src/ContextPanel.tsx`, `RunCard.tsx`, `PlanCard.tsx`, `ActivityFeed.tsx`,
   `FilesTouched.tsx` — the right pane.

### Invariants — do not move these

- `--measure: 760px` and `--column-inset: 19`. The composer and the transcript
  are one box, and their first character sits on the same pixel.
- `--topbar-h: 52`, `--statusbar-h: 26`, `--text-base: 13`. A change here
  invalidates every measurement the earlier phases were accepted against.
- **No transition on a grid track.** A docked pane toggles instantly and the
  centre reflows once; overlay forms slide and move no text.
- The run spine, when you build it, lives in the **22px air gutter outside
  `--measure`**, never inside the text column.
- Docked panes are **opaque**. Glass stays on the top bar, the status strip, the
  composer and the overlays that float.
- **One live state surface**: the top-bar status pill. The Run card is the
  detail; the status strip reports the environment, not the turn.
- One literal for the dock width: `--dock-w: var(--list-w)`. Never a second
  `288px`.
- The composer's mode chip stays neutral. Signal is a state colour, never a
  button fill; `--accent` stays white.

### Work, in this order, one commit each

**1. Close the token hole in Phase 3.** The Run card cannot show in/out for a
turn and the status strip cannot show a token count, because nothing on the wire
carries per-turn usage. `core/usage.py` already records every request
(`UsageRecord`, ledger in `usage.jsonl`) and `usage.summary` exists, but no
per-turn event does. The plan (§8) prefers a `turn.usage` event over a new RPC:
emit it at the end of a turn from the session, with input / output / reasoning
tokens and cost, sum it from the requests that turn made, and type it in
`app/src/events.ts`. `RunCard` renders `in / out` when the numbers are real and
keeps saying `unknown` when the provider reported nothing — never a zero.
`StatusBar` gains the turn's token count per §6.7, shown only once a turn has
run. Gate: a live turn shows real numbers; a provider that omits usage leaves
the row `unknown`; a restored conversation shows no invented numbers.

**2. Close the nav holes in Phase 2.** The plan's §6.2 asks for two blocks the
nav does not have: a **project block** (folder name, `Change…`, branch if the
wire has one, up to three recent files that open in Code) and a **skills block**
(count from `list_skills`, plus `Manage`). If branch is not on the wire, omit it
rather than inventing it — say so in the handoff. Settings has no Skills tab
(its sections are Behavior / Project / Keys / App), so either land `Manage` on
App or drop the control and record why. Gate: at 288px the blocks do not push the
conversation list below the fold in a 700px-tall window, and the 64px rail is
unchanged.

**3. Restore Phase 0's baselines.** Phase 0 asked for captures at 1600×1000,
1400×900, 1100×800, 900×700 and 560×700 into `design-preview/`. They were never
taken. The "before" state is gone, so these are now the baseline for Phases 4–7:
put them in `design-preview/baseline/`. Then deal with the stale images: every
PNG directly in `design-preview/` is from 4 October and shows the old
blue-accent design, and the README still points at that design. Move them to
`design-preview/archive/` or delete them; do not leave a reviewer looking at a
window that no longer exists.

**4. Phase 4 — transcript, run spine, approvals** (§6.3). Agent gutter and run
spine in the 22px air, the tool-row rewrite (status node, mono tool name,
one-line summary, duration, chevron, expanded args/result/diff, nested subagent
work unchanged), the inline approval card above the composer (the modal stays for
destructive confirmation and for Enter/Escape parity), the streaming caret, and
the error banner's link to Diagnostics. Gate: `layout.test.ts` alignment still
passes, the captured child-frame fixture renders identically, and parallel
batches, failures, long runs and nested subagents keep their shape.

**5. Phase 5 — Code mode unification** (§4.2, §6.6). The explorer moves into the
nav dock at `--dock-w` 288 (from `--code-side-w: 268`), the assistant moves into
the context column at its existing 400px, the `code-split` row becomes the shell
grid, and the assistant's collapse becomes a **container query on the editor**,
not a window breakpoint. The 1100 Agent nav collapse does not apply here: Code's
explorer is primary and stays docked to 901. Tabs stay out of Code. Gate: editor
≥560px whenever the assistant is docked; no file or tree state is lost when the
pane collapses; open-external and read-only behaviour unchanged.

**6. Phase 7 — docs, screenshots, handoff — before Phase 6, deliberately.**
README feature notes and screenshots, `NEXT_SESSION.md`, the plan's status
header, and the shortcut table: it currently documents `Ctrl+N`, `Ctrl+O`,
`Ctrl+,`, `Ctrl+Shift+P` and `Ctrl+Enter`, of which **none** exist (the only
modifier binding in the frontend is `Ctrl+S` in the editor, and there is no
command palette). Either implement them or delete the table — a table of keys
that do nothing is worse than no table.

**7. Phase 6 — polish, last** (§5). The `--signal` family with its contrast
table, opaque docks' final material, the launchpad dot grid, the two display
type steps, the motion set, and the pet as the same presence as the status orb.
Gate: `audit_reduced_motion.py` clean, the contrast assertions in
`layout.test.ts` hold, no dropped frames while a glass overlay scrolls.

**Fold in whenever it fits:** the rail's Settings button is
`disabled: !connected`, so the page that explains a missing key, a dead sandbox
or a broken provider is unreachable in exactly the state where you need it.
Ungate it and check what breaks inside when there is no core.

### How to verify

```bash
cd app && npm run typecheck
cd app && npm test                 # compiles to app/.tmp then node --test
cd app && npm run build            # rebuilds app/dist, which the window serves
python -m pytest -q                # 1685 pass, 24 skip, 1 environmental Docker failure
python scripts/audit_reduced_motion.py
python scripts/verify_window.py    # geometry from the real WebView2 window
```

To look at the interface without opening a native window: serve `app/dist` on
loopback and drive headless Chrome over CDP. `scripts/probe_webview.py` already
has the minimal WebSocket client (`_ws_connect`, `_send`, `_recv`); launch Chrome
with `--headless=new --remote-debugging-port=9333`, then use
`Page.captureScreenshot` and `Runtime.evaluate`. The page renders hostless by
design (`bridge.ts` resolves to `null`), so the shell, launchpad and run panel
are real there. Settings and Code are gated on core state, so they need a live
core or a deliberate un-gating to inspect.

### Traps that have already cost time

- The layout transition audit ("no interactive state repaints itself in a single
  frame") gets **cancelled** at ~40ms under full-suite concurrency and passes
  alone in ~370ms. Re-run it before believing it:
  `node --test --test-name-pattern "no interactive state repaints" .tmp/layout.test.js`
- `tests/integration/test_docker_backend.py::test_start_ping_exec_stop` fails
  without a Docker daemon. Environmental, pre-existing.
- Handoff prose has claimed things the tree did not have. Check the tree.
- `.shots/` and `app/.tmp/` and `.workbuddy-ai/` are ignored. Do not commit
  screenshots into `.shots/` and call them documentation; Phase 0 says
  `design-preview/`.

### Rules of engagement

- One commit per numbered item, in the repo's own style: imperative subject line,
  blank line, prose body that says what moved and what was measured. No
  conventional-commit prefixes — the history does not use them.
- Write `design/PHASE_<N>_HANDOFF.md` for each phase: what shipped, the measured
  gates, the deliberate deviations and why, what is not there yet, files touched.
  Match the shape of `PHASE_3_HANDOFF.md`.
- Never change core tool semantics, tool names or the mode allow-lists.
- Report measurements, not opinions. "The centre is 824" beats "the layout looks
  right".
- When you deviate from the plan, say so in the handoff with the reason. Five
  such deviations already exist and were the right call.

### What to report back

A table of item → gate → the number you measured, the commits, the files touched
per item, and an explicit list of anything you chose not to do and why.

## END PROMPT

---

## Verification checklist for the planning session

When the work comes back, check these before accepting it:

1. `git log --oneline` — one commit per item, messages in the repo's voice, no
   squashed "wip".
2. `git status` — clean. No screenshots, `.tmp/`, `node_modules` or
   `.workbuddy-ai/` in the tree.
3. `npm run typecheck`, `npm test`, `npm run build`, `python -m pytest -q`,
   `python scripts/audit_reduced_motion.py` — all green except the known Docker
   test. If the layout audit fails, re-run it alone before accepting the excuse.
4. Re-render at 1400 / 1100 / 900 / 760 and read `grid-template-columns` and the
   composer's rect. 1400 must still be `288px 824px 288px`; 1100 must still be
   `64px 988px 48px`; the composer must still be 760 wide and 14px clear of the
   floating rail at 900.
5. Phase 4: is the spine outside the 760 measure, or did it creep into the text
   column? Does a prose-only answer draw no spine? Does the inline approval card
   reserve its height instead of covering the transcript?
6. Phase 5: with the assistant docked, is the editor still ≥560px? Does
   collapsing the assistant lose the open file or the tree's expansion state?
7. Phase 7: does the README's shortcut table now describe real bindings? Do the
   README screenshots show the window as it is today? Is `NEXT_SESSION.md` newer
   than the last phase commit?
8. Read `design/PHASE_STATUS.md` against the new handoffs: every "not started"
   should now be either done with a gate number or explicitly deferred.
