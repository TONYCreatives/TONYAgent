/**
 * Left icon rail.
 *
 * Presentational chrome: the buttons are here because the reference design has
 * them, but they only act where the core already supports the action. Anything
 * the protocol cannot do yet is rendered disabled rather than wired to a stub
 * that silently does nothing -- which is how the Tkinter UI ended up with
 * controls that appeared to work.
 */

interface Props {
  connected: boolean;
  busy: boolean;
  messageCount: number;
  onNewChat: () => void;
  onClear: () => void;
  onCancel: () => void;
}

/** Inline SVG so the rail needs no icon dependency or network fetch. */
function Icon({ path }: { path: string }) {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

const PATHS = {
  newChat: "M12 5v14M5 12h14",
  clear: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  stop: "M6 6h12v12H6z",
  sandbox: "M4 7h16v13H4zM9 7V4h6v3",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H7a1.7 1.7 0 0 0 1-1.5V1a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V7a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  terminal: "M4 17l6-5-6-5M12 19h8",
};

export function IconRail({
  connected,
  busy,
  messageCount,
  onNewChat,
  onClear,
  onCancel,
}: Props) {
  return (
    <nav className="rail" aria-label="Primary">
      <div className="rail-logo" title="TONYAgent">
        TA
      </div>

      <button
        type="button"
        className="rail-btn"
        onClick={onNewChat}
        disabled={!connected || busy}
        title="New chat"
        aria-label="New chat"
      >
        <Icon path={PATHS.newChat} />
      </button>

      <button
        type="button"
        className="rail-btn"
        onClick={onClear}
        disabled={!connected || busy || messageCount === 0}
        title="Clear conversation"
        aria-label="Clear conversation"
      >
        <Icon path={PATHS.clear} />
      </button>

      {busy && (
        <button
          type="button"
          className="rail-btn is-active"
          onClick={onCancel}
          title="Stop generating"
          aria-label="Stop generating"
        >
          <Icon path={PATHS.stop} />
        </button>
      )}

      {/* Sandbox and search are in the reference design but have no protocol
          method for a project path yet, so they are shown disabled rather than
          pretending to work. See NEXT_SESSION.md section 7.2. */}
      <button
        type="button"
        className="rail-btn"
        disabled
        title="Sandbox — coming soon"
        aria-label="Sandbox"
      >
        <Icon path={PATHS.sandbox} />
      </button>

      <button
        type="button"
        className="rail-btn"
        disabled
        title="Search — coming soon"
        aria-label="Search"
      >
        <Icon path={PATHS.search} />
      </button>

      <button
        type="button"
        className="rail-btn"
        disabled
        title="Settings — coming soon"
        aria-label="Settings"
      >
        <Icon path={PATHS.settings} />
      </button>

      <div className="rail-spacer" />

      {messageCount > 0 && <span className="rail-badge">{messageCount}</span>}
      <div className="rail-avatar" title="Local session">
        TA
      </div>
    </nav>
  );
}
