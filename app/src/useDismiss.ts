/**
 * Dismissing a surface when something else happens.
 *
 * Three surfaces need this -- the row menu, the model picker and the tool
 * budget popover -- and each one grew its own copy of the listeners, which is
 * how all three ended up with the same bug: a capture-phase `pointerdown` on
 * `window` fires on the way *down*, for every press including presses that
 * land inside the surface. Clicking the model filter closed the menu the
 * filter was in; clicking a budget preset closed the popover before the
 * preset's own handler could be believed.
 *
 * The fix is one line and it is the whole point of this module: a press that
 * starts inside the surface is the surface being *used*, not dismissed. The
 * capture phase is kept deliberately -- it is what lets a press on the anchor
 * toggle the surface shut instead of being eaten by this listener closing it
 * on the way through.
 *
 * Every caller passes the element that *wraps* the anchor as well as the panel,
 * for the same reason: the anchor is inside the surface, so pressing it is not
 * a dismissal and the anchor's own toggle decides what happens.
 */

import { useEffect, type RefObject } from "react";

/**
 * Close `open` surfaces when the user does something else.
 *
 * @param open Whether the surface is currently open. Keyed on this rather than
 *   on the node: a dismissed surface stays mounted briefly so it can animate
 *   out, so an effect watching the node would never observe the close and
 *   would leave three window listeners attached for the rest of the session.
 * @param onClose Called for a press outside the surface, Escape, or the window
 *   losing focus. A cancel is a normal outcome, not an error.
 * @param surface The element that counts as "inside". Omit it and every press
 *   dismisses, which is only right for a surface with nothing to click.
 */
export function useDismiss(
  open: boolean,
  onClose: () => void,
  surface?: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const onPointerDown = (event: PointerEvent) => {
      const node = surface?.current;
      if (node && event.target instanceof Node && node.contains(event.target)) {
        return;
      }
      onClose();
    };
    // Capture, so a press on the anchor toggles rather than being eaten by
    // this listener closing it on the way through.
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", onClose);
    };
  }, [open, onClose, surface]);
}
