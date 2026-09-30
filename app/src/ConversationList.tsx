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
  const [menu, setMenu] = useState<Menu | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing !== null) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  // The menu is anchored to a click, so anything else that happens closes it:
  // a click elsewhere, a scroll, Escape, or the window losing focus.
  useEffect(() => {
    if (!menu) return;
    const dismiss = () => setMenu(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    // Capture, so a click on another row opens that row's menu rather than
    // being eaten by this one closing.
    window.addEventListener("pointerdown", dismiss, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("blur", dismiss);
    window.addEventListener("resize", dismiss);
    return () => {
      window.removeEventListener("pointerdown", dismiss, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", dismiss);
      window.removeEventListener("resize", dismiss);
    };
  }, [menu]);

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
                setMenu({ id: conversation.id, x: event.clientX, y: event.clientY });
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
                      setMenu({
                        id: conversation.id,
                        x: box.left,
                        y: box.bottom + 4,
                      });
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

      {menu && (
        <div
          className="rowmenu"
          role="menu"
          style={{ left: menu.x, top: menu.y }}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              const target = conversations.find((c) => c.id === menu.id);
              setMenu(null);
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
              setMenu(null);
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
              setMenu(null);
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
