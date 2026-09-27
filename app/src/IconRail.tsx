/**
 * Left icon rail.
 *
 * Presentational chrome: the buttons are here because the reference design has
 * them, but they only act where the core already supports the action. Anything
 * the protocol cannot do yet is rendered disabled rather than wired to a stub
 * that silently does nothing -- which is how the Tkinter UI ended up with
 * controls that appeared to work.
 */

import type { ReactNode } from "react";

interface Props {
  connected: boolean;
  busy: boolean;
  messageCount: number;
  onNewChat: () => void;
  onClear: () => void;
  onCancel: () => void;
}

/** Inline SVG so the rail needs no icon dependency or network fetch. */
function Icon({ children }: { children: ReactNode }) {
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
      {children}
    </svg>
  );
}

const PATHS = {
  newChat: "M12 5v14M5 12h14",
  clear: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  stop: "M6 6h12v12H6z",
  sandbox: "M4 7h16v13H4zM9 7V4h6v3",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3",
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
        <Icon>
          <path d={PATHS.newChat} />
        </Icon>
      </button>

      <button
        type="button"
        className="rail-btn"
        onClick={onClear}
        disabled={!connected || busy || messageCount === 0}
        title="Clear conversation"
        aria-label="Clear conversation"
      >
        <Icon>
          <path d={PATHS.clear} />
        </Icon>
      </button>

      {busy && (
        <button
          type="button"
          className="rail-btn is-active"
          onClick={onCancel}
          title="Stop generating"
          aria-label="Stop generating"
        >
          <Icon>
            <path d={PATHS.stop} />
          </Icon>
          <span className="rail-badge">{messageCount || 1}</span>
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
        <Icon>
          <path d={PATHS.sandbox} />
        </Icon>
      </button>

      <button
        type="button"
        className="rail-btn"
        disabled
        title="Search — coming soon"
        aria-label="Search"
      >
        <Icon>
          <path d={PATHS.search} />
        </Icon>
      </button>

      <button
        type="button"
        className="rail-btn"
        disabled
        title="Settings — coming soon"
        aria-label="Settings"
      >
        {/* A gear needs two rings plus eight teeth, so it cannot be a single
            path string. The previous transcription from Feather mixed arc radii
            and left the body unconnected to the teeth, which is what made the
            glyph render as a malformed blob. */}
        <Icon>
          <circle cx="12" cy="12" r="3.2" />
          <circle cx="12" cy="12" r="7" />
          <path d="M19 12h2.5M12 19v2.5M5 12H2.5M12 5V2.5M16.95 16.95l1.77 1.77M7.05 7.05L5.28 5.28M16.95 7.05l1.77-1.77M7.05 16.95l-1.77 1.77" />
        </Icon>
      </button>

      <div className="rail-spacer" />

      <div className="rail-avatar" title="Local session">
        TA
      </div>
    </nav>
  );
}
