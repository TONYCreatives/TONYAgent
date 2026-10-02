/**
 * The conversation list, docked above the icon rail.
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
 */

import { useEffect, useRef, useState } from "react";
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

interface Props {
  conversations: ConversationSummary[];
  /** The conversation currently open, or "" before the first is created. */
  active: string;
  busy: boolean;
  connected: boolean;
  onNew: () => void;
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
  conversations,
  active,
  busy,
  connected,
  onNew,
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
    <nav className="chatlist" aria-label="Conversations">
      <button
        type="button"
        className="chatlist-new"
        onClick={onNew}
        disabled={!connected || busy}
        title="New conversation"
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
      </button>

      {conversations.length === 0 ? (
        // Silent rather than a placeholder: an empty list with one button in it
        // already says what to do, and a line of text saying "no conversations"
        // just pushes the button down.
        <div className="chatlist-empty" />
      ) : (
        <ul className="chatlist-rows">
          {conversations.map((conversation) => (
            <li
              key={conversation.id}
              className={`chatrow${
                conversation.id === active ? " is-active" : ""
              }`}
              onContextMenu={(event) => {
                // The browser's own menu offers "search image for" and
                // "inspect", neither of which means anything on a title.
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
                    <span className="chatrow-title">{conversation.title}</span>
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
  );
}
