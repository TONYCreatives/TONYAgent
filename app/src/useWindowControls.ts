/**
 * The window's own caption buttons, because the window has no system ones.
 *
 * The window is undecorated (`frameless` in the host), so Windows draws no
 * title bar: no caption, no minimize/maximize/close, no drag handle, no
 * double-click to maximize. Everything the OS bar used to provide is either
 * markup in the top bar or a call in here.
 *
 * **The gestures are still the OS's.** Moving and resizing are not
 * reimplemented here. A window pushed around with a `SetWindowPos` per mouse
 * move -- which is what a JavaScript drag does -- is not a window the OS is
 * dragging, and it is therefore a window that cannot be snapped: no
 * drag-to-the-top maximize, no half-screen tiles, no drag previews. So what
 * this hook does is *name* the gesture. The page knows where the title bar and
 * the edges are and the host does not, so the page says "the caption was
 * pressed" or "the left edge was pressed", and the host starts the same modal
 * loops a decorated window runs.
 *
 * **The host answers late, so this hook starts null.** The bridge is injected
 * after the page loads and announces itself with an event, so on the first
 * render there is nothing to drive yet. Returning null until it arrives is the
 * same answer this hook already gave for a browser preview, and for the same
 * reason: a caption drawn before there is a window behind it is three controls
 * that look like they work and do not.
 *
 * **The maximized state is read, and then followed.** Reading it once would
 * leave the button offering "maximize" after the user maximized by
 * double-clicking the title bar or by dragging the window to the top of the
 * screen -- neither of which is a button press this page ever hears about. So
 * the state is re-read when the viewport resizes, which is what both of those
 * gestures do. Debounced, because a drag-resize fires it continuously and each
 * re-read is a round trip to the host.
 *
 * **The system menu is the one thing no window API covers.** It goes through
 * the host's own Win32 call, which asks the OS for the menu it already has
 * rather than rebuilding one -- so the greyed-out states and the Move and Size
 * loops are the system's own. Alt+Space is the name Windows gives that menu and
 * is deliberately *not* bound: on the machine this was built on it belongs to
 * Copilot and the OS takes it before any window sees it, so a binding for it
 * would be a line of code that can never run. F10 is the other name Windows has
 * for the same menu, and nothing here claims it.
 *
 * Named for the hook rather than the module it wraps, because the sibling
 * `WindowControls.tsx` is the component: a `windowControls.ts` beside a
 * `WindowControls.tsx` is two files whose names differ only in case, which
 * compiles on Windows and confuses git, bundlers and every `forceUpdate` since.
 */

import { useCallback, useEffect, useState } from "react";

import {
  whenHostReady,
  type HostApi,
  type ResizeEdge,
  type WindowAction,
} from "./bridge.js";

export interface WindowControls {
  /** True when the window is maximized, so the button offers to restore it. */
  maximized: boolean;
  minimize(): void;
  toggleMaximize(): void;
  close(): void;
  /**
   * Open the window's system menu at the cursor.
   *
   * The whole reason this exists: with no decorations there is no Alt+Space, no
   * right-click menu, and no Move or Size -- and those last two are drag loops
   * the OS runs and no component can stand in for.
   */
  showSystemMenu(): void;
}

/**
 * The class a press has to land on to move the window.
 *
 * A class rather than "anywhere in the bar" for the reason the bar has
 * controls in it: the model picker and the three caption buttons live up there,
 * and a press that starts a window drag is a press that never reaches them. So
 * the bar and its empty regions carry this, the controls do not, and the check
 * is on the pressed element *itself* rather than on an ancestor. The host holds
 * the same name as `DRAG_CLASS` in `host.py`, where the region's behaviour now
 * lives.
 */
export const DRAG_REGION_CLASS = "app-drag-region";

/** How close to an edge a press has to be to count as a resize. */
const RESIZE_BORDER = 8;

/** The cursor each edge wears, so the frame is visible without a frame. */
const EDGE_CURSORS: Record<ResizeEdge, string> = {
  left: "ew-resize",
  right: "ew-resize",
  top: "ns-resize",
  bottom: "ns-resize",
  "top-left": "nwse-resize",
  "top-right": "nesw-resize",
  "bottom-left": "nesw-resize",
  "bottom-right": "nwse-resize",
};

/**
 * Which of the window's edges a point is on, or null when it is inside them.
 *
 * A pure function of the point and the window's size, which is what makes the
 * arithmetic testable without a window to measure. A corner is decided before a
 * side, because a press equally close to two edges is a corner press and not
 * either of them alone.
 */
export function edgeAt(
  x: number,
  y: number,
  width: number,
  height: number,
): ResizeEdge | null {
  const left = x < RESIZE_BORDER;
  const right = x >= width - RESIZE_BORDER;
  const top = y < RESIZE_BORDER;
  const bottom = y >= height - RESIZE_BORDER;
  if (top && left) return "top-left";
  if (top && right) return "top-right";
  if (bottom && left) return "bottom-left";
  if (bottom && right) return "bottom-right";
  if (top) return "top";
  if (bottom) return "bottom";
  if (left) return "left";
  if (right) return "right";
  return null;
}

/** How long to wait after a resize before asking the window about itself. */
const RESIZE_SETTLE_MS = 120;

/**
 * Read and drive the current window, or `null` when there is none to drive.
 *
 * Null rather than a set of no-ops: a caption drawn in a browser preview has
 * nothing to minimize, so it would be three controls that look like they work
 * and do not.
 */
export function useWindowControls(): WindowControls | null {
  const [api, setApi] = useState<HostApi | null>(null);
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let disposed = false;
    void (async () => {
      const found = await whenHostReady();
      // `disposed` is checked before `setApi`, not after: the bridge arrives
      // asynchronously and React 19's StrictMode unmounts this effect before it
      // does, so without the check the first mount would set state on a
      // component that is already gone.
      if (!found || disposed) return;
      setApi(found);
      try {
        const state = await found.window_state();
        if (!disposed) setMaximized(state.maximized);
      } catch (error: unknown) {
        console.warn("[tonyagent] could not read the window state:", error);
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  const apply = useCallback((state: { maximized: boolean }) => {
    setMaximized(state.maximized);
  }, []);

  const run = useCallback(
    (action: WindowAction, edge?: ResizeEdge) => {
      if (!api) return;
      void api
        .window_control(action, edge)
        .then(apply)
        .catch((error: unknown) => {
          // Nothing to show the user: the caption is the only place this could
          // be reported, and a caption that says "I could not close the window"
          // is worse than one that stays quiet. The console keeps the reason.
          console.warn(`[tonyagent] could not ${action} the window:`, error);
        });
    },
    [api, apply],
  );

  const showSystemMenu = useCallback(() => {
    if (!api) return;
    void api
      .system_menu()
      .then(apply)
      .catch((error: unknown) => {
        console.warn("[tonyagent] could not open the system menu:", error);
      });
  }, [api, apply]);

  // Follow the window's own idea of whether it is maximized.
  //
  // A drag to the screen edge is the gesture this page never hears about as a
  // press -- the OS runs it -- and a resize is what it leaves behind, so this is
  // when to ask again. The double-click is ours and goes through `run`, which
  // reads the same answer back.
  useEffect(() => {
    if (!api) return;
    let timer = 0;
    const onResize = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        void api
          .window_state()
          .then(apply)
          .catch(() => {
            // A resize during teardown is not worth a console line.
          });
      }, RESIZE_SETTLE_MS);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [api, apply]);

  // The window's edges and its title bar: the two things whose position the page
  // knows and the host cannot.
  //
  // Both end in the OS's own loops -- see `win32` -- so all this does is name the
  // gesture and put the right cursor over the edge. The resize is decided first,
  // because a window's frame is the frame's before it is the caption's: that is
  // what makes the top few pixels of a title bar resize rather than drag, here as
  // in every other program.
  useEffect(() => {
    if (!api) return;
    let cursor = "";

    const onMouseDown = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const edge = edgeAt(
        event.clientX,
        event.clientY,
        window.innerWidth,
        window.innerHeight,
      );
      if (edge) {
        event.preventDefault();
        run("resize", edge);
        return;
      }
      const pressed = event.target as Element | null;
      if (!pressed?.classList?.contains(DRAG_REGION_CLASS)) return;
      event.preventDefault();
      // The second press of a double-click maximizes, which is what a title bar
      // does everywhere else and what a user's hands already expect. The first
      // press of the pair has started a move; letting go of the mouse ends it,
      // and the maximize lands on top of it.
      run(event.detail >= 2 ? "toggleMaximize" : "drag");
    };

    const onMouseMove = (event: MouseEvent) => {
      const edge = edgeAt(
        event.clientX,
        event.clientY,
        window.innerWidth,
        window.innerHeight,
      );
      const wanted = edge ? EDGE_CURSORS[edge] : "";
      if (wanted === cursor) return;
      cursor = wanted;
      document.documentElement.style.cursor = wanted;
    };

    // The pointer left the window, so the edge it was on is not the edge it is
    // on any more -- and a resize cursor left behind is a cursor for a gesture
    // the user is no longer next to.
    const forgetCursor = () => {
      cursor = "";
      document.documentElement.style.cursor = "";
    };

    window.addEventListener("mousedown", onMouseDown, true);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("blur", forgetCursor);
    return () => {
      window.removeEventListener("mousedown", onMouseDown, true);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("blur", forgetCursor);
      forgetCursor();
    };
  }, [api, run]);

  // F10, because an undecorated window has a webview holding the focus and the
  //
  // No modifiers, which is what keeps Shift+F10 (the context-menu key) and
  // Ctrl+F10 and Alt+F10 out of it. The default is suppressed, because with the
  // caret in the composer F10 would otherwise be swallowed by the webview's own
  // handling and nothing would happen at all.
  useEffect(() => {
    if (!api) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      // Either name: `code` is the physical key, `key` is what the layout calls
      // it, and a shortcut that only answers to one of them is broken on half
      // the keyboards.
      if (event.code !== "F10" && event.key !== "F10") return;
      event.preventDefault();
      showSystemMenu();
    };
    // Capture, because the surfaces in this app handle their own keys and one
    // that stops propagation would otherwise swallow the window's own.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [api, showSystemMenu]);

  if (!api) return null;
  return {
    maximized,
    minimize: () => run("minimize"),
    toggleMaximize: () => run("toggleMaximize"),
    close: () => run("close"),
    showSystemMenu,
  };
}
