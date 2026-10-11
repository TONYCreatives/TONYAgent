/**
 * The settings gear, drawn once because it is drawn in two places.
 *
 * **Solid, where every other glyph in this app is an outline.** That is a
 * deliberate exception and the reason is the size it is drawn at. A gear's
 * meaning lives in its teeth being joined to its body, and at 17px an outline
 * loses exactly that: the stroke lands at about 1.2px around teeth about 2px
 * wide, so the teeth merge into the ring they sit on and the whole thing reads as
 * a sun or a brightness control.
 *
 * That failure was already known here -- the rail's own comment records the
 * version before it, "two concentric circles with eight radial ticks", reading as
 * a sun. The fix then was to make the *body* one continuous outline, which
 * helped and was not enough: a thin ring around a thin hub ring is still two
 * rings at 17px. Filling the silhouette is what actually settles it, and it is
 * the form Windows uses for this control itself.
 *
 * The hub is a second subpath under `evenodd`, so it is a hole rather than a
 * filled circle drawn on top.
 *
 * One component rather than two copies: the rail's gear and the sidebar's were
 * byte-identical strings in two files, which is a copy that is correct right up
 * until the day one of them is edited.
 */

interface Props {
  /** Width and height in CSS pixels. */
  size?: number;
}

export function Gear({ size = 17 }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      fillRule="evenodd"
      stroke="none"
      // Decorative: every place this is drawn labels itself. Without
      // `focusable` a Tab can land on it in older engines.
      aria-hidden="true"
      focusable="false"
    >
      <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
    </svg>
  );
}
