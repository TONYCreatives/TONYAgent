# Workspace refine — Phase 7 handoff

**Landed:** 2026-10-27
**Plan:** [AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md) §9 Phase 7
**Scope:** docs, screenshots, verification. No product code except the one
comment the window's own audit script needed.

Phase 7 closes the pass: the README describes the window as it is, the plan's
status is current, the baselines show the finished product, the shortcut table
describes real bindings, and every gate re-runs green — including one live
turn against a real provider.

---

## What shipped

### README

- Feature notes rewritten to the finished window: run spine + inline
  approval, three-pane workspace with dock/rail/overlay policy, same-shell
  Code mode with container-query assistant collapse, mode chip + track
  toggle, Trajectory from the run card and Usage as a tab.
- Tool confirmation section: the permission card (`Allow`/`Deny`,
  Enter/Esc parity), modal kept for destructive only. The `[Allow Always]`
  button the ASCII showed never existed.
- Shortcut table replaced: four real bindings (Enter, Shift+Enter, Escape,
  Ctrl/Cmd+S). The five documented before it (Ctrl+N/O/,/Shift+P/Enter) do
  not exist anywhere in the frontend.
- New Screenshots section: 1400px + 900px captures inline, full set + sheet
  linked.

### Baselines and plan status

- `design-preview/baseline/` re-captured at five widths over a replayed turn
  (`--preview --send`): the finished window — spine, unified shell, registry
  glyphs, signal finish. `design-preview/README.md` updated: the folder is the
  "after" now, with the pre-Phase-4 record noted as served.
- `AGENT_WORKSPACE_REFINE.md` status header: Phases 0–8 landed, with handoff
  links. `NEXT_SESSION.md`: new header + a dated entry for the pass.
- `scripts/verify_window.py`: the gear probe's comment updated to the stroked
  form (the probe reports; it does not assert).

### Verification, re-run for this phase

- `cd app && npm run typecheck` — clean. (No product change in this phase.)
- `cd app && npm test` — **1215 pass, 0 fail**.
- `python -m pytest -q` — **1690 passed, 24 skipped, 1 failed**: only the
  pre-existing Docker-daemon integration failure.
- `python scripts/audit_reduced_motion.py` — clean.
- `python scripts/verify_window.py` (real WebView2 window, core up, watchdog
  closes it) — **fully green**: page/bridge suite, tab strip at x=64, stroked
  gear report (`none/currentColor/null/1 path` in the sidebar), foot at the
  panel bottom, shell rows 52/window/26 with the strip spanning the window,
  panel opens/floats/closes below 1400, model menu inside at full and 640px,
  15-request core round trip with the picker filled.
- Headless geometry at five widths (`capture_window.py --preview --send
  --measure`): centre 1264/1064/988/900/560, composer 760/760/760/760/448,
  statusbar full width — the Phase 1/5 numbers, unchanged by Phases 6 and 8.
- **One live turn with a real provider** (`scripts/live_turn_check.py`, new):
  bound `airllm / deepseek-v4.1-flash` in Chat mode, replied `pinecone` to a
  one-word prompt, usage in=429/out=3/reasoning=0. The hosted identity
  (OpenRouter) has no key in this context's keyring, so the turn ran against
  the loopback gateway rather than a hosted model — recorded honestly in
  `NEXT_SESSION.md`, with the harness kept for a keyed re-run.

---

## Deliberate deviations and non-fixes

1. **No hosted-model turn.** The gate says "a real provider", and the loopback
   gateway is one (real HTTP, real streaming, real usage) — but it is not a
   hosted model, and the handoff does not pretend otherwise. A hosted turn
   needs the user to add a key in Settings; nothing in this repo can do that
   step for them, and nothing here invents a key.
2. **The gateway is flaky with synthetic ids.** Two runs returned empty
   content with no usage block before a re-run landed cleanly. The harness
   reads the session record rather than the bus, and the journal says to
   re-run on empty.
3. **`NEXT_SESSION.md` keeps its journal shape.** 6.8k lines of history were
   not rewritten; the header is current and the pass has its dated entry, per
   the phase's "handoff current" gate.

## Files touched

```
README.md
NEXT_SESSION.md
design/AGENT_WORKSPACE_REFINE.md   (status header)
design-preview/README.md
design-preview/baseline/*.png      (re-captured 5 widths)
scripts/verify_window.py           (gear comment)
scripts/live_turn_check.py         (new)
design/PHASE_7_HANDOFF.md          (new)
```
