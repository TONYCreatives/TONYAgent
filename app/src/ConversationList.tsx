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

import { useEffect, useMemo, useRef, useState } from "react";
import { useDelayedUnmount, useLastValue } from "./useDelayedUnmount.js";
import { useDismiss } from "./useDismiss.js";

export interface ConversationSummary {
  id: string;
  title: string;
  project: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

/**
 * One project folder, and the conversations filed under it.
 *
 * Derived from the list the core reports rather than kept alongside it. A
 * project is not a thing the user creates -- it is the folder a conversation
 * was started in -- so a separate registry of them would be a second source of
 * truth about a list that changes while you are looking at it, and every way of
 * emptying a project's only conversation would leave an empty folder behind
 * that no longer corresponds to anything.
 */
interface ProjectGroup {
  /** The folder's full path, which is also what identifies it. */
  path: string;
  /** The last path segment: `TONYAgent`, not `C:\Users\...\TONYAgent`. */
  name: string;
  conversations: ConversationSummary[];
}

/**
 * A project is shown by its folder name, not its path.
 *
 * The path is what identifies it and is kept as the `title`, because two
 * projects called `api` in different trees are the same row otherwise -- and
 * which of the two is open is not something a user can work out from a name
 * they chose themselves.
 */
function projectName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const cut = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  return cut >= 0 ? trimmed.slice(cut + 1) : trimmed;
}

/**
 * Group conversations under their project.
 *
 * **The active project goes first, and the rest keep the order the core sent.**
 * The core sorts by most recently updated, so first-seen is newest-first, and
 * that ordering is worth keeping: the project someone is working in is the one
 * whose rows they are most likely scanning for. Pinning the active one keeps it
 * reachable at the top when they are in a different folder, and the rest stay
 * in recency order rather than being re-sorted by name -- alphabetical would
 * bury the project they used yesterday under projects they have not opened in
 * months.
 *
 * Conversations with no project are grouped under `""` rather than dropped. A
 * chat saved before `project` existed, or one started with no folder, is still a
 * real conversation the user can open; hiding it would be the list quietly
 * losing rows.
 */
function groupByProject(
  conversations: ConversationSummary[],
  active: string,
): ProjectGroup[] {
  const byPath = new Map<string, ProjectGroup>();
  for (const conversation of conversations) {
    const path = conversation.project || "";
    let group = byPath.get(path);
    if (!group) {
      group = { path, name: projectName(path), conversations: [] };
      byPath.set(path, group);
    }
    group.conversations.push(conversation);
  }
  const groups = [...byPath.values()];
  // Only reordered when the active project is actually present. Before the
  // first conversation exists there is nothing to pin, and a group list with a
  // hole in it would be a rendering of an absence.
  const index = active ? groups.findIndex((g) => g.path === active) : -1;
  if (index > 0) groups.unshift(...groups.splice(index, 1));
  return groups;
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
  onNew: () => void;
  /** Open the folder picker, to file the next chat somewhere else. */
  onChooseProject: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDuplicate: (id: string) => void;
}

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
  x: number;
  y: number;
}

export function ConversationList({
  open,
  conversations,
  active,
  project,
  busy,
  connected,
  onDismiss,
  onNew,
  onChooseProject,
  onOpen,
  onDelete,
  onRename,
  onDuplicate,
}: Props) {
  /** The conversation being renamed, or null. */
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
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

  /**
   * Which projects are folded away.
   *
   * A set rather than a boolean per project so a group that has not been folded
   * needs no key here at all. Local state, not persisted: it is a view of the
   * list in front of the user, and a fold remembered across launches would hide
   * a project's rows behind a caret nobody can find the state of.
   */
  const [folded, setFolded] = useState<Set<string>>(() => new Set());
  const toggleProject = (path: string) =>
    setFolded((prev) => {
      const next = new Set(prev);
      if (!next.delete(path)) next.add(path);
      return next;
    });

  const groups = useMemo(
    () => groupByProject(conversations, project),
    [conversations, project],
  );

  /**
   * The folder the next chat will be filed under.
   *
   * Shown from `project` rather than from the groups, for the reason given on
   * the prop: a project can be open before it has any conversations, and a
   * label derived from the rows would read "no project" at exactly the moment
   * the user is deciding where to type.
   */
  const projectLabel = project ? projectName(project) : "";

  const openMenu = (id: string, x: number, y: number) => setOpenMenuAt({ id, x, y });
  const closeMenu = () => setOpenMenuAt(null);

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
      aria-label="Conversations"
    >
      <button
        type="button"
        className="chatlist-new"
        onClick={onNew}
        disabled={!connected || busy}
        title={
          projectLabel
            ? `New conversation in ${projectLabel}`
            : "Choose a project folder for the new conversation"
        }
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
        <span>New chat</span>
        {/*
          Naming the project on the button, because "New chat" is now a
          decision about where a conversation lives. A button that silently
          files the chat under whatever folder was open last is how a
          conversation ends up somewhere the user did not mean.
        */}
        <span className="chatlist-new-project">
          {projectLabel || "Choose folder"}
        </span>
      </button>

      {groups.length === 0 ? (
        // Silent rather than a placeholder: an empty list with one button in it
        // already says what to do, and a line of text saying "no conversations"
        // just pushes the button down.
        <div className="chatlist-empty" />
      ) : (
        <>
          <div className="chatlist-label">Projects</div>
          <div className="chatlist-rows">
            {groups.map((group) => {
              const isFolded = folded.has(group.path);
              return (
                <section className="chatproj" key={group.path}>
                  <div className="chatproj-head">
                    <button
                      type="button"
                      className="chatproj-toggle"
                      onClick={() => toggleProject(group.path)}
                      aria-expanded={!isFolded}
                      title={group.path || "No project folder"}
                    >
                      <span className="chatproj-caret" aria-hidden="true">
                        {isFolded ? "▸" : "▾"}
                      </span>
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
                      <span className="chatproj-name">
                        {group.path ? group.name : "No project"}
                      </span>
                    </button>
                    {/*
                      Only on the group new chats actually go into. On any other
                      it would be a lie: the conversation would be created under
                      whatever project is open, not this one.
                    */}
                    {group.path === project && (
                      <button
                        type="button"
                        className="chatproj-add"
                        onClick={onChooseProject}
                        title="Choose a different project folder"
                        aria-label="Choose a different project folder"
                      >
                        +
                      </button>
                    )}
                  </div>
                  {!isFolded && (
                    <ul className="chatproj-rows">
                      {group.conversations.map((conversation) => (
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
                            openMenu(conversation.id, event.clientX, event.clientY);
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
                                  const box = event.currentTarget.getBoundingClientRect();
                                  openMenu(conversation.id, box.left, box.bottom + 4);
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
                </section>
              );
            })}
          </div>
        </>
      )}

      {/*
        `menuMounted && menu`, not `openMenuAt`: the node has to outlive the
        dismissal so styles.css can play `menu-out`, and it needs the anchor to
        do it from the right place. `data-state` tells the two apart, and the
        closed state is inert -- see `.rowmenu[data-state="closed"]`.
      */}
      {menuMounted && menu && (
        <div
          ref={menuNodeRef}
          className="rowmenu"
          role="menu"
          data-state={openMenuAt ? "open" : "closed"}
          style={{ left: menu.x, top: menu.y }}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
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
        </div>
      )}
    </nav>
    </>
  );
}
