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
import { RailViewButton, type ViewMode } from "./ViewSwitch.js";

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
  /** Whether the desktop pet's card is on screen. */
  petOpen: boolean;
  onPet: () => void;
  /**
   * Whether a newer version is waiting to be installed.
   *
   * The rail's job here is only to say *that* there is one: the answer, the
   * release notes and the button all live in the settings panel's App tab, and a
   * second copy of them in a strip of icons would be a worse place to read any
   * of it. A mark on the gear is the whole contribution -- without it the update
   * is only discoverable by opening the panel and looking.
   */
  updateAvailable: boolean;
  /**
   * Which workspace is in front, for the strip's compact switch.
   *
   * The rail is the nav's collapsed state at 1100 and below, in every mode --
   * including Trajectory, which is a workspace beside Agent rather than a page
   * with the window to itself. Without this control the only way out of
   * Trajectory was to open the nav first, and on a window where the nav is an
   * overlay that is a panel you have to find before you can leave.
   */
  view: ViewMode | "settings";
  /** True when a project is open, so the code half has something to show. */
  canCode: boolean;
  onViewChange: (mode: ViewMode) => void;
}

/**
 * One glyph, in the rail's own frame.
 *
 * A function returning a node rather than a component wrapping children, and the
 * difference is not stylistic: the gear is a *solid* silhouette and cannot be
 * nested inside this svg. A nested `<svg width="20">` is sized in the parent's
 * user units, so inside a `viewBox="0 0 24 24"` it would come out 20/24 of the
 * box. So every entry carries a complete node and this is how the stroked ones
 * are built.
 *
 * **20px and a 2px stroke, up from 17 and 1.7.** The target is 44px, so 17 was
 * 39% of it -- a small mark floating in a big disc -- while the sidebar's foot
 * was already 17 in 38px, which is 45%. 20 in 44 is that same 45%, so the two
 * states of one sidebar fill their buttons alike.
 *
 * The stroke is in the frame's own units, so what lands on screen is
 * `strokeWidth * size / 24`. 2 at 20px draws 1.67px against 1.2px before, and
 * that is the half of "bigger and thicker" a size alone cannot do: a glyph that
 * grew 18% and kept its stroke would draw 1.42px -- the same 18% more line -- and
 * read exactly as thin as it does now.
 *
 * Inline SVG so the rail needs no icon dependency or network fetch.
 */
function glyph(children: ReactNode): ReactNode {
  return (
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
  // The app's own T, with eyes: the pet is drawn from the same two strokes
  // everywhere else, and this strip is the one place a 17px version of it is
  // needed. The two `h.01` ticks are dots -- the round linecap turns a zero-length
  // horizontal segment into one -- sitting above the crossbar as eyes.
  pet: "M9 5h.01M15 5h.01M6 9h12M12 9v10",
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
  /**
   * A tooltip that says more than the label does, for a button whose mark needs
   * explaining.
   *
   * **`aria-label` stays the label.** A mark is decoration on a control that is
   * already named, and a screen reader given "Settings — a new version is
   * available" as the *name* would lose the word it navigates the rail by.
   */
  hint?: string;
  /**
   * A dot in the corner.
   *
   * Distinct from `badge`, which carries a count: this is a yes-or-no, so it is
   * a disc with nothing in it rather than a number that happens to be small.
   */
  dot?: boolean;
  onClick: () => void;
  disabled: boolean;
  active?: boolean;
  badge?: number;
}

/**
 * The three workspaces, drawn in the rail's own frame.
 *
 * One current-view button needs all three, because the menu shows the choice
 * rather than only the state -- the glyph has to change when the menu does.
 * A bubble, a pair of angle brackets and a trace: three shapes that are told
 * apart at a glance in a 20px strip, and none of them is the usage chart's
 * baseline or the search mark beside them.
 */
const VIEW_GLYPHS: Record<ViewMode, ReactNode> = {
  agent: glyph(
    <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  ),
  code: glyph(<path d="M9 8l-5 4 5 4M15 8l5 4-5 4" />),
  trajectory: glyph(<path d="M3 12h3l2-6 3.5 12L15 10l2 2h4" />),
};

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
  petOpen,
  onPet,
  updateAvailable,
  view,
  canCode,
  onViewChange,
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

  // The pet, beside the working actions rather than at the foot with Settings:
  // what it shows is the work, and it is the entry you reach for while the agent
  // is busy -- which is the moment the strip is otherwise all "Stop".
  //
  // Enabled without the core, unlike its neighbours. This opens a *window*, which
  // the shell can do whether or not a core is running; a card that said "waiting"
  // with no core is the truth, and a disabled control that could do its job is the
  // failure this file was written to avoid.
  items.push({
    key: "pet",
    icon: glyph(<path d={PATHS.pet} />),
    label: petOpen ? "Hide desktop pet" : "Show desktop pet",
    onClick: onPet,
    disabled: false,
    active: petOpen,
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
    // The same 20px the stroked entries above are drawn at. The gear is a solid
    // silhouette rather than a frame with a stroke, so it carries its own size
    // -- see `Gear`, which is drawn at 17px in the composer's row and 20 here.
    icon: <Gear size={20} />,
    label: "Settings",
    // The dot says a version is waiting without the panel being opened; the
    // tooltip says what the mark means, because a dot on a gear is not
    // self-explaining.
    hint: updateAvailable ? "Settings \u2014 a new version is available" : undefined,
    dot: updateAvailable,
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
      title={item.hint ?? item.label}
      aria-label={item.label}
    >
      {item.icon}
      {item.badge !== undefined && <span className="rail-badge">{item.badge}</span>}
      {item.dot && <span className="rail-dot" aria-hidden="true" />}
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

      {/* The nav's switch, in its collapsed form: which workspace is in front,
          and the three of them behind it. See `RailViewButton`. */}
      <RailViewButton
        mode={view}
        canCode={canCode}
        onChoose={onViewChange}
        glyphs={VIEW_GLYPHS}
      />

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
