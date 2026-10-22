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
 * The provider's account pages the host will open, as the host names them.
 *
 * A closed set rather than a URL, and the closing is the host's: the page may
 * name a view and nothing else, so a window this program creates cannot be
 * pointed at an arbitrary site from here.
 */
export type AccountView = "activity" | "credits" | "keys";

/**
 * Why a read of one of those pages did not produce figures.
 *
 * `no-window` is a webview that refused a window, `timeout` is a page that did
 * not arrive, `unreadable` is a page that answered with something this side
 * could not parse. Each is a different sentence for the user, which is why they
 * are not collapsed into one failure.
 */
export type AccountReason = "no-window" | "timeout" | "unreadable";

/** One label the provider's page displayed, and the value beside it. */
export interface AccountFigure {
  label: string;
  value: string;
}

/**
 * What the provider's page said.
 *
 * `figures` is the page's own wording, paired as it displayed it and never
 * renamed or added up -- see `AccountBrowser.EXTRACT`. `signed_out` is the state
 * the user has to fix, and it is not a failure: the read worked and the page is
 * the sign-in page.
 */
export interface AccountRead {
  view: string;
  url: string;
  ok: boolean;
  reason?: AccountReason;
  signed_out: boolean;
  figures: AccountFigure[];
  read_at: number;
}

/** Everything the desktop pet can be asked. See `Bridge.pet`. */
export type PetAction = "state" | "show" | "hide" | "ready" | "status" | "focus" | "drag";

/** What the pet reports about itself: up now, and wanted at next start. */
export interface PetStateReply {
  open: boolean;
  wanted: boolean;
}

/**
 * What a drag reported: whether the card actually moved.
 *
 * Not part of `PetStateReply`, because only one action answers it and the two
 * callers care about different halves -- the app's toggle wants the booleans, the
 * card wants this. See `DeskPet.drag`: a press that moved nothing is a click, and
 * the card is the only thing that can act on the difference.
 */
export interface PetDragReply {
  moved: boolean;
  x: number;
  y: number;
}

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
  /**
   * Open one of the provider's own pages in a real browser window.
   *
   * `opened` is not decoration: creating a second window can be refused, and a
   * caller that assumed otherwise would claim a window had opened that had not.
   */
  open_account_view(view: AccountView): Promise<{ view: string; url: string; opened: boolean }>;
  /** Show one of them and read the figures it is displaying. */
  read_account_view(view: AccountView): Promise<AccountRead>;
  /**
   * The desktop pet: ask about it, show or hide it, or tell it what to draw.
   *
   * One method with a closed set of actions, because two pages share this bridge
   * -- the app asks for the state and pushes statuses, the card announces itself,
   * drags itself and raises the app -- and the action is what tells them apart.
   */
  pet(action: PetAction, payload?: Record<string, unknown>): Promise<PetStateReply & Partial<PetDragReply>>;
  /**
   * Run the installer the core downloaded, and close the window.
   *
   * **No arguments**, deliberately. The file to run is found in one directory
   * and checked against a name pattern there, so the page cannot point this at
   * an arbitrary path -- the same rule `open_account_view`'s closed set keeps.
   * The window closes itself because Windows Installer cannot replace the
   * running executable: the close is what lets the update proceed.
   */
  update_install(): Promise<{ started: boolean; reason: string; path: string }>;
  /**
   * Open the project's releases page in the user's own browser.
   *
   * The address is a constant in the core, so the page cannot point this
   * anywhere. The *user's* browser rather than the owned one: a release page
   * needs no remembered sign-in, and it is where a manual download belongs.
   */
  open_releases(): Promise<{ url: string; opened: boolean }>;
  /**
   * Open the folder the core's log files live in.
   *
   * No arguments, like `update_install`: the folder is the one `diagnostics.get`
   * reports, chosen by the host, so the page cannot point this anywhere.
   */
  open_logs(): Promise<{ path: string; opened: boolean }>;
  /**
   * Open one project file in the OS default app.
   *
   * The path is project-relative and confined by the host, so the page
   * cannot point this outside the project. Reported, not raised -- a
   * button that errors is worse than one that quietly did nothing.
   */
  open_path(path: string): Promise<{ path: string; opened: boolean }>;
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

/**
 * The host, or null when this page is running somewhere else.
 *
 * **`null` for pywebview's placeholder, which is the whole reason this is not a
 * one-line accessor.** pywebview injects the bridge in halves: `api.js` runs at
 * document start and sets `window.pywebview = { ..., api: {} }`, and `finish.js`
 * later calls `_createApi(...)` to put the methods on that object and only
 * *then* dispatches `pywebviewready`. So there is a window -- as long as it
 * takes the host to answer -- in which `api` is a truthy object with nothing on
 * it.
 *
 * Handing that back as "the host" is what put `TypeError: a.ready is not a
 * function` in the window's error banner the moment the app opened: the page's
 * script won the race, `whenHostReady` short-circuited on the placeholder, and
 * the first thing `start()` does is call `api.ready()`.
 *
 * **Empty is the test, and not the presence of some particular method.** The two
 * halves are separated by a synchronous `_createApi` call -- it loops over the
 * method list and assigns, with no await anywhere in it -- so "one method is
 * there" and "they are all there" are the same instant, and nothing can observe
 * a half-built api. Asking for one method by name would instead make this a
 * statement about what the *reader* needs, and this function has readers that
 * want `ready` (startup), `window_state` (the caption) and `pet` (the card): a
 * host with one of those and not the others is not something pywebview can
 * produce, so testing for it would be testing a shape that cannot occur.
 */
export function host(): HostApi | null {
  if (typeof window === "undefined") return null;
  const api = (window as unknown as HostGlobal).pywebview?.api;
  return api && Object.keys(api).length > 0 ? api : null;
}

/**
 * Whether pywebview has injected anything at all, methods or not.
 *
 * The distinction `host()` deliberately throws away, and the one thing a caller
 * waiting on a *slow* bridge needs: an empty `api` means the host is present and
 * still being built, while no `pywebview` at all means this page is in a browser
 * or a test and there will never be one.
 */
function presentsHost(): boolean {
  if (typeof window === "undefined") return false;
  return (window as unknown as HostGlobal).pywebview !== undefined;
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
 * Install the handler the pet's card receives on.
 *
 * Separate from `installPushHandlers` rather than a fourth key on it, because the
 * two pages are pushed *different* things: the app is pushed the core's frames
 * and the card is pushed the app's conclusions about them. One object carrying
 * both would have each page listening for what the other is sent, which is how a
 * missing key becomes a crash in a window nobody is looking at.
 *
 * `onStatus` is a name the host holds too -- `pet.PUSH_TARGET` -- and the two
 * must agree.
 */
export function installStatusHandler(handler: (status: unknown) => void): void {
  (window as unknown as Record<string, unknown>)[PUSH_TARGET] = { onStatus: handler };
}

/**
 * The host, once it has announced itself.
 *
 * Resolves to `null` on timeout rather than rejecting, because "there is no
 * window here" is an ordinary answer: a browser preview, a jsdom test and a
 * `vite dev` session all run this page without a host, and all three should get
 * a page that renders and says so.
 *
 * **The timeout is for "there is no host here", not for "the host is slow".**
 * Those are different questions and pywebview makes them distinguishable: an
 * empty `api` with a `pywebview` beside it is a bridge that is present and still
 * being built, and `finish.js` is on its way with the methods and the event. So
 * the wait re-arms while the bridge is there, and only a page with no
 * `pywebview` at all is answered with `null` -- answering the other way would
 * turn a slow cold start into "No window host answered" about a window that is
 * about to work.
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

    function wait(): void {
      timer = window.setTimeout(() => {
        if (settled) return;
        if (presentsHost()) {
          wait();
          return;
        }
        finish(null);
      }, timeoutMs);
    }

    window.addEventListener("pywebviewready", onReady);
    // The timeout is not a failure path, it is the *only* way a page with no
    // host ever hears an answer. Without it, every test and every browser tab
    // would hang on a promise that can never settle.
    wait();
  });
}
