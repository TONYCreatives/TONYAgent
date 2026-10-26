/**
 * Which workspace is in front: Agent, Code or Trajectory.
 *
 * **The nav owns it, and Code carries the same switch where its nav will be.**
 * It used to sit in the top bar. That bar now holds the tab strip, the track
 * toggle, the status pill, the model chip and the caption, and at 640px -- the
 * window's minimum -- the switch was the one that no longer fit. So it moved to
 * the surface that is *about* where you are: the nav's header. Code has no nav
 * until Phase 5 moves its explorer into the dock, so its explorer head carries
 * the switch in the meantime; that is the corner the nav occupies in Agent, and
 * a mode control that moved to a different corner depending on the mode would be
 * a control to hunt for. Settings hides the app's nav entirely and has its own
 * way back, so it renders no switch.
 *
 * The three workspaces are peers and all three are named, for the reason the
 * top-bar version gave: a single toggle labelled with the state you are *not*
 * in is a control people press the wrong way round.
 *
 * **`settings` lights no segment, and that is deliberate.** The page is not a
 * view *of* the conversation the way these three are -- there is no transcript
 * behind it to come back to by pressing one of them -- so the switch is honest
 * about it, and `settings` is not one of the three it renders.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { placeFixedMenu } from "./menuPlacement.js";
import { useDismiss } from "./useDismiss.js";

/** The three workspaces, and the names the switch uses for them. */
export type ViewMode = "agent" | "code" | "trajectory";

const LABELS: Record<ViewMode, string> = {
  agent: "Agent",
  code: "Code",
  trajectory: "Trajectory",
};

const HINTS: Record<ViewMode, string> = {
  agent: "The conversation, its run panel and the project's files",
  code: "Read and edit this project's files",
  trajectory: "Every event the agent produced, in order: calls, arguments, outputs and diffs",
};

interface Props {
  /** The mode in front. `settings` matches none of the three. */
  mode: ViewMode | "settings";
  /** True when a project is open, so the code half has something to show. */
  canCode: boolean;
  onChange: (mode: ViewMode) => void;
  /** The group's name in the accessibility tree. */
  label?: string;
}

/**
 * The labelled form: a segmented control in the nav's header, or in Code's
 * explorer head while the explorer is still a column of its own.
 *
 * Same stadium language as the sidebar's Chats/Files control and the composer's
 * mode chip, because it is the same kind of choice -- one of these is selected
 * -- and the same `--input` track. It is **not** the top bar's `.topbar-modes`
 * any more: that class is the track toggle's alone now, and a class named for a
 * place it no longer lives in is how a stylesheet starts documenting a layout
 * that stopped existing.
 */
export function ViewSwitch({ mode, canCode, onChange, label = "View" }: Props) {
  return (
    <div className="viewswitch" role="group" aria-label={label}>
      {(Object.keys(LABELS) as ViewMode[]).map((name) => {
        const disabled = name === "code" && !canCode;
        return (
          <button
            key={name}
            type="button"
            className={`viewswitch-option${name === mode ? " is-active" : ""}`}
            aria-pressed={name === mode}
            disabled={disabled}
            title={disabled ? "Choose a project folder first" : HINTS[name]}
            onClick={() => onChange(name)}
          >
            {LABELS[name]}
          </button>
        );
      })}
    </div>
  );
}

/** One row of the rail's view menu. */
export interface ViewMenuItem {
  mode: ViewMode;
  label: string;
  disabled: boolean;
  hint: string;
}

/**
 * The rail's compact form: one button showing the view you are in, and a menu.
 *
 * The rail is 64px and its targets are 44px; three view buttons plus the
 * existing entries would be 540px of a 402px workspace at the window's 480px
 * minimum height, so the strip would lose its settings gear at the bottom.
 * **One control and a menu is the only form that fits**, and it is a deliberate
 * trade: the rail says which workspace you are in at all widths, and changing it
 * is one press plus one choice rather than one press.
 *
 * The glyph is therefore the *current* view's, drawn by the rail in its own
 * frame, and the menu is where the three names live. It is portalled because
 * `.rail` carries a `backdrop-filter`, which makes it a containing block for
 * `position: fixed` descendants -- the same trap the row menus document; without
 * the portal the menu would be positioned against the 64px strip.
 *
 * The dismissal includes **both** the button and the menu as "inside": the
 * button is the toggle, and a capture-phase listener that did not count it would
 * close the menu on the press down and then let the button's click reopen it.
 */
export function RailViewButton({
  mode,
  canCode,
  onChoose,
  glyphs,
}: {
  mode: ViewMode | "settings";
  canCode: boolean;
  onChoose: (mode: ViewMode) => void;
  /** The three drawings, built by the rail so they share its frame. */
  glyphs: Record<ViewMode, ReactNode>;
}) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<ReturnType<typeof placeFixedMenu> | null>(
    null,
  );
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  // One array for the life of the component: `useDismiss` keys its listeners on
  // this value, and a fresh array each render would detach and reattach them.
  const surfaces = useMemo(() => [buttonRef, menuRef], []);

  useDismiss(open, () => setOpen(false), surfaces);

  const current: ViewMode = mode === "settings" ? "agent" : mode;

  const toggle = (button: HTMLButtonElement) => {
    if (open) {
      setOpen(false);
      return;
    }
    setAnchor(placeFixedMenu(button.getBoundingClientRect(), 4));
    setOpen(true);
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="rail-btn rail-view"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`View: ${LABELS[current]}`}
        title={`View: ${LABELS[current]} — switch workspace`}
        onClick={(event) => toggle(event.currentTarget)}
      >
        {glyphs[current]}
      </button>

      {open &&
        anchor &&
        createPortal(
          <div
            ref={menuRef}
            className="viewmenu"
            role="menu"
            aria-label="Workspace"
            style={{
              ...anchor.offsets,
              maxHeight: `${anchor.placement.maxHeight}px`,
            }}
          >
            {(Object.keys(LABELS) as ViewMode[]).map((name) => {
              const disabled = name === "code" && !canCode;
              return (
                <button
                  key={name}
                  type="button"
                  role="menuitemradio"
                  aria-checked={name === current}
                  className={`viewmenu-item${name === current ? " is-active" : ""}`}
                  disabled={disabled}
                  title={disabled ? "Choose a project folder first" : undefined}
                  onClick={() => {
                    setOpen(false);
                    if (name !== current) onChoose(name);
                  }}
                >
                  {LABELS[name]}
                  {name === current && (
                    <span className="viewmenu-check" aria-hidden="true">
                      &#10003;
                    </span>
                  )}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </>
  );
}
