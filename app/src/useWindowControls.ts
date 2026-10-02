/**
 * The window's own caption buttons, because the window has no system ones.
 *
 * `tauri.conf.json` sets `decorations: false`, so Windows draws no title bar:
 * no caption, no minimize/maximize/close, no drag handle, no double-click to
 * maximize. Everything the OS bar used to provide is now either markup in the
 * top bar or a call in here, and the calls need permissions
 * (`core:window:allow-minimize` and friends) that `core:default` does not
 * grant -- `core:window:default` is all getters plus the internal
 * double-click maximize, so without the extra lines in `capabilities/default.json`
 * the buttons would be dead and say so only in the console.
 *
 * `@tauri-apps/api/window` is imported lazily through `import()`, for the same
 * reason `backend.ts` and `dialog.ts` do it: a top-level import is hoisted and
 * evaluated when the module loads, which would make every component test need
 * Tauri installed. It also means the module is importable in a plain browser,
 * where `useWindowControls` reports `null` and the caption is simply not drawn.
 *
 * Named for the hook rather than the module it wraps, because the sibling
 * `WindowControls.tsx` is the component: a `windowControls.ts` beside a
 * `WindowControls.tsx` is two files whose names differ only in case, which
 * compiles on Windows and confuses git, bundlers and every `forceUpdate` since.
 */

import { useCallback, useEffect, useState } from "react";

type WindowModule = typeof import("@tauri-apps/api/window");

let cached: WindowModule | null = null;

async function loadWindow(): Promise<WindowModule> {
  if (!cached) cached = await import("@tauri-apps/api/window");
  return cached;
}

/**
 * Whether the UI is running inside the Tauri shell.
 *
 * `__TAURI_INTERNALS__` is installed by Tauri itself before any app code runs,
 * so it is the honest test -- and the only one that is true in the packaged
 * window and false under jsdom.
 */
export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export interface WindowControls {
  /** True when the window is maximized, so the button offers to restore it. */
  maximized: boolean;
  minimize(): void;
  toggleMaximize(): void;
  close(): void;
}

/**
 * Read and drive the current window, or `null` outside the shell.
 *
 * Null rather than a set of no-ops: a caption drawn in a browser preview has
 * nothing to minimize, so it would be three controls that look like they work
 * and do not.
 *
 * The maximized state is read *and then followed*. Reading it once would leave
 * the button offering "maximize" after the user maximized by double-clicking
 * the drag region or snapping the window with the keyboard -- both of which the
 * same top bar offers.
 */
export function useWindowControls(): WindowControls | null {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!inTauri()) return;
    let disposed = false;
    let unlisten: (() => void) | null = null;
    void (async () => {
      const { getCurrentWindow } = await loadWindow();
      const win = getCurrentWindow();
      if (disposed) return;
      setMaximized(await win.isMaximized());
      unlisten = await win.onResized(() => {
        void win.isMaximized().then((now) => {
          if (!disposed) setMaximized(now);
        });
      });
    })().catch((error: unknown) => {
      console.warn("[tonyagent] the window controls are unavailable:", error);
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const run = useCallback((action: "minimize" | "toggleMaximize" | "close") => {
    void (async () => {
      const { getCurrentWindow } = await loadWindow();
      const win = getCurrentWindow();
      if (action === "minimize") await win.minimize();
      else if (action === "toggleMaximize") await win.toggleMaximize();
      else await win.close();
    })().catch((error: unknown) => {
      // Nothing to show the user: the caption is the only place this could be
      // reported, and a caption that says "I could not close the window" is
      // worse than one that stays quiet. The console keeps the reason.
      console.warn(`[tonyagent] could not ${action} the window:`, error);
    });
  }, []);

  if (!inTauri()) return null;
  return {
    maximized,
    minimize: () => run("minimize"),
    toggleMaximize: () => run("toggleMaximize"),
    close: () => run("close"),
  };
}