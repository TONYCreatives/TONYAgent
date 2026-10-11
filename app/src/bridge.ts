/**
 * The seam between the page and the window it is running inside.
 *
 * This is what `@tauri-apps/api` and `@tauri-apps/plugin-*` used to be, and it
 * is deliberately a thin one: the page asks the host to send a line, pick a
 * folder, or move the window, and the host does it. Nothing here knows the wire
 * format -- that is `backend.ts`'s job -- and nothing here knows Win32.
 *
 * **The bridge arrives late, and that is the whole reason for
 * `whenHostReady`.** pywebview injects `window.pywebview.api` *after* the page
 * loads, and announces it with a `pywebviewready` event. So `host()` is null on
 * the first render and non-null a moment later, which is a shape a plain
 * function cannot express: every caller would have to poll or re-render. The
 * promise is the answer, and it resolves to `null` rather than rejecting when
 * there is no host at all -- a browser preview and a jsdom test are both
 * legitimate places for this page to run, and neither should get an unhandled
 * rejection for it.
 *
 * Nothing is imported from pywebview itself. The host is reached through one
 * global that the host installs, so this module has no dependency to resolve and
 * is importable in plain Node -- the same property `backend.ts` and `dialog.ts`
 * were built around before it.
 */

/**
 * Everything the window is asked to do, as the host accepts it.
 *
 * The last two are *gestures* rather than caption buttons, and they are here
 * because the page is the only thing that knows where the title bar and the
 * window's edges are. Both hand the press to the OS's own loops, which is what
 * makes snapping and the drag-to-the-top maximize the real ones.
 */
export type WindowAction =
  | "minimize"
  | "toggleMaximize"
  | "close"
  | "drag"
  | "resize";

/**
 * Which edge a resize starts from, as the host names them.
 *
 * Eight rather than four: a corner is its own hit code in Win32, so `top-left`
 * is something the page tells the host rather than something it works out from
 * two of them.
 */
export type ResizeEdge =
  | "left"
  | "right"
  | "top"
  | "bottom"
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

/**
 * What the window host exposes as `window.pywebview.api`.
 *
 * Every method returns an object rather than a bare value, and that is a
 * pywebview constraint rather than a style: the bridge marshals Python return
 * values through JSON, and a bare `None` arrives as `null` with no way to tell
 * "cancelled" from "failed". A named field says which.
 */
export interface HostApi {
  /** One request frame, on its way to the core. Resolves when it is written. */
  send(line: string): Promise<unknown>;
  /** The page is mounted and can receive pushes. Call once, before any send. */
  ready(): Promise<unknown>;
  core_alive(): Promise<{ alive: boolean }>;
  window_control(action: WindowAction, edge?: ResizeEdge): Promise<{ maximized: boolean }>;
  window_state(): Promise<{ maximized: boolean }>;
  system_menu(): Promise<{ maximized: boolean }>;
  pick_folder(): Promise<{ path: string | null }>;
  pick_files(multiple?: boolean): Promise<{ paths: string[] }>;
}

/** What the host pushes into the page. */
export interface PushHandlers {
  /** A batch of core output lines, already framed. */
  frames(lines: string[]): void;
  /** One line of the core's stderr. */
  log(line: string): void;
  /** The core is gone. */
  exit(): void;
}

/**
 * The global the host pushes into.
 *
 * A single object with three functions rather than three globals: the host
 * builds one script per push, and one name is one thing to get right. The host
 * holds the same string (`bridge.py`'s `TARGET`) and the two must agree.
 */
export const PUSH_TARGET = "__tonyAgent";

/** How long to wait for the bridge before concluding there is not one. */
const READY_TIMEOUT_MS = 3000;

interface HostGlobal {
  pywebview?: { api?: HostApi };
}

/** The host, or null when this page is running somewhere else. */
export function host(): HostApi | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as HostGlobal).pywebview?.api ?? null;
}

/** Whether a host is answering right now. */
export function inHost(): boolean {
  return host() !== null;
}

/**
 * Install the handlers the host pushes into.
 *
 * Must happen before `ready()` is called: the host buffers frames until then,
 * and flushes them *during* that call, so a handler installed afterwards would
 * miss the first batch -- which is the reply to the first request.
 */
export function installPushHandlers(handlers: PushHandlers): void {
  (window as unknown as Record<string, unknown>)[PUSH_TARGET] = {
    onFrames: handlers.frames,
    onLog: handlers.log,
    onCoreExit: handlers.exit,
  };
}

/**
 * The host, once it has announced itself.
 *
 * Resolves to `null` on timeout rather than rejecting, because "there is no
 * window here" is an ordinary answer: a browser preview, a jsdom test and a
 * `vite dev` session all run this page without a host, and all three should get
 * a page that renders and says so.
 */
export function whenHostReady(timeoutMs: number = READY_TIMEOUT_MS): Promise<HostApi | null> {
  const already = host();
  if (already) return Promise.resolve(already);
  if (typeof window === "undefined") return Promise.resolve(null);

  return new Promise((resolve) => {
    let settled = false;
    let timer = 0;

    function finish(api: HostApi | null): void {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      window.removeEventListener("pywebviewready", onReady);
      resolve(api);
    }

    function onReady(): void {
      finish(host());
    }

    window.addEventListener("pywebviewready", onReady);
    // The timeout is not a failure path, it is the *only* way a page with no
    // host ever hears an answer. Without it, every test and every browser tab
    // would hang on a promise that can never settle.
    timer = window.setTimeout(() => finish(host()), timeoutMs);
  });
}
