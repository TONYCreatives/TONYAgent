# Icon drawing manual

The window's glyphs live in one registry, `app/src/icons.tsx`, and this file
is how to draw the next one. The spec is §5.6 of
[AGENT_WORKSPACE_REFINE.md](AGENT_WORKSPACE_REFINE.md); this file is the
workbench copy — the same rules, written as steps.

## The grid

- 24-unit frame, 1.5 units of padding: 21 units of live area.
- Strokes centred on whole or half units. 2-unit minimum between parallel
  strokes. 1-unit corner radius.
- Angles at 0°, 45° or 90°. No 30° lines — at 12px they read as neither
  vertical nor diagonal.

## The weight

One drawn weight: **1.5px** (`drawn = strokeWidth × size / 24`), within ±0.1
at every size. The frame stroke per size:

| size | strokeWidth | draws |
| ---: | ---: | ---: |
| 12 | 3.0 | 1.500 |
| 14 | 2.57 | 1.499 |
| 16 | 2.25 | 1.500 |
| 20 | 1.8 | 1.500 |

This is a *constant absolute* policy: a 12px close draws the same 1.5px as a
20px rail icon. The alternative — scaling the stroke with the box, so 12px
draws ~1px — was rejected on the sheet: at 1.0px a close on `--bg` is a grey
smudge, while 1.5px holds at 100% and stays calm at 200%. See
`design-preview/icons-sheet.png`: the weight-comparison rows (1.0 vs 1.5 at
12px) and the full matrix on `--bg` / `--raised` / `--chip` at 100% and 200%.

Never write a `strokeWidth` at a call site. The type only admits
12 / 14 / 16 / 20, and the registry owns the table.

## The families

- **Stroked** is action, control or object in a row. The default; reach for it
  first.
- **Solid** holds exactly two transport marks, `stop` and `menu`, with the
  reason written on each in the registry: at 12px a stroked ring the size of a
  menu dot is a blob, and a 12-unit outlined square reads as a checkbox rather
  than as stop. A third solid needs its own written reason — "it looks better
  filled" is how the gear regressed twice.
- The gear is the cautionary tale, told in full in the registry: two
  concentric circles with eight ticks reads as a sun; teeth must be *part of
  the edge*. Its stroked form keeps the one-path cog outline and is never
  drawn below 16px, where the teeth clear the 2-unit minimum.

## Names and geometry

- Names are concepts, not pictures: `search`, not `magnifier`; `close`, not
  `x`. One name per concept, no aliases — the folder the launchpad used to
  draw differently is `folder`, and the three closes, three pluses, two
  searches and two back chevrons the tree used to define separately are one
  entry each.
- Bodies are bare shapes: no `svg`, no size, no stroke, no colour. The frame
  owns all four, so a body cannot drift from it.
- One colour: `currentColor`, inherited. Disabled is inherited opacity, never
  a second grey.
- One geometry, two grounds (rule 8 of §5.6) applies to the app's mark, not to
  these: `AppMark.tsx`, `petcard.tsx` and `WindowControls.tsx` are the only
  other files allowed to draw `<svg>`, each a different kind of object from an
  interface glyph.

## Adding an icon

1. Draw it on the grid above, in the registry's `BODIES`, as bare shapes.
2. If it shares subpaths with an entry (like `eyeOff` with `eye`), share the
   constant — `icons.test.ts` forbids duplicated path data, including across
   variants of one concept.
3. Use it as `<Icon name size />`, where `size` is 12 / 14 / 16 / 20. Anything
   else is a type error.
4. Re-run the sheet (`python scripts/gen_icons_sheet.py`) and look at the new
   row at 100% and 200% before committing. The sheet is committed with the
   glyph — it is the review artefact and the thing the next person draws
   against.

## Enforcement

`app/src/icons.test.tsx` renders every entry at every size and asserts the
frame, the declared stroke, `currentColor` and `aria-hidden`; it scans
`app/src/*.tsx` for `<svg` (exactly four files may draw) and for path data
defined twice. A spec nobody can fail is a comment.
