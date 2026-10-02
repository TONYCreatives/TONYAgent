/**
 * Left icon rail: a fixed 52px strip down the window's left edge.
 *
 * It is always that width and always there. It used to widen and grow text
 * labels beside its icons, then widen again to 307px to hold the conversation
 * list underneath it -- neither of which is anything the reference does, whose
 * rail is a strip of icons at every size and whose conversation titles live in
 * a panel beside it. That panel is an overlay now, so the rail's own width
 * never changes and `expanded` says one thing only: whether the panel beside it
 * is open. It still has to reach the toggle's icon, its tooltip and its
 * `aria-expanded`, because those are how the panel's state is announced.
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
  /**
   * The conversation panel beside the rail is open. Does not change this
   * component's own width, which is fixed; it names the toggle's icon, its
   * label and its `aria-expanded`.
   */
  expanded: boolean;
  onToggle: () => void;
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
  clear: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  stop: "M6 6h12v12H6z",
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
  onClear,
  onCancel,
  onSettings,
  onSearch,
}: Props) {
  // No Sandbox entry. It used to sit directly above Settings and open the same
  // panel, so two labels led to one destination and neither could be the obvious
  // choice. The panel already covers the project folder and the sandbox together
  // -- both are "what is this window working on" -- so one entry says that once.
  // Search keeps its own panel because it is a query with results, not a setting.
  // No "New chat" entry: the conversation panel owns that action, and two
  // controls for one action is duplication rather than choice.
  const items: Item[] = [
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
    // No expanded variant of the rail itself, and no `rail-open` class. It used to
    // widen to 236px and grow a text label beside every icon, and then to 307px
    // to hold the conversation list underneath it -- the reference does neither.
    // The rail is a strip of icons at every width; `expanded` now only decides
    // whether the panel beside it is shown, plus this button's own icon and
    // label. The names survive on `title` and `aria-label`, which is where a
    // keyboard user reads them anyway.
    <nav className="rail" aria-label="Primary">
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
          {item.badge !== undefined && <span className="rail-badge">{item.badge}</span>}
        </button>
      ))}
    </nav>
  );
}
