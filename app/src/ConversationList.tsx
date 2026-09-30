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
 */

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

export function ConversationList({
  conversations,
  active,
  busy,
  connected,
  onNew,
  onOpen,
  onDelete,
}: Props) {
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
            >
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
              {/*
               * Delete is a second control on the row rather than a menu. A
               * menu would put the only way to remove a conversation behind two
               * clicks, and deleting is the operation people need most when a
               * list gets long.
               */}
              <button
                type="button"
                className="chatrow-delete"
                onClick={() => onDelete(conversation.id)}
                title={`Delete "${conversation.title}"`}
                aria-label={`Delete ${conversation.title}`}
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}