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
 * The system menu is the one thing the window API does not cover, so it goes
 * through `core`'s `invoke` and one app command of its own (see
 * `src-tauri/src/system_menu.rs`). Same lazy import, same reason.
 *
 * Named for the hook rather than the module it wraps, because the sibling
 * `WindowControls.tsx` is the component: a `windowControls.ts` beside a
 * `WindowControls.tsx` is two files whose names differ only in case, which
 * compiles on Windows and confuses git, bundlers and every `forceUpdate` since.
 */

import { useCallback, useEffect, useState } from "react";

type WindowModule = typeof import("@tauri-apps/api/window");
type CoreModule = typeof import("@tauri-apps/api/core");

let cached: WindowModule | null = null;
let cachedCore: CoreModule | null = null;

async function loadWindow(): Promise<WindowModule> {
  if (!cached) cached = await import("@tauri-apps/api/window");
  return cached;
}

async function loadCore(): Promise<CoreModule> {
  if (!cachedCore) cachedCore = await import("@tauri-apps/api/core");
  return cachedCore;
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
  /**
   * Open the window's system menu at the cursor.
   *
   * The whole reason this exists: with `decorations: false` there is no
   * `Alt+Space`, no right-click menu, and no Move or Size. The command asks
   * the OS for the menu it already has, so the greyed-out states and the move
   * and size loops are the system's own.
   */
  showSystemMenu(): void;
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

  const showSystemMenu = useCallback(() => {
    void (async () => {
      const { invoke } = await loadCore();
      await invoke("show_system_menu");
    })().catch((error: unknown) => {
      // A menu that did not open is not something the user can be told about
      // from here -- there is no caption left to say it on. The console keeps
      // the reason, which is the ACL refusing the call.
      console.warn("[tonyagent] could not open the system menu:", error);
    });
  }, []);

  // F10. A decorated window gets Alt+Space from the OS, which is why nobody
  // implements it: the key never reaches the page, DefWindowProc sees it on the
  // window. An undecorated one has a webview with the focus instead, so the
  // page is the only place that can hear a key at all.
  //
  // Alt+Space is the obvious candidate and is deliberately *not* bound: on this
  // machine it is Copilot's, taken by the OS before any window sees it, so a
  // binding for it would be a line of code that can never run. F10 is the other
  // name Windows has for the same menu, and nothing here claims it.
  //
  // No modifiers, which is what keeps Shift+F10 (the context-menu key) and
  // Ctrl+F10 and Alt+F10 out of it. The default is suppressed, because with the
  // caret in the composer F10 would otherwise be swallowed by the webview's own
  // handling and nothing would happen at all.
  useEffect(() => {
    if (!inTauri()) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      // Either name: `code` is the physical key, `key` is what the layout
      // calls it, and a shortcut that only answers to one of them is broken on
      // half the keyboards.
      if (event.code !== "F10" && event.key !== "F10") return;
      event.preventDefault();
      showSystemMenu();
    };
    // Capture, because the surfaces in this app handle their own keys and one
    // that stops propagation would otherwise swallow the window's own.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [showSystemMenu]);

  if (!inTauri()) return null;
  return {
    maximized,
    minimize: () => run("minimize"),
    toggleMaximize: () => run("toggleMaximize"),
    close: () => run("close"),
    showSystemMenu,
  };
}