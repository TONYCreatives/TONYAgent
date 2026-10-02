/**
 * The app's own title bar, and the top bar's job on top of that.
 *
 * Two things live here now, because the window has no system title bar
 * (`decorations: false` in tauri.conf.json):
 *
 * - **The drag region.** `data-tauri-drag-region="deep"` is what makes the
 *   window moveable at all, so it is the load-bearing attribute rather than
 *   decoration. "deep" rather than bare: bare only drags when the press lands
 *   on the element itself, and every pixel of this bar is covered by a child --
 *   the tab pill, the title, the caption buttons -- so a bare attribute would
 *   leave almost nothing draggable. Tauri walks the pressed element's ancestor
 *   chain, and a `<button>` with no attribute of its own blocks the drag, which
 *   is exactly right: the caption buttons and the tab pill are clickable and
 *   must not also be a drag handle.
 * - **The caption.** `WindowControls`, supplied by the caller so this file needs
 *   no Tauri and no window state of its own.
 *
 * The bar still answers exactly one question -- "what am I looking at, and is it
 * busy?" -- and the rail answers "what can I do?". It names the open
 * conversation, not the application: a bar that said "TONYAgent" answered "what
 * is this program", the question the taskbar and the window icon already
 * answer, and left the useful one -- the name of the thing you are reading, and
 * the one that changes when you rename it -- unasked.
 */

import { WindowControls } from "./WindowControls.js";
import type { WindowControls as WindowActions } from "./useWindowControls.js";

interface Props {
  busy: boolean;
  /** Title of the open conversation, or "" before one exists. */
  title: string;
  /**
   * The caption buttons, or null outside the Tauri shell.
   *
   * A prop rather than a hook call here so the bar stays renderable in jsdom
   * and in a browser, where there is no window to caption.
   */
  controls?: WindowActions | null;
}

export function TopBar({ busy, title, controls }: Props) {
  return (
    <header className="topbar" data-tauri-drag-region="deep">
      <div className="tab">
        {busy && <span className="tab-spinner" aria-label="Working" />}
        <span className="tab-title" title={title || undefined}>
          {title || "TONYAgent"}
        </span>
      </div>
      <div className="topbar-spacer" />
      {controls && (
        <WindowControls
          maximized={controls.maximized}
          onMinimize={controls.minimize}
          onToggleMaximize={controls.toggleMaximize}
          onClose={controls.close}
        />
      )}
    </header>
  );
}