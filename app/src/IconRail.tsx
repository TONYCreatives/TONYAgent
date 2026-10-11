/**
 * Left icon rail: a fixed `--rail-w` strip down the window's left edge.
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

import { Gear } from "./Gear.js";

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
  onCancel: () => void;
  onSettings: () => void;
  onSearch: () => void;
  /** Whether the usage dashboard currently owns the main area. */
  dashboardOpen: boolean;
  onDashboard: () => void;
}

/**
 * One glyph, in the rail's own frame.
 *
 * A function returning a node rather than a component wrapping children, and the
 * difference is not stylistic: the gear is a *solid* silhouette and cannot be
 * nested inside this svg. A nested `<svg width="17">` is sized in the parent's
 * user units, so inside a `viewBox="0 0 24 24"` it would come out 17/24 of the
 * box. So every entry carries a complete node and this is how the stroked ones
 * are built.
 *
 * Inline SVG so the rail needs no icon dependency or network fetch.
 */
function glyph(children: ReactNode): ReactNode {
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
  stop: "M6 6h12v12H6z",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3",
  // A baseline with three bars over it, which is the whole idea of the view
  // and is not the same shape as anything else in this strip.
  usage: "M4 20h16M8 20v-7M12 20v-12M16 20v-4",
  terminal: "M4 17l6-5-6-5M12 19h8",
  // Panel with the divider nearer the left edge: matches the reference's
  // toggle, which shows the sidebar "attached on the left".
  toggleOpen: "M3 4v16M9 4h12v16H9z",
  toggleClosed: "M21 4v16M15 4H3v16h12z",
};

interface Item {
  key: string;
  /**
   * The whole glyph, already drawn -- see `glyph`.
   *
   * A node rather than a path string, because the gear is not a stroked path at
   * all: it is a filled silhouette, and it is the one entry that cannot go
   * through the shared frame.
   */
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled: boolean;
  active?: boolean;
  badge?: number;
}

export function IconRail({
  connected,
  busy,
  messageCount,
  expanded,
  onToggle,
  onCancel,
  onSettings,
  onSearch,
  dashboardOpen,
  onDashboard,
}: Props) {
  // No Sandbox entry. It used to sit directly above Settings and open the same
  // panel, so two labels led to one destination and neither could be the obvious
  // choice. The panel already covers the project folder and the sandbox together
  // -- both are "what is this window working on" -- so one entry says that once.
  // Search keeps its own panel because it is a query with results, not a setting.
  // No "New chat" entry: the conversation panel owns that action, and two
  // controls for one action is duplication rather than choice.
  //
  // No "Clear" entry either. It was a trash glyph in the middle of the strip,
  // and clearing is not a rail action: it is something you do *to a
  // conversation*, so it belongs beside the list it acts on -- which is where
  // the sidebar's own foot already carries it. In the rail it read as "delete",
  // and it sat between the logo and Search, where a reach for Search could land
  // on it.
  const items: Item[] = [];
  if (busy) {
    items.push({
      key: "stop",
      icon: glyph(<path d={PATHS.stop} />),
      label: "Stop generating",
      onClick: onCancel,
      disabled: false,
      active: true,
      badge: messageCount || 1,
    });
  }
  items.push({
    key: "search",
    icon: glyph(<path d={PATHS.search} />),
    label: "Search project",
    onClick: onSearch,
    disabled: !connected,
  });

  // Usage sits with the working actions rather than at the foot with Settings:
  // it is something you look at, not something you configure, and the foot of
  // the strip is reserved for the one entry that is always there.
  items.push({
    key: "usage",
    icon: glyph(<path d={PATHS.usage} />),
    label: "Usage dashboard",
    onClick: onDashboard,
    disabled: !connected,
    active: dashboardOpen,
  });

  /**
   * Settings, held out of the run above so it can be pinned to the foot of the
   * strip.
   *
   * The rail is a full-height flex column of content-sized buttons, so with
   * nothing claiming the free space every icon clusters under the logo and the
   * rest of the strip stands empty -- which leaves the gear floating one row
   * under Search, where a reach for Search can land on it instead. A `flex: 1`
   * spacer after the working actions drops it on the floor, the same mechanism
   * `.topbar-spacer` and `.composer-spacer` use in their own rows.
   *
   * Still last in the DOM, so it is still the last name in the strip: the rail
   * test reads the entries in order, and this is the same order.
   */
  const settings: Item = {
    key: "settings",
    icon: <Gear />,
    label: "Settings",
    onClick: onSettings,
    disabled: !connected,
  };

  /** One entry of the strip. Shared, so the pinned gear is drawn like the rest. */
  const railButton = (item: Item) => (
    <button
      key={item.key}
      type="button"
      className={`rail-btn${item.active ? " is-active" : ""}`}
      onClick={item.onClick}
      disabled={item.disabled}
      title={item.label}
      aria-label={item.label}
    >
      {item.icon}
      {item.badge !== undefined && <span className="rail-badge">{item.badge}</span>}
    </button>
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
        className={`rail-btn rail-toggle${expanded ? " is-active" : ""}`}
        onClick={onToggle}
        title={expanded ? "Close sidebar" : "Open sidebar"}
        aria-label={expanded ? "Close sidebar" : "Open sidebar"}
        aria-expanded={expanded}
      >
        {glyph(<path d={expanded ? PATHS.toggleClosed : PATHS.toggleOpen} />)}
      </button>

      {/*
        No mark here, and its absence is deliberate.

        The rail's head used to carry the app's glyph in a `--raised` box: it was
        the plain text "TA" once, then the same drawing `icon.svg` ships. When the
        mark moved to the title bar's corner this copy did not leave with it, so
        the window drew the same glyph twice -- 22px in the corner and 32px here,
        64px apart, which is what made the rail's one read as a second logo rather
        than as the app's mark.

        The corner is the one that is always on screen. This one came and went with
        nothing. `IconRail.test.tsx` asserts the rail has no mark at all, so a
        second copy cannot come back quietly.
      */}

      {items.map(railButton)}

      {/* Takes the strip's free height, which is what puts the gear at its foot. */}
      <div className="rail-spacer" aria-hidden="true" />

      {railButton(settings)}
    </nav>
  );
}
