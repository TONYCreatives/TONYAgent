/**
 * The placement of a menu anchored to a control, measured when it opens.
 *
 * `placeMenu` in `menuPlacement.ts` is the decision; this is where it gets its
 * two rectangles from, and the two things it has to get right are *when* and
 * *against what*.
 *
 * **When: a layout effect, before paint.** In an ordinary effect the menu would
 * be committed at the stylesheet's default position, painted, and only then
 * moved -- which on a menu that is 320px wide and 900px from where it belongs
 * is a frame of a menu hanging off the window. jsdom is why this is not simply
 * done in a render: the rectangles do not exist until after the commit, so the
 * measurement cannot happen earlier than this.
 *
 * **`visible`, not `open`.** The flag is what says the node is *on screen*, and
 * for a menu that lingers on its way out that is `useDelayedUnmount`'s `mounted`
 * rather than the open flag: the node arrives one commit after `open` does, so
 * an effect keyed on `open` measures a menu that is not in the DOM yet. That is
 * not a theoretical difference -- measured in the real window, it read the
 * menu's width as 0, which made "does it fit to the right of the chip" answer
 * yes for a menu that overflowed the window by 57px.
 *
 * **Against what: the surface that clips it, not the window.** Inside a
 * scrolling modal anything past the panel's edge is gone even though it is on
 * screen, so a menu capped to the window would be capped to the wrong box and
 * would lose its last row inside the panel it lives in. The class is
 * `confirm-modal.css`'s `.modal`, which is the one modal in this app -- the
 * confirmation, the settings panel and the search panel are all it -- so
 * "the nearest one, or the window when there is none" is the whole rule.
 *
 * The answer is deliberately *not* cleared when the menu closes. The node
 * outlives the dismissal so the exit animation has something to fade from the
 * right place (`useDelayedUnmount`), and a placement that reset on close would
 * send it back to the window's corner on the way out. It is re-measured on the
 * next open, and on a resize in between, because the answer is a function of
 * the window: a menu left open while the window is dragged narrower is a menu
 * that has to move with it.
 *
 * **The menu's width is measured too, and with `offsetWidth` rather than its
 * rectangle.** A picker arriving plays `pop-in`, which is a `scale(0.98)` and a
 * 6px rise held for the length of the animation -- so in the very commit this
 * measures in, the menu's *rectangle* is 2% narrower than the menu and 6px away
 * from where the stylesheet puts it. `offsetWidth` is the layout box, before
 * transforms, which is the number the horizontal half of the placement is
 * actually a question about. The side is chosen from it, and the two pickers
 * have widths the stylesheet changes per context -- 320 in the title bar, 232 in
 * the code viewer -- which a constant over here could not know.
 */

import { useCallback, useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

import { MENU_GAP, placeMenu, viewportBounds } from "./menuPlacement.js";
import type { MenuPlacement } from "./menuPlacement.js";

export function useMenuPlacement(
  visible: boolean,
  anchor: RefObject<HTMLElement | null>,
  menu: RefObject<HTMLElement | null>,
  gap = MENU_GAP,
): MenuPlacement | null {
  const [placement, setPlacement] = useState<MenuPlacement | null>(null);

  const measure = useCallback(() => {
    const node = anchor.current;
    if (!node) return;
    const panel = node.closest(".modal");
    setPlacement(
      placeMenu(
        node.getBoundingClientRect(),
        panel?.getBoundingClientRect() ?? viewportBounds(),
        { width: menu.current?.offsetWidth ?? 0, gap },
      ),
    );
  }, [anchor, menu, gap]);

  useLayoutEffect(() => {
    if (!visible) return;
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [visible, measure]);

  return placement;
}
