/**
 * Where a menu opens, as arithmetic over two rectangles.
 *
 * Every menu in this window is positioned by the stylesheet against the trigger
 * that opened it, so whether it *fits* is a question only layout can answer --
 * and for a long time no surface asked it. The model picker hung 320px to the
 * right of a chip in the title bar's right-hand cluster and was cut off by the
 * window edge; the row menu opened downward from a click near the bottom of a
 * short window and hid its own Delete behind the client rect. Both were
 * reported from the running window, not read off the stylesheet.
 *
 * **The decision is a function of two rectangles and nothing else**, which is
 * the only reason it can be tested at all: jsdom reports every rectangle as
 * zero, so a rule that had to be *measured* rather than *computed* could not be
 * asserted. `useMenuPlacement` is what hands it real rectangles; nothing here
 * touches the DOM.
 *
 * **A menu keeps the side it has always been on, and flips only when it cannot
 * stay there.** The vertical half of that question needs no widths -- above and
 * below are the trigger's own edges -- but the horizontal half does, so a menu's
 * width comes in with the trigger: the pickers measure theirs (`offsetWidth`,
 * which is immune to the entry animation's transform) and two of them have a
 * width the stylesheet overrides per context -- 320px in the title bar, 232px
 * for the code viewer's theme chip -- which a measurement picks up and a
 * constant in this module could not.
 *
 * The one exception is a menu with no width to declare: the row menus size to
 * their own content, and they are anchored inside a 255px sidebar with at least
 * 380px of window to their right, so the honest answer is the default side
 * rather than a guess at a width nobody measured.
 *
 * **Two ways to consume it, because a menu is positioned against one of two
 * things.** A menu inside a wrapper (`position: absolute` in a `position:
 * relative` trigger) is positioned by the *stylesheet*: this module decides
 * `dir` and `align`, the component writes them as `data-` attributes, and a
 * rule per direction carries the anchor -- which is why the base rule declares
 * neither `top` nor `bottom` and a menu that never got a direction renders
 * unpositioned rather than silently opening the wrong way.
 *
 * A menu rendered at the window root (`position: fixed`, the two row menus, out
 * of a portal so the sidebar's `overflow` cannot clip it) cannot do that: `100%`
 * in its box is the whole window, not the trigger. Those are given the numbers
 * outright by `placeFixedMenu` -- the vertical half of the placement written
 * out, one axis each, because the horizontal half already has an answer there
 * (see that function) and there is nothing left for the stylesheet to say.
 */

/**
 * The smallest a menu may be capped to.
 *
 * A trigger hard against the edge of its bounds still has to open somewhere.
 * The floor lets a menu exceed the room it measured by a little and scroll,
 * which is recoverable; a height of zero is a menu whose every row is a sliver
 * the user cannot click.
 */
export const MENU_MIN_HEIGHT = 120;

/**
 * The space a wrapped menu leaves between itself and its trigger.
 *
 * The stylesheet owns the same distance -- `calc(100% + var(--menu-gap))` on the
 * direction rules in `thinking.css` and `settings.css` -- because those rules
 * are what *moves* the menu. This copy is what the *cap* is measured against:
 * the room on a side is the space from the trigger's edge to the edge of the
 * bounds, and the menu has to stop one gap short of it. Six pixels of
 * disagreement would put the last row of a capped menu six pixels past the floor
 * it was capped to, so `layout.test.ts` reads the token out of the stylesheet
 * and compares this number with it: the two cannot be changed apart, which is
 * as close as a module and a stylesheet can get to sharing a constant.
 */
export const MENU_GAP = 6;

/**
 * The edges a menu is bounded by, and the edges it is anchored to.
 *
 * Not a `DOMRect`, because the bounds of the *window* are built here rather
 * than measured -- and because a `DOMRect` is structurally assignable to this
 * and a two-field object is not, which is what keeps a caller from placing a
 * menu against a rectangle that has no left or right edge.
 */
export interface MenuBounds {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** Which way a menu opens: above its trigger, or below it. */
export type MenuDirection = "up" | "down";

/**
 * Which edge of the trigger a menu hangs from.
 *
 * `start` is the app's ordinary case and the one the stylesheet used to assume:
 * the menu's left edge on the trigger's left edge, growing rightwards. `end` is
 * the mirror -- the menu's right edge on the trigger's right edge -- and it is
 * what a control near the window's right edge needs, because the opposite side
 * has no room.
 */
export type MenuAlign = "start" | "end";

/** What `placeMenu` needs beyond the two rectangles. */
export interface MenuRequest {
  /**
   * The menu's own width, in border-box pixels.
   *
   * Zero -- or absent -- for a menu that sizes to its content and has not been
   * measured, which is the two row menus: it is then taken to fit, and it keeps
   * the side it has always opened on rather than being flipped on a guess.
   */
  width?: number;
  /** How far the menu sits from its trigger. */
  gap?: number;
}

/** What the placement decided, and the height the menu is allowed. */
export interface MenuPlacement {
  dir: MenuDirection;
  align: MenuAlign;
  maxHeight: number;
}

/** The window, as a box. Its edges are the viewport's, not the document's. */
export function viewportBounds(): MenuBounds {
  return {
    top: 0,
    left: 0,
    right: window.innerWidth,
    bottom: window.innerHeight,
  };
}

/**
 * A pointer, as a rectangle with no width and no height.
 *
 * A right-click on a row or a tab has no button to hang a menu from, so the
 * pointer is the anchor: the menu opens below it (or above it, near the floor)
 * and on the side of it that has room. Built here rather than written out at
 * each call site so the two menus that do it agree about what a pointer is.
 */
export function pointerBounds(x: number, y: number): MenuBounds {
  return { top: y, bottom: y, left: x, right: x };
}

/**
 * Which side of the trigger a menu opens on, and how tall it may be.
 *
 * A tie -- the same room above as below, or the same to each side -- goes to
 * `down` and `start`, which is the case the title bar and the settings panel are
 * both actually in: a control with the same room both ways is one in the middle,
 * and a menu that flickered to the other side of it from one pixel of resize
 * would be worse than one that never moved. It is also the position every menu
 * in the app had before there was a choice, so a tie is not a visible change.
 */
export function placeMenu(
  trigger: MenuBounds,
  bounds: MenuBounds,
  { width = 0, gap = MENU_GAP }: MenuRequest = {},
): MenuPlacement {
  const above = trigger.top - bounds.top - gap;
  const below = bounds.bottom - trigger.bottom - gap;
  const dir: MenuDirection = above > below ? "up" : "down";
  // The two sides, asked in that order: the edge the menu hangs from is the
  // trigger's, so `start` needs the trigger's left edge plus the menu's width to
  // clear the bounds, and `end` needs its right edge minus the menu's width to
  // stay inside them. A tie -- neither side can hold it -- goes to `start`,
  // because that is where every menu in the app opened before this existed and
  // there is nothing to choose between two failures.
  const fitsRight = width === 0 || trigger.left + width <= bounds.right;
  const fitsLeft = trigger.right - width >= bounds.left;
  const align: MenuAlign = fitsRight
    ? "start"
    : fitsLeft
      ? "end"
      : bounds.right - trigger.left >= trigger.right - bounds.left
        ? "start"
        : "end";
  return {
    dir,
    align,
    // Floored rather than taken literally, and not read off the menu: the
    // menu's own height is not known until it is laid out, and a fixed number
    // would be wrong in every window but one. What *is* known at open time is
    // the space available, and a menu taller than that is one whose last row
    // cannot be reached.
    maxHeight: Math.max(MENU_MIN_HEIGHT, dir === "up" ? above : below),
  };
}

/** Offsets for a `position: fixed` menu, in the fields a fixed menu can use. */
export interface MenuOffsets {
  top?: number;
  bottom?: number;
  left: number;
}

/**
 * The placement of a menu that is rendered at the window root, and where to put
 * it.
 *
 * Both row menus -- the conversation row's and the tab's -- live in a portal so
 * that the sidebar's and the tab strip's `overflow` cannot clip them, which
 * also means the window is the only box they can be measured against and the
 * only one they can be positioned in. So they get numbers: the offsets *are*
 * the placement, one axis each, and the stylesheet keeps only the shape of the
 * surface.
 *
 * The anchor is a rectangle rather than a point for one reason: the row's own
 * button hands over its box, a right-click hands over a pointer, and a pointer
 * is a rectangle with no width -- see `pointerBounds`. Both then get the same
 * answer, which is what the two entry points lacked when each added its own gap.
 *
 * **Only the vertical half is a question here.** Both row menus hang from
 * something on the left -- the sidebar, which is 255px wide, and the tab strip,
 * which is capped at `min(60%, 360px)` of the window -- and both are 132px wide,
 * so the menu's right edge lands at 0.6W + 132 of a W-wide window: inside it for
 * every W above 330, and this window cannot be made narrower than 640. The
 * horizontal answer is therefore the anchor's own left edge, and the align the
 * placement computes for them is deliberately not used rather than being used
 * to write an offset that no click can reach.
 */
export function placeFixedMenu(
  trigger: MenuBounds,
  gap = MENU_GAP,
): { placement: MenuPlacement; offsets: MenuOffsets } {
  const bounds = viewportBounds();
  const placement = placeMenu(trigger, bounds, { gap });
  const offsets: MenuOffsets = { left: trigger.left };
  if (placement.dir === "down") offsets.top = trigger.bottom + gap;
  // `bottom` in a fixed box counts up from the viewport's floor, so a menu
  // opening upward is written as the distance from that floor to the trigger's
  // top edge -- plus the gap it keeps.
  else offsets.bottom = bounds.bottom - trigger.top + gap;
  return { placement, offsets };
}
