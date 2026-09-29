/**
 * Left icon rail, with an optional expanded (fully open) state.
 *
 * Closed: a 70px strip of icons -- the shape the app has always had. Expanded:
 * the rail widens and each button grows a text label, in the manner of the
 * reference design's fully-open sidebar.
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
  /** Fully open: wide rail with text labels. Closed is the icon strip. */
  expanded: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  onClear: () => void;
  onCancel: () => void;
  onSettings: () => void;
  onSearch: () => void;
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
  // Panel with the divider nearer the left edge: matches the reference's
  // toggle, which shows the sidebar "attached on the left".
  toggleOpen: "M3 4v16M9 4h12v16H9z",
  toggleClosed: "M21 4v16M15 4H3v16h12z",
};

interface Item {
  key: string;
  /** Pre-built glyph: some icons (the gear) cannot be a single path string. */
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled: boolean;
  active?: boolean;
  badge?: number;
}

const GEAR = (
  <>
    {/* A gear needs two rings plus eight teeth, so it cannot be a single path
        string. The previous transcription from Feather mixed arc radii and
        left the body unconnected to the teeth, which is what made the glyph
        render as a malformed blob. */}
    <circle cx="12" cy="12" r="3.2" />
    <circle cx="12" cy="12" r="7" />
    <path d="M19 12h2.5M12 19v2.5M5 12H2.5M12 5V2.5M16.95 16.95l1.77 1.77M7.05 7.05L5.28 5.28M16.95 7.05l1.77-1.77M7.05 16.95l-1.77 1.77" />
  </>
);

export function IconRail({
  connected,
  busy,
  messageCount,
  expanded,
  onToggle,
  onNewChat,
  onClear,
  onCancel,
  onSettings,
  onSearch,
}: Props) {
  // Sandbox and settings both open the one settings panel: the project folder
  // and the model are both "what is this window working on", and two modals
  // reaching the same core methods would be two places to keep in sync. Search
  // has its own panel because it is a query with results, not a setting.
  const items: Item[] = [
    {
      key: "new",
      icon: <path d={PATHS.newChat} />,
      label: "New chat",
      onClick: onNewChat,
      disabled: !connected || busy,
    },
    {
      key: "clear",
      icon: <path d={PATHS.clear} />,
      label: "Clear conversation",
      onClick: onClear,
      disabled: !connected || busy || messageCount === 0,
    },
  ];
  if (busy) {
    items.push({
      key: "stop",
      icon: <path d={PATHS.stop} />,
      label: "Stop generating",
      onClick: onCancel,
      disabled: false,
      active: true,
      badge: messageCount || 1,
    });
  }
  items.push(
    {
      key: "sandbox",
      icon: <path d={PATHS.sandbox} />,
      label: "Sandbox",
      onClick: onSettings,
      disabled: !connected,
    },
    {
      key: "search",
      icon: <path d={PATHS.search} />,
      label: "Search project",
      onClick: onSearch,
      disabled: !connected,
    },
    {
      key: "settings",
      icon: GEAR,
      label: "Settings",
      onClick: onSettings,
      disabled: !connected,
    },
  );

  return (
    <nav className={`rail${expanded ? " rail-expanded" : ""}`} aria-label="Primary">
      <button
        type="button"
        className="rail-btn rail-toggle"
        onClick={onToggle}
        title={expanded ? "Close sidebar" : "Open sidebar"}
        aria-label={expanded ? "Close sidebar" : "Open sidebar"}
        aria-expanded={expanded}
      >
        <Icon>
          <path d={expanded ? PATHS.toggleClosed : PATHS.toggleOpen} />
        </Icon>
      </button>

      <div className="rail-logo" title="TONYAgent">
        TA
      </div>

      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className={`rail-btn${item.active ? " is-active" : ""}`}
          onClick={item.onClick}
          disabled={item.disabled}
          title={item.label}
          aria-label={item.label}
        >
          <Icon>{item.icon}</Icon>
          {expanded && <span className="rail-label">{item.label}</span>}
          {item.badge !== undefined && <span className="rail-badge">{item.badge}</span>}
        </button>
      ))}

      <div className="rail-spacer" />

      <div className="rail-avatar" title="Local session">
        TA
      </div>
    </nav>
  );
}
