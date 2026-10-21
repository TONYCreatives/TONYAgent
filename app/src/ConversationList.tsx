/**
 * The conversation list, as a floating panel beside the icon rail.
 *
 * **It is an overlay with a scrim, exactly like the Files panel.** It used to
 * be an overlay with only a shadow, which made it read as a column that had
 * always been there rather than as something opened over the transcript. The
 * scrim is what says "over", and its click is the dismiss that a docked panel
 * has no way to offer. See the comment on the scrim below for why it stops at
 * the rail rather than covering it.
 *
 * Presentational only: it renders whatever the core reports and calls back.
 * The core owns which conversations exist and what is in them -- a list built
 * from local state would be a second source of truth about exactly the thing
 * most likely to disagree, since it is the one thing that changes while you
 * are looking at it.
 *
 * Rows carry a title and a timestamp and nothing else. The transcripts live in
 * the core; pulling them here to render a sidebar would mean moving every
 * conversation's full history to the window on every launch.
 *
 * The row menu (rename / duplicate / delete) is the whole management surface.
 * Right-click is how you get at it, and the "..." button is the same menu for
 * anyone not holding a mouse button -- a right-click-only control cannot be
 * reached from the keyboard at all, which would make deleting a conversation
 * impossible for exactly the people most likely to have a long list of them.
 *
 * **Opening a conversation is not handled here.** This component fires `onOpen`
 * and lets the parent close the panel, because the panel's lifetime already
 * belongs to the parent -- see `open` below -- and closing it is a decision
 * about the window, not about a list. Doing it here would mean the list unmounts
 * itself, which is the thing `useDelayedUnmount` in `App.tsx` exists to prevent:
 * an unmounted node has no box, so there would be no exit to play.
 *
 * `open` is passed in rather than read here for the same reason. What this
 * component does with `open` is say which way the motion runs, via `data-state`
 * -- the same contract `<Overlay>` and the files panel use, and the reason
 * styles.css can tell an arriving panel from a leaving one.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDelayedUnmount, useLastValue } from "./useDelayedUnmount.js";
import { useDismiss } from "./useDismiss.js";
import { placeFixedMenu, pointerBounds } from "./menuPlacement.js";
import type { MenuBounds } from "./menuPlacement.js";
import { FilesPane } from "./FileSidebar.js";
import type { CoreTreeEntry, FileChange } from "./filetree.js";
import { Gear } from "./Gear.js";

export interface ConversationSummary {
  id: string;
  title: string;
  project: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  /** Which track this conversation belongs to: "chat" or "build". */
  track: string;
}

/**
 * A folder is shown by its name, not its path.
 *
 * The path is what identifies it, and the full one is kept as a `title`
 * wherever this is drawn, because two folders called `api` in different trees
 * are the same label otherwise -- and which of the two is open is not something
 * a user can work out from a name they chose themselves.
 */
function projectName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const cut = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  return cut >= 0 ? trimmed.slice(cut + 1) : trimmed;
}

/**
 * The rows the sidebar shows: the current folder's chats, and nothing else.
 *
 * **One folder at a time.** The window works in a single project folder, so this
 * list is that folder's conversations rather than a tree of every folder the app
 * has ever been pointed at. A chat is bonded to the folder it is about --
 * `Conversation.project`, which the core persists -- so another folder's chats
 * are not gone, they are somewhere else, and changing back to that folder brings
 * them back. That is why this is a filter and not a delete.
 *
 * **No folder open is not a folder called `""`.** With nothing chosen there is
 * nothing to scope by, so the list shows everything. The alternative -- showing
 * only the chats that have no folder -- would greet a first run with an empty
 * list while the user's real chats sat behind a folder they had not picked yet.
 *
 * **A chat with no folder shows only in that no-folder state.** It is what every
 * conversation saved before `project` existed is; it is a real chat, it is just
 * not about any folder yet.
 *
 * **A chat is listed once it has a message, not when it is created.** The empty
 * conversation the core reuses at boot, and a fresh "+" chat with nothing typed
 * yet, are not chats the list should show: the panel reads as "your chats", so it
 * starts at the first message -- which is also what gives the row its title.
 *
 * Exported because it is the rule the whole feature turns on, and a rule that
 * only exists inside a render is a rule with no test.
 */
export function rowsForFolder(
  conversations: ConversationSummary[],
  project: string,
): ConversationSummary[] {
  // A chat is listed once it has a message. The empty conversation the core
  // reuses at boot, and a "+" chat with nothing typed yet, are left out: the
  // panel is the user's chats, not a shelf of untitled drafts.
  const started = conversations.filter((conversation) => conversation.message_count > 0);
  if (!project) return started;
  return started.filter((conversation) => conversation.project === project);
}

interface Props {
  /**
   * Open, or on its way out.
   *
   * The panel stays mounted after this goes false for the length of the exit
   * animation, so `false` means "closing" rather than "gone" -- which is why it
   * is a `data-state` on the node rather than a decision about whether to
   * render one.
   */
  open: boolean;
  conversations: ConversationSummary[];
  /** The conversation currently open, or "" before the first is created. */
  active: string;
  /**
   * The folder new conversations will be filed under, or "" when none is open.
   *
   * Read here rather than inferred from the rows: a project the user has just
   * opened has no conversations yet, and a list that only knew about projects
   * it could see would not be able to say so.
   */
  project: string;
  busy: boolean;
  connected: boolean;
  /**
   * Put the panel away, from the scrim's click.
   *
   * Owned by the window rather than done here, for the reason `onOpen` is:
   * whether the panel exists is a decision about the window, and closing it
   * from inside would mean this component unmounts itself.
   */
  onDismiss: () => void;
  /** Open the folder picker, to file the next chat somewhere else. */
  onChooseProject: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDuplicate: (id: string) => void;
  /**
   * The rail's own actions, because the panel covers the rail.
   *
   * The sidebar starts at x=0 and hides the rail when it is open (see the
   * module comment), which would otherwise put Search and Settings out of reach.
   * So the panel carries the same two in its foot -- same handlers, same
   * disabled rules as `IconRail` -- because they are the same controls in the
   * panel's own state, not a second set of them.
   */
  onSearch: () => void;
  onSettings: () => void;
  /**
   * Whether a newer version is waiting, for the mark on this foot's gear.
   *
   * The same fact `IconRail` is given, and here for the same reason the two
   * buttons are here at all: this foot *is* the rail while the sidebar covers
   * it, so a mark that only existed on the rail would disappear exactly when
   * this foot is what the user is looking at.
   */
  updateAvailable: boolean;
  /**
   * Which half of the sidebar is showing.
   *
   * The Files tree was its own panel on the other edge of the window; it is a
   * pane of this sidebar now, and the segmented control under the head switches
   * between them. So "which pane" is state of the sidebar, and the App owns it
   * rather than this component, because picking a folder has to be able to
   * switch the sidebar to Files -- which is a decision about the window.
   */
  pane: SidebarPane;
  onPaneChange: (pane: SidebarPane) => void;
  /** The Files pane's tree, filter and folder picker -- see `FilesPane`. */
  files: CoreTreeEntry[];
  /** Per-file change badges, from the agent's own artifacts. */
  fileChanges: Map<string, FileChange>;
  fileFilter: string;
  onFileFilterChange: (value: string) => void;
  onChooseFolder: () => void;
  /** Open a file from the tree in the code viewer. */
  onOpenFile: (path: string) => void;
  /** The walk hit its own bound, and how the read is going. */
  treeTruncated?: boolean;
  treeLoading?: boolean;
  hasProject: boolean;
  /**
   * The Search pane, handed in rather than built here.
   *
   * It is a panel in its own right, with handlers that all live on the App, and
   * this component's job is the sidebar's frame rather than what fills it. It
   * arrives as an element so React mounts it only while its pane is showing: a
   * search panel parked behind a closed pane would run its effects and read a
   * project nobody asked for.
   *
   * The settings page was the other one of these and is not here any more -- see
   * `SidebarPane`, and `SettingsPanel`, which is the window now.
   */
  searchPane?: ReactNode;
}

/**
 * Which face of the sidebar is in front.
 *
 * Chats and Files are peers, and the segmented control under the head is how
 * you move between them. Search is not a peer of those: it is a place you
 * *enter* -- from the foot or from the rail -- so it covers the body rather than
 * sitting beside it, and it swaps the control for a way back instead of lighting
 * a tab.
 *
 * **Settings was the other one, and it left.** It was a pane here at 288px with
 * four tabs across the top, and that row was the constraint the whole panel was
 * built around -- see `SettingsPanel`, which is a page of the window now. What
 * is left of the pair is a single "place you enter", which is why the comments
 * around it read as though they were written for one.
 */
export type SidebarPane = "chats" | "files" | "search";

/**
 * Relative time, coarse on purpose.
 *
 * A sidebar is scanned, not read. "4m ago" answers the only question a scan
 * asks -- is this the one I was just in -- and a full timestamp is four times
 * the width for information nobody uses at that distance.
 */
function when(timestamp: number): string {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w`;
  return new Date(timestamp * 1000).toLocaleDateString();
}

interface Menu {
  id: string;
  /**
   * What the menu is placed against: the row's own button as a box, or the
   * pointer as a rectangle with no size.
   *
   * The placement turns this into offsets rather than the component doing it,
   * which is what lets the same menu open upward when it is asked for near the
   * bottom of a short window -- it used to open downward unconditionally, and
   * Delete ended up outside the client rect.
   */
  anchor: MenuBounds;
}

export function ConversationList({
  open,
  conversations,
  active,
  project,
  busy,
  connected,
  onDismiss,
  onChooseProject,
  onOpen,
  onDelete,
  onRename,
  onDuplicate,
  onSearch,
  onSettings,
  updateAvailable,
  pane,
  onPaneChange,
  files,
  fileChanges,
  fileFilter,
  onFileFilterChange,
  onChooseFolder,
  onOpenFile,
  treeTruncated,
  treeLoading,
  hasProject,
  searchPane,
}: Props) {
  /** The conversation being renamed, or null. */
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  /**
 * How far below the point that opened it the row menu sits.
 *
 * A menu whose corner is exactly on the cursor puts the pointer on its own first
 * item, so the click that opened it is also the click that chooses something --
 * which is how a rename turns into a delete. Four pixels clears the arrow.
 *
 * One constant rather than a number at each call site, because the row's button
 * and a right-click on the row have to agree about it: they were 4 and 0, and
 * the same menu opened in two different places depending on how it was asked
 * for.
 *
 * It is read by the *placement* now instead of being added to the coordinates
 * by each caller, because the direction is no longer known at the call site:
 * the gap has to be part of the measurement for the same reason it is part of
 * the position.
 */
const MENU_GAP = 4;

const [openMenuAt, setOpenMenuAt] = useState<Menu | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // `openMenuAt` is the menu that is open *and where it was opened from*; it
  // doubles as the open flag, so dismissing it clears the row it belonged to.
  // `menu` is what the node renders, and it outlives the dismissal so the exit
  // animation has something to fade out from the right place -- a menu that
  // slid back to the window origin on its way out would be worse than one that
  // simply vanished.
  const menu = useLastValue(openMenuAt);
  const menuMounted = useDelayedUnmount(openMenuAt !== null);
  // The menu node, so a press on one of its items is the item being pressed
  // rather than the menu being dismissed underneath it. Shared with the model
  // picker and the budget popover, which had the same unguarded listener.
  const menuNodeRef = useRef<HTMLDivElement | null>(null);

  const rows = useMemo(
    () => rowsForFolder(conversations, project),
    [conversations, project],
  );

  /**
   * The folder the next chat will be filed under, and the folder this list is
   * showing -- the same one, which is the point of the whole feature.
   *
   * Read from `project` rather than derived from the rows: a folder can be open
   * before it has any conversations, and a label taken off the rows would say
   * "no project" at exactly the moment the user is deciding where to type.
   */
  const projectLabel = project ? projectName(project) : "";

  const openMenu = (id: string, anchor: MenuBounds) =>
    setOpenMenuAt({ id, anchor });
  const closeMenu = () => setOpenMenuAt(null);

  /**
   * Whether a conversation's name can be chosen by hand.
   *
   * A chat with no messages has a placeholder name, and the core replaces it with
   * the first thing the user says -- but only while the name is still "New chat".
   * So a name typed into an empty chat is a name that chat can never outgrow,
   * which is worse than not being allowed to type one. The tab's own menu refuses
   * it for the same reason, from the same field.
   */
  const renameable = (id: string) =>
    (conversations.find((c) => c.id === id)?.message_count ?? 0) > 0;

  useEffect(() => {
    if (editing !== null) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  // The menu is anchored to a click, so anything else that happens closes it:
  // a click elsewhere, Escape, or the window losing focus. A menu that only
  // closes on a second right-click is one a user has to hunt for the exit to.
  //
  // Keyed on `openMenuAt`, not on `menu`: `menu` is retained so the node can
  // animate out, which means it never returns to null, and an effect watching
  // it would leave its listeners on the window for the rest of the session.
  // What they are for is the time the menu is *open*, so that is what they
  // watch.
  useDismiss(openMenuAt !== null, closeMenu, menuNodeRef);

  // A resize is its own case: the menu is positioned in page pixels against a
  // window that just changed size, so it would be left pointing at the wrong
  // row. Closing it is the honest answer, because there is nothing to re-anchor
  // it to.
  useEffect(() => {
    if (!openMenuAt) return;
    window.addEventListener("resize", closeMenu);
    return () => window.removeEventListener("resize", closeMenu);
  }, [openMenuAt]);

  const startRename = (conversation: ConversationSummary) => {
    setEditing(conversation.id);
    setDraft(conversation.title);
  };

  /**
   * Commit the edit, or throw it away.
   *
   * A blank name is refused here rather than sent and refused there, so the
   * input stays open with what was typed: closing it on a rejected save loses
   * the text, and the title is the only thing identifying the conversation.
   */
  const commitRename = (keep: boolean) => {
    if (editing === null) return;
    const title = draft.trim();
    const id = editing;
    if (keep && title) {
      setEditing(null);
      onRename(id, title);
      return;
    }
    if (keep && !title) return; // Blank: stay open, keep the draft.
    setEditing(null);
  };

  /**
   * Where the open menu goes, and how tall it may be.
   *
   * Computed during the render rather than measured in a layout effect, which
   * is the one way this differs from the model picker's menu: this one is fixed
   * to the window and anchored to a point, so its box and its bounds are both
   * already known -- there is no layout to wait for, and no frame in which it
   * would sit in the window's corner.
   *
   * The *retained* menu is what is placed, not the open one: the node outlives
   * the dismissal so the exit animation has something to fade from the right
   * place, and a menu that jumped to the window's corner on its way out would
   * be worse than one that simply vanished.
   */
  const placed = menu ? placeFixedMenu(menu.anchor, MENU_GAP) : null;

  return (
    <>
      {/*
        The scrim, and the reason this panel now has one.

        It floats over the transcript, and a floating panel over the thing the
        window is *for* reads as a mistake rather than as a decision: without
        something dimming what is behind it, 255px of panel looks like a column
        that was always there. The Files panel had this from the start and the
        conversation panel is now built the same way -- scrim, shadow, and a
        click anywhere to dismiss, which is the affordance a docked panel
        cannot have.

        **It covers the transcript only, not the rail.** The rail stays
        operable so the toggle that opened this panel is still reachable, and so
        Stop does not disappear behind a scrim because a side panel is open. A
        full-window scrim here would put the two most important rail buttons --
        stop and settings -- under a backdrop the user then has to dismiss
        before using them.

        `tabIndex={-1}` and `aria-hidden` on the panel's behalf: it is a
        dismiss target, not a control anyone navigates to, and it is reachable
        from the keyboard already through the rail toggle and Escape.
      */}
      <button
        type="button"
        className="chatlist-scrim"
        data-state={open ? "open" : "closed"}
        onClick={onDismiss}
        tabIndex={-1}
        aria-label="Close conversations"
      />
      <nav
      className="chatlist"
      data-state={open ? "open" : "closed"}
      data-pane={pane}
      aria-label="Conversations"
    >
      {/*
        The sidebar's cap: the way back to the rail.

        This is the merge made visible -- the rail is the collapsed state of this
        one sidebar and this panel is its expanded state, so the control that
        puts it away sits here, at the top, exactly where the rail's toggle sits
        when the panel is not covering it.

        The app's mark used to be here too, beside the wordmark. Both moved to
        the title bar's top-left corner when it became clear that this head is
        the one part of the window that is only sometimes on screen: the mark is
        the window's, and a window's mark does not come and go with a panel.
      */}
      <div className="chatlist-head">
        <button
          type="button"
          className="chatlist-toggle"
          onClick={onDismiss}
          title="Close sidebar"
          aria-label="Close sidebar"
        >
          {/*
            The rail's toggle in the sidebar's other state, so it is the rail's
            own frame at the rail's own size -- see `glyph` in `IconRail`. It was
            18px against the rail's 17, which is two drawings of one control at
            two sizes; both are 20 now.
          */}
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 4v16M15 4H3v16h12z" />
          </svg>
        </button>
      </div>

      {pane === "search" ? (
        /*
          The way back, in the tabs' place rather than above them.

          Search is not a third tab -- it is a place you enter and leave -- and
          the control that leaves it belongs where the control that reached it
          was, so the row keeps its height and nothing below it moves when the
          pane changes.
        */
        <div className="chatlist-subhead">
          <button
            type="button"
            className="chatlist-back"
            onClick={() => onPaneChange("chats")}
            title="Back to chats"
            aria-label="Back to chats"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <span className="chatlist-subhead-title">Search</span>
        </div>
      ) : (
        <div className="chatlist-tabs" role="tablist" aria-label="Sidebar">
          <button
            type="button"
            role="tab"
            aria-selected={pane === "chats"}
            className={`chatlist-tab${pane === "chats" ? " is-active" : ""}`}
            onClick={() => onPaneChange("chats")}
          >
            Chats
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={pane === "files"}
            className={`chatlist-tab${pane === "files" ? " is-active" : ""}`}
            onClick={() => onPaneChange("files")}
          >
            Files
          </button>
        </div>
      )}

      {/*
        There is no "New chat" button here any more. A conversation begins from
        the tabs' "+" or, more usually, from simply typing -- the first message
        files it and lists it -- so this panel is the user's chats rather than a
        place to mint empty ones. Starting one on purpose is the "+" by the tabs.
      */}

      {/*
        The folder this list is, named -- and the way to change it.

        It is a button because it has to be. The list is scoped to one folder, so
        the folder is the thing a user needs to be able to move, and the picker
        used to hang off the project group's header, which is gone. Same control,
        same handler, one rung up.

        **Always drawn, empty list or not.** It is the scope of the list rather
        than a property of the rows, and a folder with no chats yet is exactly
        when someone is most likely to want a different one. Hung off the rows,
        that state drew no heading and no way to change folders from this pane at
        all -- measured in the window, as `MISSING`.

        Its `title` is the full path: two folders called `api` in different trees
        are the same label otherwise, and which one is open is not something a
        user can work out from a name they chose themselves.
      */}
      <button
        type="button"
        className="chatlist-label chatlist-folder"
        onClick={onChooseProject}
        title={project || "Choose a project folder"}
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
        <span className="chatlist-folder-name">
          {projectLabel || "All chats"}
        </span>
      </button>

      {rows.length === 0 ? (
        // Silent rather than a placeholder: an empty list with one button in it
        // already says what to do, and a line of text saying "no conversations"
        // just pushes the button down.
        <div className="chatlist-empty" />
      ) : (
        <ul className="chatlist-rows">
          {rows.map((conversation) => (
            <li
              key={conversation.id}
              className={`chatrow${
                conversation.id === active ? " is-active" : ""
              }`}
              onContextMenu={(event) => {
                // The browser's own menu offers "search image for"
                // and "inspect", neither of which means anything on
                // a title.
                event.preventDefault();
                // Below the pointer, like the row's own button: the menu
                // used to open with its corner on the cursor, so the click
                // that asked for it already sat over "Rename".
                openMenu(
                  conversation.id,
                  pointerBounds(event.clientX, event.clientY),
                );
              }}
            >
              {editing === conversation.id ? (
                <input
                  ref={inputRef}
                  className="chatrow-input"
                  value={draft}
                  aria-label="Conversation name"
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
                <>
                  <button
                    type="button"
                    className="chatrow-open"
                    onClick={() => onOpen(conversation.id)}
                    disabled={busy}
                    title={conversation.title}
                  >
                    <span className="chatrow-title">
                      {conversation.title}
                    </span>
                    <span className="chatrow-meta">
                      {when(conversation.updated_at)}
                      {conversation.message_count > 0 && (
                        <> · {conversation.message_count}</>
                      )}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="chatrow-more"
                    onClick={(event) => {
                      // The button's own box, and the placement decides which
                      // side of it the menu goes: below it in a tall window,
                      // above it in a short one.
                      openMenu(
                        conversation.id,
                        event.currentTarget.getBoundingClientRect(),
                      );
                    }}
                    title="Rename, duplicate or delete"
                    aria-label={`Options for ${conversation.title}`}
                    aria-haspopup="menu"
                    aria-expanded={menu?.id === conversation.id}
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                      aria-hidden="true"
                    >
                      <circle cx="5" cy="12" r="1.7" />
                      <circle cx="12" cy="12" r="1.7" />
                      <circle cx="19" cy="12" r="1.7" />
                    </svg>
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {/*
        `menuMounted && menu`, not `openMenuAt`: the node has to outlive the
        dismissal so styles.css can play `menu-out`, and it needs the anchor to
        do it from the right place. `data-state` tells the two apart, and the
        closed state is inert -- see `.rowmenu[data-state="closed"]`.
      */}
      {/*
       * Portalled to the body, and this is load-bearing rather than tidy.
       *
       * `.rowmenu` is `position: fixed` and is placed from *viewport*
       * coordinates -- `clientX/clientY` from a right-click, and a
       * `getBoundingClientRect()` from the row's own button. But `.chatlist`
       * carries a `transform` and a `backdrop-filter`, and either one makes it a
       * containing block for fixed descendants, so "fixed" resolved against the
       * panel instead of the window. The panel starts 52px down, so every menu
       * opened 52px below where it was asked for -- measured: click at y=251,
       * menu at y=307 -- and it would have been offset horizontally too had the
       * panel not happened to sit on x=0.
       *
       * The rule's comment has always claimed it is "fixed to the window... not
       * clipped by the sidebar's overflow". That was the intent; a portal is what
       * makes it true, and it keeps the menu outside the panel's overflow as a
       * side effect.
       */}
      {menuMounted && menu && createPortal(
        <div
          ref={menuNodeRef}
          className="rowmenu"
          role="menu"
          data-state={openMenuAt ? "open" : "closed"}
          style={{
            ...placed?.offsets,
            maxHeight: placed ? `${placed.placement.maxHeight}px` : undefined,
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
            disabled={!renameable(menu.id)}
            title={
              renameable(menu.id)
                ? undefined
                : "A chat with no messages names itself from the first thing you say"
            }
            onClick={() => {
              const target = conversations.find((c) => c.id === menu.id);
              closeMenu();
              if (target) startRename(target);
            }}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              const id = menu.id;
              closeMenu();
              onDuplicate(id);
            }}
          >
            Duplicate
          </button>
          <button
            type="button"
            role="menuitem"
            className="rowmenu-danger"
            onClick={() => {
              const id = menu.id;
              closeMenu();
              onDelete(id);
            }}
          >
            Delete
          </button>
        </div>,
        document.body,
      )}

      {pane === "files" && (
        <FilesPane
          entries={files}
          changes={fileChanges}
          filter={fileFilter}
          onFilterChange={onFileFilterChange}
          onChooseFolder={onChooseFolder}
          onOpenFile={onOpenFile}
          truncated={treeTruncated}
          loading={treeLoading}
          hasProject={hasProject}
        />
      )}

      {pane === "search" && searchPane}

      {/*
        The sidebar's foot: the rail's remaining actions, so closing the rail to
        open the sidebar does not put Search and Settings out of reach. Same
        controls, same order, one rung lower.

        Clear was the third, and it is gone. It was a trash glyph in the panel's
        foot, where it read as "delete this chat" -- and that is not what it did:
        it emptied the transcript you were looking at and left the conversation
        in the list. Deleting a conversation is the row menu's Delete, which says
        so and acts on the row you pointed at. The core's `clear` method is still
        there; nothing in the window calls it now.
      */}
      <div className="chatlist-foot">
        <button
          type="button"
          className="chatlist-act"
          onClick={onSearch}
          disabled={!connected}
          title="Search project"
          aria-label="Search project"
        >
          {/* The rail's Search, one rung lower: the same drawing at the same
              size, because it is the same control in the sidebar's other
              state. */}
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3" />
          </svg>
        </button>
        <button
          type="button"
          className="chatlist-act"
          onClick={onSettings}
          disabled={!connected}
          title={updateAvailable ? "Settings \u2014 a new version is available" : "Settings"}
          aria-label="Settings"
        >
          <Gear size={20} />
          {/* The same mark the rail's gear carries, for the same reason. */}
          {updateAvailable && <span className="rail-dot" aria-hidden="true" />}
        </button>
      </div>
    </nav>
    </>
  );
}
