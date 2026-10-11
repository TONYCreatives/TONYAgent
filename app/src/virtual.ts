/**
 * Which lines of a file are worth rendering.
 *
 * A 20,000-line file is 20,000 rows of spans, and the browser lays every one
 * of them out whether or not it is on screen -- which is the difference
 * between a viewer that scrolls and one that hitches. VSCode does exactly
 * this: it draws the window of lines the viewport covers, plus a margin, and
 * two spacer elements of the right heights stand in for the rest.
 *
 * The arithmetic is a pure function of four numbers so it can be tested
 * without a DOM, a scroll event or a layout engine -- which matters here
 * because jsdom reports every element's height as zero, so a component test
 * could never exercise the interesting cases.
 */

export interface Range {
  /** First line to render, 0-based and inclusive. */
  start: number;
  /** Last line to render, 0-based and exclusive. */
  end: number;
  /** Height of the spacer above the rendered window, in pixels. */
  paddingTop: number;
  /** Height of the spacer below it. */
  paddingBottom: number;
}

/**
 * The visible window of lines.
 *
 * `overscan` is the margin above and below: rows just off screen are already
 * rendered, so a fast scroll shows text rather than blank space for one
 * frame. Zero height (no layout yet, or jsdom) reads as "render a screenful"
 * rather than "render nothing", because a viewer that shows an empty file
 * until something measures it is a viewer that looks broken.
 */
export function visibleRange(
  lineCount: number,
  scrollTop: number,
  viewportHeight: number,
  rowHeight: number,
  overscan = 12,
): Range {
  if (lineCount <= 0) return { start: 0, end: 0, paddingTop: 0, paddingBottom: 0 };

  const rows = Math.max(1, rowHeight);
  const height = viewportHeight > 0 ? viewportHeight : rows * 40;
  const top = Math.max(0, Math.min(scrollTop, lineCount * rows));

  const first = Math.max(0, Math.floor(top / rows) - overscan);
  const last = Math.min(lineCount, Math.ceil((top + height) / rows) + overscan);

  return {
    start: first,
    end: Math.max(last, first + 1),
    paddingTop: first * rows,
    paddingBottom: Math.max(0, (lineCount - Math.max(last, first + 1)) * rows),
  };
}
