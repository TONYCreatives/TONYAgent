/**
 * The app's own mark: a T, the app's own initial.
 *
 * One component, because it was drawn twice -- once inline in the rail and once
 * in the first-run state -- and two copies of a glyph are how a logo ends up on
 * the taskbar in one shape and in the window in another. `icon.svg` is the
 * third copy and the source both are measured from; `AppMark.test.tsx` compares
 * the geometry against that file rather than against a copy of it here.
 *
 * The two surfaces are the title bar's corner and the first-run state now. The
 * rail had a third, and it was the one that read as a second logo: the mark
 * moved to the corner without the rail's copy leaving with it, so the window
 * drew the same drawing at 22px and again at 32px, 64px apart.
 * `IconRail.test.tsx` asserts that copy stays gone.
 *
 * The glyph is two rects with flat terminals (`rx` 0), and that is a change of
 * construction as well as of shape. The chevron this replaces was drawn as
 * paths with a 72-unit stroke; the mark after that was two stadiums, which
 * tapered: a 132-tall crossbar with `rx` 66 spends half its length rounding, so
 * at 16px the bar arrived as a lozenge rather than a bar. A T has no mitre to
 * blunt and no arm to round off, so the terminals are squares, and the stem
 * went to 204 of 1024 -- 3.19px at 16px -- because it was free while there.
 * `icon.svg` says why at greater length.
 *
 * `MARK_RECTS` therefore carries numbers rather than path data, and the test
 * compares those numbers against the file's `x`/`y`/`width`/`height`/`rx`
 * attributes -- the same agreement the old test made, between the same two
 * files, on the fields that now describe the drawing.
 *
 * The dimensions are the artwork's own: `viewBox 0 0 1024 1024`, a 204-wide
 * stem and a 700-wide crossbar, which is what still reads at the 16px the icon
 * rasterises to. `icon.svg` says why at greater length.
 *
 * Drawn on `currentColor`, never on a literal: the title bar is achromatic by
 * design and the first-run state wants the accent, and `--accent` is read out of
 * the rasterised artwork, so a hex here would not move when the artwork did.
 */

/** One stroke of the mark, as the geometry `icon.svg` draws it. */
export interface MarkRect {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Always 0 -- the terminals are square. Kept so the agreement with `icon.svg` is on all five attributes rather than four of them. */
  rx: number;
}

/**
 * The two strokes of the mark: the crossbar, then the stem.
 *
 * Crossbar first because that is the order they appear in the file, and the
 * test compares the two sequences positionally -- a glyph drawn stem-first
 * would pass a set comparison and fail the real one.
 *
 * The stem starts at y=344, which is exactly where the crossbar ends at
 * y=168 + 176, so the two meet without a seam and without an overlap that
 * would antialias twice.
 */
export const MARK_RECTS: readonly MarkRect[] = [
  { x: 162, y: 168, width: 700, height: 176, rx: 0 },
  { x: 410, y: 344, width: 204, height: 512, rx: 0 },
];

/** One eye of the pet, as its centre and radius in the artwork's units. */
export interface MarkEye {
  cx: number;
  cy: number;
  r: number;
}

/**
 * The pet's two eyes, on the crossbar -- one shared source for the in-app mark,
 * the desktop pet (`petcard.tsx` imports this under its own name) and
 * `icon.svg`.
 *
 * They turn the mark into the app's pet: the crossbar is the head, the stem the
 * body, and these are its face. A single definition, because two are how the
 * window's eyes and the card's end up a pixel apart -- the drift this whole
 * module exists to prevent, applied to the face as well as the strokes.
 *
 * Both sit inside the crossbar (`MARK_RECTS[0]`); `petcard.test.tsx` asserts
 * that holds, since an eye overhanging the head reads as a wink and a wink is
 * not something this pet means. `r` is 52 of 1024 -- 0.8px at the 16px the
 * taskbar shows, so the face survives as two points rather than two blobs and
 * grows with the glyph to a clear pair at the first-run hero.
 */
export const MARK_EYES: readonly MarkEye[] = [
  { cx: 348, cy: 260, r: 52 },
  { cx: 676, cy: 260, r: 52 },
];

/**
 * The size at which the mark grows a face.
 *
 * Below this, `AppMark` draws the two strokes only -- a clean T. The eyes are
 * r=52 of 1024, which is ~1.1px at the 22px the title bar draws and 0.8px at the
 * 16px the taskbar raster shows; at those sizes two dots read as specks on a bar
 * rather than a look, so the face is held back until there is room for it. The
 * taskbar icon (`icon.svg`) is a separate raster that keeps the eyes at every
 * size -- this gate is only about the one component the app draws live.
 *
 * 48px is where an eye becomes a clear ~4.9px circle and the crossbar is wide
 * enough to hold two of them without crowding.
 */
export const MARK_FACE_AT = 48;

/** The canvas the geometry above is expressed in, and `icon.svg`'s viewBox. */
export const MARK_VIEWBOX = 1024;

interface Props {
  /**
   * Width and height in CSS pixels, and the artwork's aspect ratio with it. A
   * surface that scales the mark passes the largest size it will ever take and
   * lets CSS clamp it down, so the drawn size and the rendered one cannot end
   * up describing different marks.
   */
  size?: number;
  className?: string;
}

export function AppMark({ size = 32, className }: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      fill="currentColor"
      // Decorative wherever it sits: the tab beside it in the title bar names the
      // app in text and the first-run state prints the wordmark beside it.
      // `focusable` is the SVG 1.1 spelling of the same thing, and without it a
      // Tab can land here.
      aria-hidden="true"
      focusable="false"
    >
      {MARK_RECTS.map((r) => (
        <rect
          key={`${r.x},${r.y}`}
          x={r.x}
          y={r.y}
          width={r.width}
          height={r.height}
          rx={r.rx}
        />
      ))}
      {/* The pet's eyes: the same `MARK_EYES` the desktop pet and the taskbar
          icon draw, on the crossbar, carved in the surface tone rather than
          `currentColor` so the glyph reads as a face. Drawn only at or above
          `MARK_FACE_AT` -- below it (the 22px title bar) two such eyes are a hair
          each and read as specks on a bar, so the small mark stays a clean T.
          The taskbar icon is a separate raster and keeps its eyes at every size. */}
      {size >= MARK_FACE_AT && (
        <g fill="var(--surface, #202020)">
          {MARK_EYES.map((eye) => (
            <circle key={eye.cx} cx={eye.cx} cy={eye.cy} r={eye.r} />
          ))}
        </g>
      )}
    </svg>
  );
}