/**
 * The window's only icon module.
 *
 * Every interface glyph lives here, in one registry, drawn on one grid: a
 * 24-unit frame with 1.5 units of padding, strokes centred on whole or half
 * units, 1-unit corner radius, angles at 0/45/90 degrees. Call sites say
 * `<Icon name size />` and get the frame, the weight and `currentColor` for
 * free -- which is what stops the next glyph from arriving with its own
 * numbers, the way thirty-odd ad-hoc svgs did before this module.
 *
 * **One drawn weight.** What matters is the pixel on screen, not the number in
 * the frame: `drawn = strokeWidth * size / 24`. The window used to draw
 * 0.97-1.67px across one frame (a 72% spread between two icons side by side);
 * every entry here draws **1.5px within ±0.1** at every size, via the table
 * below. That is a *constant absolute* policy: a 12px close draws the same
 * 1.5px as a 20px rail icon, so small glyphs carry relatively more ink. The
 * alternative -- scaling the stroke with the box, so a 12px icon draws ~1px
 * -- was rejected on the sheet (`design-preview/icons-sheet.png`): at 1.0px a
 * close on `--bg` is a grey smudge, while 1.5px holds at 100% and stays calm
 * at 200%. The 20px rail moves 1.67 to 1.5 with it; no box measurement depends
 * on a stroke width, so the earlier phases' numbers stand.
 *
 * **Two families, declared.** Stroked is action, control or object in a row.
 * Solid holds exactly two transport marks -- `stop` and `menu` -- and the
 * reason is written on each: at 12px a stroked ring the size of a menu dot is
 * a blob, and a 12-unit outlined square reads as a checkbox rather than as
 * stop. Everything else that was solid is stroked here, including the gear:
 * its old filled form is gone deliberately (see `gear` below), and the
 * launchpad's second folder geometry is unified into `folder`.
 *
 * **Four sizes.** 12, 14, 16 and 20. The type enforces it: a fifth size is a
 * type error, not a review comment. The 10-unit caption set in
 * `WindowControls.tsx` is the OS's own and stays out of this module.
 *
 * **One colour.** `currentColor`, inherited. Disabled is inherited opacity,
 * never a second grey. No icon carries a fill of its own.
 *
 * **Names are concepts.** `search`, not `magnifier`; `close`, not `x`. One
 * name per concept, no aliases: the folder the launchpad drew differently is
 * `folder` here, and the three closes, three pluses, two searches and two
 * back chevrons the tree used to define separately are one entry each.
 *
 * The only other files allowed to draw `<svg>` are `AppMark.tsx` (the app's
 * mark), `petcard.tsx` (the pet) and `WindowControls.tsx` (the OS caption
 * set) -- each a different kind of object from an interface glyph, each
 * asserted by `icons.test.ts`.
 */

import type { ReactNode } from "react";

/** Every size an interface glyph may be drawn at. Nothing else typechecks. */
export const ICON_SIZES = [12, 14, 16, 20] as const;
export type IconSize = (typeof ICON_SIZES)[number];

/**
 * The drawn weight, in CSS pixels on screen: `strokeWidth * size / 24`.
 * Asserted within ±0.1 by `icons.test.ts` and drawn on the sheet beside it.
 */
export const DRAWN_WEIGHT = 1.5;

/**
 * Frame stroke per size for the weight above: 1.5 * 24 / size, to two places.
 * 12 draws 1.500, 14 draws 1.499, 16 and 20 draw 1.500.
 */
export const STROKE_FOR_SIZE: Record<IconSize, number> = {
  12: 3.0,
  14: 2.57,
  16: 2.25,
  20: 1.8,
};

export type IconName =
  | "search"
  | "close"
  | "plus"
  | "back"
  | "folder"
  | "file"
  | "eye"
  | "eyeOff"
  | "trash"
  | "send"
  | "agent"
  | "code"
  | "trajectory"
  | "usage"
  | "pet"
  | "dockOpen"
  | "dockClosed"
  | "assistantOpen"
  | "assistantClosed"
  | "forward"
  | "gear"
  | "stop"
  | "menu";

/** The two solid marks. Everything else is a stroked frame (see above). */
const SOLID: ReadonlySet<IconName> = new Set(["stop", "menu"]);

/** The eye's outline and pupil, shared by `eye` and `eyeOff` so the geometry is written once. */
const EYE_OUTLINE = <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z" />;
const EYE_PUPIL = <circle cx="12" cy="12" r="2.6" />;

/**
 * One glyph per concept, as bare shapes: no `svg`, no size, no stroke, no
 * colour. The frame below owns all four, so a body cannot drift from it.
 */
const BODIES: Record<IconName, ReactNode> = {
  search: <path d="M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  back: <path d="M15 18l-6-6 6-6" />,
  folder: (
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </>
  ),
  eye: (
    <>
      {EYE_OUTLINE}
      {EYE_PUPIL}
    </>
  ),
  eyeOff: (
    <>
      {EYE_OUTLINE}
      {EYE_PUPIL}
      <path d="M4 4l16 16" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M9 7V5h6v2" />
      <path d="M6.5 7l1 13h9l1-13" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  send: (
    <>
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </>
  ),
  agent: (
    <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  ),
  code: <path d="M9 8l-5 4 5 4M15 8l5 4-5 4" />,
  trajectory: <path d="M3 12h3l2-6 3.5 12L15 10l2 2h4" />,
  usage: <path d="M4 20h16M8 20v-7M12 20v-12M16 20v-4" />,
  // The app's own T, with eyes: the two `h.01` ticks are dots -- the round
  // linecap turns a zero-length segment into one -- sitting above the crossbar.
  pet: <path d="M9 5h.01M15 5h.01M6 9h12M12 9v10" />,
  // The nav dock's state glyph: the divider sits where the dock does.
  dockOpen: <path d="M3 4v16M9 4h12v16H9z" />,
  dockClosed: <path d="M21 4v16M15 4H3v16h12z" />,
  // The assistant's own pair, kept distinct from the dock's: the rail's toggle
  // names the left edge and this one the right, and one drawing cannot name
  // both. A frame with a divider: on the right while shown, against the edge
  // once put away.
  assistantOpen: <path d="M3 4h18v16H3zM15 4v16" />,
  assistantClosed: <path d="M3 4h18v16H3zM19 4v16" />,
  forward: <path d="M5 12h14M13 6l6 6-6 6" />,
  /*
   * Stroked, where it used to be solid -- and the history is why this comment
   * is long. It began as two concentric circles with eight radial ticks and
   * read as a sun; it was redrawn as one continuous outline and still read as
   * brightness at 17px; filling the silhouette settled it. What the filled
   * form proved is that the teeth must be *part of the edge*, not ticks beside
   * a ring -- and that property survives stroking: this is the same one-path
   * cog outline, teeth joined to the body, with the hub as its second subpath
   * rather than a circle drawn on top. At the 16/20 it is drawn at (never 12:
   * no call site asks for it there) the teeth clear the 2-unit minimum, which
   * the sheet confirms at 100% and 200%.
   */
  gear: (
    <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
  ),
  /*
   * A transport mark, not an action in a row: the button that stops what is
   * happening, always beside the send position it replaces. A 12-unit outlined
   * square reads as a checkbox; the filled square is what says stop, and it is
   * the same mark in the composer and on the rail.
   */
  stop: <rect x="6" y="6" width="12" height="12" rx="1.5" />,
  /*
   * Three filled dots: at 12px a stroked ring this size is a blob with a hole
   * that never opens, so the honest drawing is the dot itself. The row's menu,
   * never a second meaning.
   */
  menu: (
    <>
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </>
  ),
};

interface IconProps {
  name: IconName;
  size: IconSize;
  className?: string;
}

/**
 * One glyph, in the registry's frame.
 *
 * Decorative wherever it sits: every call site names its own control, so the
 * svg is `aria-hidden` and unfocusable. Colour is inherited `currentColor`;
 * a disabled control fades by opacity, never by a second grey.
 */
export function Icon({ name, size, className }: IconProps) {
  const solid = SOLID.has(name);
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={solid ? "currentColor" : "none"}
      stroke={solid ? "none" : "currentColor"}
      strokeWidth={solid ? undefined : STROKE_FOR_SIZE[size]}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {BODIES[name]}
    </svg>
  );
}
