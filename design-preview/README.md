# design-preview

Where the window is looked at.

- **`index.html`** — the reviewer's entry point. Opens the five baseline
  captures with the numbers each was measured at. Start here.
- **`baseline/`** — 1600×1000, 1400×900, 1100×800, 900×700 and 560×700, taken
  from the built `app/dist` in Chromium over CDP. **Committed.** Re-captured at
  the end of the workspace refine (Phase 7), so they show the finished window —
  run spine, unified Code shell, registry glyphs, signal finish — over a
  replayed turn. Earlier in the pass this folder held the pre-Phase-4
  transcript as the "before"; that record served its purpose once Phase 4
  replaced the surface it photographed.
- **`icons-sheet.png`** — every registry glyph at every size on every surface
  (Phase 8's evidence; regenerable via `scripts/gen_icons_sheet.py`).
- **`archive/`** — the 4 October captures of the retired blue-accent design. Kept
  so a reader can see what changed; not the window any more.

## Taking them again

```
cd app && npm run build
python scripts/capture_window.py --preview --send --out design-preview/baseline
python scripts/capture_window.py --preview --send --measure
```

`--preview` injects `scripts/preview_host.js`, a fake core that answers the boot
requests and replays one turn (prose, a parallel batch, a failure, a nested
subagent, an edit with a diff, a plan). Without it the page renders hostless:
the shell and the launchpad are real, the transcript is empty, and the window
draws its own "no backend" banner.

The rest of this folder — the logo studies, `logos/`, the icon sheets — is brand
work rather than window captures, and stays out of git. Those files are what
`logo/` at the repo root was cut from.
