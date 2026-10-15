/**
 * The app's own title bar, and the top bar's job on top of that.
 *
 * Three things live here now, because the window has no system title bar (the
 * host creates it `frameless`):
 *
 * - **The mark.** The app's own "T", in the window's top-left corner -- the one
 *   place on screen that never goes away. It used to be in the sidebar's head,
 *   and the sidebar is an overlay: a logo that disappears when a panel closes is
 *   not the window's mark. See `.topbar-mark` in topbar.css.
 * - **The drag region.** `app-drag-region` is what makes the window moveable at
 *   all, so it is the load-bearing class rather than decoration. A press moves
 *   the window only when it lands on an element carrying the class *itself* --
 *   see `useWindowControls` -- so it goes on the bar and on the regions inside it
 *   that are nothing but background (the mark, the spacer), and the tabs, the
 *   caption buttons and the model picker, which are separate elements, stay
 *   clickable. That is the division Tauri's `"deep"` attribute was reaching for,
 *   made explicit rather than inherited from whichever elements happened to block
 *   it.
 *
 *   The class is the app's own now rather than pywebview's, and that is the point
 *   of the rename: pywebview's drag *moved the window itself*, a `SetWindowPos`
 *   per mouse move, and a window moved by hand is not a window the OS is
 *   dragging -- so it could never be snapped. The press is still detected here,
 *   because the page is what knows where the bar is, but what it does now is ask
 *   the host for the OS's own move loop. See `useWindowControls`.
 * - **The caption.** `WindowControls`, supplied by the caller so this file needs
 *   no window API and no window state of its own.
 *
 * The bar still answers exactly one question -- "what am I looking at, and is it
 * busy?" -- and the rail answers "what can I do?". It names the open
 * conversation, not the application: a bar that said "TONYAgent" answered "what
 * is this program", the question the taskbar and the window icon already
 * answer, and left the useful one -- the name of the thing you are reading, and
 * the one that changes when you rename it -- unasked.
 *
 * - **The system menu.** Turning the decorations off took away the right-click
 *   on the caption as well as the caption, and Windows answers that right-click
 *   with the window menu: Restore, Move, Size, Minimize, Maximize, Close. Move
 *   and Size are the two that cannot be rebuilt -- they are drag loops the OS
 *   runs, and without them an undecorated window cannot be positioned or
 *   resized at all. So the press is claimed here and handed to the OS rather
 *   than answered with a menu of our own; the coordinates are not passed
 *   because the system menu opens at the cursor on its own.
 *
 *   `preventDefault()` is load-bearing rather than tidy: the webview answers a
 *   right-click with its own context menu, and a user who right-clicks the
 *   title bar would get two menus, one of them for a document that is not a
 *   document.
 *
 *   The keyboard route to the same menu is F10, and it belongs to
 *   `useWindowControls` rather than here: the key is the window's, not the
 *   bar's, and it has to work with the caret in the composer.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import { useDismiss } from "./useDismiss.js";
import {
  DRAG_REGION_CLASS,
  type WindowControls as WindowActions,
} from "./useWindowControls.js";
import { AppMark } from "./AppMark.js";
import { WindowControls } from "./WindowControls.js";
import { placeFixedMenu, pointerBounds } from "./menuPlacement.js";
import type { MenuBounds } from "./menuPlacement.js";

/**
 * How far below the point that opened it the tab's menu sits.
 *
 * The same number and the same reason as the conversation row's: a menu whose
 * corner is on the cursor has the pointer resting on its own first item. Kept
 * as a local constant rather than imported from `ConversationList` so neither
 * file has to know the other exists for a menu they each render -- the comment
 * on each says they have to agree.
 */
const MENU_GAP = 4;

/** One chat open in the strip. */
export interface Tab {
  id: string;
  title: string;
  /**
   * Whether its name can be chosen by hand.
   *
   * False for a chat with no messages. Its name is a placeholder the core
   * replaces with the first thing the user says, and that replacement only fires
   * while the name is still "New chat" -- so a name typed into an empty chat is a
   * name the chat can never outgrow, which is worse than not being allowed to
   * type one.
   */
  renameable: boolean;
}

interface Props {
  busy: boolean;
  /**
   * The chats open in the strip, in the order they were opened.
   *
   * A tab is an open conversation, not a copy of one -- the core holds a single
   * session -- so selecting one is a switch rather than a second view, and two
   * tabs cannot disagree about what a chat says.
   */
  tabs?: Tab[];
  /** Which of them is showing. */
  active?: string;
  onSelect?: (id: string) => void;
  /** Close the tab. The chat stays in the sidebar; this is not a delete. */
  onClose?: (id: string) => void;
  /** Start a new chat, in a new tab. */
  onNewTab?: () => void;
  onRename?: (id: string, title: string) => void;
  /**
   * The caption buttons, or null when there is no window to caption.
   *
   * A prop rather than a hook call here so the bar stays renderable in jsdom and
   * in a browser, where there is no window to caption.
   */
  controls?: WindowActions | null;
  /**
   * The model selector, which lives up here now rather than in the composer.
   *
   * Where the model is chosen says how reversible it is. In the composer it
   * read as part of the message being composed, and it is not: it is what the
   * whole window is talking to, and it does not change when the message is sent.
   * Up here it sits on the right, between the title and the caption -- the
   * window's own controls rather than the page's, so it reads as a setting of
   * the window and not as something belonging to the conversation.
   *
   * A node rather than the picker's own props, so this file keeps knowing
   * nothing about models -- the App builds the control and the bar places it.
   */
  modelSelector?: ReactNode;
  /**
   * Which half of the window is in front: the conversation or the code.
   *
   * Here rather than in the rail because it is the same kind of choice the tab
   * strip is -- "what am I looking at" -- and it is the one control that
   * *leaves* the transcript, so it belongs beside the tabs it competes with.
   * The rail answers "what can I do"; a mode lives with the view.
   */
  mode?: "agent" | "code" | "trajectory";
  onModeChange?: (mode: "agent" | "code" | "trajectory") => void;
  /** True when a project is open, so the code half has something to show. */
  canCode?: boolean;
}

export function TopBar({
  busy,
  tabs = [],
  active = "",
  onSelect,
  onClose,
  onNewTab,
  onRename,
  controls,
  modelSelector,
  mode = "agent",
  onModeChange,
  canCode = true,
}: Props) {
  /** The tab whose name is being typed, and what has been typed so far. */
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  /** The tab menu, and what it was asked for against -- the pointer, here. */
  const [menu, setMenu] = useState<{ id: string; anchor: MenuBounds } | null>(
    null,
  );
  const inputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (editing !== null) inputRef.current?.focus();
  }, [editing]);

  // Escape, or a press anywhere else, puts the menu away -- and a press *inside*
  // it is the menu being used rather than dismissed, which is the bug all three
  // surfaces had before `useDismiss` existed.
  useDismiss(menu !== null, () => setMenu(null), menuRef);

  // Placed during the render: this menu is fixed to the window and anchored to
  // a point, so both boxes are known without waiting for a layout pass. See the
  // same call in `ConversationList`, which is the same menu on the same kind of
  // target -- they opened in two different places once already.
  const placed = menu ? placeFixedMenu(menu.anchor, MENU_GAP) : null;

  /** Keep the typed name, or throw it away. Both close the editor. */
  const commitRename = (save: boolean) => {
    const id = editing;
    const name = draft.trim();
    setEditing(null);
    setDraft("");
    // A blank name is refused rather than saved: the core rejects it, and an
    // editor that closed on a name nothing accepted would look like it worked.
    if (save && id && name) onRename?.(id, name);
  };

  const row = (id: string) => tabs.find((tab) => tab.id === id);

  return (
    <header
      className={`topbar ${DRAG_REGION_CLASS}`}
      onContextMenu={(event) => {
        // No window, no menu: in a browser preview the right-click belongs to
        // whatever the page has, which is the honest answer there.
        if (!controls) return;
        event.preventDefault();
        controls.showSystemMenu();
      }}
    >
      {/*
        The app's mark, in the window's top-left corner.

        `AppMark` rather than an inline glyph: the taskbar icon and the first-run
        state draw the same drawing, and two copies of a logo are how one of them
        ends up out of step. `AppMark.test.tsx` compares the
        component's geometry against `icon.svg`, so this corner and the taskbar
        cannot disagree.

        It is a drag region like the rest of the bar's empty surface -- the class
        has to be on the element a press lands on, and 64x52 of dead title bar
        would be the one patch of the window that cannot be dragged by.
      */}
      <div className={`topbar-mark ${DRAG_REGION_CLASS}`}>
        <AppMark size={22} />
      </div>
      {/*
        The strip: one tab per open chat, then the way to open another.

        **Nothing in here is a drag region, and that is the change.** The class
        was on the tab and on its title when the tab was a label; a tab is a
        control now, and a press moves the window only when it lands on an
        element carrying the class *itself* -- so leaving it on would turn every
        click on a tab into a window drag. The bar's own background either side
        of the strip is what the window is moved by.
      */}
      <div className="tabs">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`tab${tab.id === active ? " is-active" : ""}`}
            onContextMenu={(event) => {
              // Rename and close live here rather than as controls on the tab:
              // a tab is a title you click, and two glyphs inside every one of
              // them would make the strip a toolbar. The browser puts its tab
              // menu behind this same press.
              event.preventDefault();
              // The same 4px the conversation row's menu leaves. Without it the
              // menu's corner sits exactly on the pointer, so the click that
              // asked for it is already over its first item -- which is how a
              // rename turns into a delete. See `MENU_GAP` in
              // `ConversationList`: this is the same menu on the same kind of
              // target, and it opened in two different places depending on
              // whether the row or the tab was right-clicked. It is the
              // placement that applies it now, on whichever side of the pointer
              // the menu ends up.
              setMenu({ id: tab.id, anchor: pointerBounds(event.clientX, event.clientY) });
            }}
          >
            {/*
              The leading slot: the box the busy ring appears in, reserved in
              every tab rather than only in the busy one.

              It used to be inserted only while busy, and an inserted 12px box
              plus its gap pushed the title 16px sideways the moment a turn
              started -- the name the user was reading moved for a reason that
              had nothing to do with the name. Reserving the box means the ring
              arrives into space that was already there and the title never
              moves; a browser's favicon column is the same mechanism, and this
              is the honest version of it while tabs have no icon of their own.
            */}
            <span className="tab-lead">
              {tab.id === active && busy && (
                <span className="tab-spinner" aria-label="Working" />
              )}
            </span>
            {editing === tab.id ? (
              <input
                ref={inputRef}
                className="tab-input"
                value={draft}
                aria-label="Chat name"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitRename(true);
                  } else if (event.key === "Escape") {
                    event.preventDefault();
                    commitRename(false);
                  }
                }}
                onBlur={() => commitRename(true)}
              />
            ) : (
              <button
                type="button"
                className="tab-open"
                onClick={() => onSelect?.(tab.id)}
                title={tab.title || "New chat"}
              >
                <span className="tab-title">{tab.title || "New chat"}</span>
              </button>
            )}
            <button
              type="button"
              className="tab-close"
              onClick={() => onClose?.(tab.id)}
              title="Close tab"
              aria-label={`Close ${tab.title || "this chat"}`}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
        ))}
      </div>

      {/*
        The divider and the "+", beside the strip rather than inside it.

        The strip scrolls now that a tab keeps a width it can be read at, and a
        "+" at the end of scrolling content is a "+" that a full strip hides --
        the one control the user needs *more* the more tabs there are would be
        the one that left. Out here it stays put however far the strip is
        scrolled, which is what a browser does with its own.

        The divider still belongs to the tabs: it is they that give it a left
        side, so an empty strip draws none and the "+" stands alone.
      */}
      {onNewTab && (
        <>
          {tabs.length > 0 && <div className="tabs-divider" aria-hidden="true" />}
          <button
            type="button"
            className="tab-new"
            onClick={onNewTab}
            title="New chat"
            aria-label="New chat"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </>
      )}

      {menu && (
        <div
          ref={menuRef}
          className="rowmenu"
          role="menu"
          style={{
            ...placed?.offsets,
            maxHeight: placed ? `${placed.placement.maxHeight}px` : undefined,
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
            disabled={!row(menu.id)?.renameable}
            title={
              row(menu.id)?.renameable
                ? undefined
                : "A chat with no messages names itself from the first thing you say"
            }
            onClick={() => {
              const id = menu.id;
              setMenu(null);
              setDraft(row(id)?.title ?? "");
              setEditing(id);
            }}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              const id = menu.id;
              setMenu(null);
              onClose?.(id);
            }}
          >
            Close tab
          </button>
        </div>
      )}
      <div className={`topbar-spacer ${DRAG_REGION_CLASS}`} />
      {/*
        The mode switch. A segmented set rather than one toggle, because every
        state is nameable and a button labelled with the state you are *not* in
        is a button people press the wrong way round. Code is disabled with no
        folder open -- a viewer with nothing to view is a dead end, and the
        tooltip names the missing thing -- while Trajectory reads the same
        traffic in every state, so it is never disabled.
      */}
      <div className="topbar-modes" role="group" aria-label="View">
        <button
          type="button"
          className={`topbar-mode${mode === "agent" ? " is-active" : ""}`}
          aria-pressed={mode === "agent"}
          onClick={() => onModeChange?.("agent")}
        >
          Agent
        </button>
        <button
          type="button"
          className={`topbar-mode${mode === "code" ? " is-active" : ""}`}
          aria-pressed={mode === "code"}
          disabled={!canCode}
          title={canCode ? "Read and edit this project's files" : "Choose a project folder first"}
          onClick={() => onModeChange?.("code")}
        >
          Code
        </button>
        <button
          type="button"
          className={`topbar-mode${mode === "trajectory" ? " is-active" : ""}`}
          aria-pressed={mode === "trajectory"}
          title="Every event the agent produced, in order: calls, arguments, outputs and diffs"
          onClick={() => onModeChange?.("trajectory")}
        >
          Trajectory
        </button>
      </div>
      {modelSelector}
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