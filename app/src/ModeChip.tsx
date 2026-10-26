/**
 * The core's mode, as one chip with a menu instead of a row of pills.
 *
 * **Why one control replaced four.** The composer's row held a pill per mode --
 * Build, Plan, Mission, Skills -- and the row was the widest thing in the field
 * after the field itself. At the 400px assistant panel it wrapped; at 640px of
 * window it was the first thing to run out of room. A chip says which mode is in
 * force and opens the list when asked, which is the same choice at a third of
 * the width.
 *
 * **The labels and descriptions are the core's.** The chip never invents a mode
 * or a sentence: `mode.list` supplies both, the window filters by track, and the
 * chip draws what it was handed -- so a mode the core stops offering cannot
 * linger here as a dead row.
 *
 * **The one-mode case is a label, not a menu.** A chat-track conversation has
 * exactly one mode, and a chip that opened a menu with one row in it would be a
 * control pretending there is a choice. It is drawn as a static label with the
 * mode's description on hover, and the composer's hint line already explains a
 * read-only mode in full.
 *
 * The menu opens upward, anchored to the wrapper: the composer is at the foot of
 * the column, so downward is off-screen. It is `position: absolute` rather than
 * fixed because `.composer-inner` is the box the control belongs to -- the same
 * mechanism the tool budget popover uses one control to the right.
 */

import { useEffect, useRef, useState } from "react";

import type { ModeInfo } from "./Composer.js";
import { useDismiss } from "./useDismiss.js";

interface Props {
  /** Modes from the core, already filtered to this conversation's track. */
  modes: ModeInfo[];
  /** The mode actually in force, as the core last reported it. */
  mode: string;
  /** Not connected: nothing can be changed yet. */
  disabled: boolean;
  onModeChange: (name: string) => void;
}

export function ModeChip({ modes, mode, disabled, onModeChange }: Props) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const current = modes.find((m) => m.name === mode) ?? modes[0];

  useDismiss(open, () => setOpen(false), wrapRef);

  // Open on the mode in force rather than on the first row: the menu's job is to
  // answer "what is selected and what else is there", and starting the focus
  // somewhere else makes the selected row something to find.
  const openMenu = () => {
    setIndex(Math.max(0, modes.findIndex((m) => m.name === current?.name)));
    setOpen(true);
  };

  // Focus follows the highlight. These are real buttons, so Enter and Space
  // activate them natively; this is only what makes the arrow keys a menu.
  useEffect(() => {
    if (open) optionRefs.current[index]?.focus();
  }, [open, index]);

  const select = (next: ModeInfo) => {
    setOpen(false);
    buttonRef.current?.focus();
    if (next.name !== current?.name) onModeChange(next.name);
  };

  if (!current) return null;

  if (modes.length <= 1) {
    return (
      <span
        className="modechip is-static"
        title={current.description}
        aria-label={`Mode: ${current.label}`}
      >
        {current.label}
      </span>
    );
  }

  return (
    <div className="modechip-wrap" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className="modechip"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Mode: ${current.label}. Change mode`}
        title={current.description}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openMenu())}
      >
        <span className="modechip-label">{current.label}</span>
        <span className="modechip-caret" aria-hidden="true">
          &#9662;
        </span>
      </button>

      {open && (
        <div
          className="modechip-menu"
          role="menu"
          aria-label="Mode"
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const step = event.key === "ArrowDown" ? 1 : -1;
              setIndex((prev) => (prev + step + modes.length) % modes.length);
            } else if (event.key === "Home" || event.key === "End") {
              event.preventDefault();
              setIndex(event.key === "Home" ? 0 : modes.length - 1);
            } else if (event.key === "Tab") {
              // Tabbing out of a menu closes it; leaving it open behind the
              // caret would cover the field the keyboard just moved to.
              setOpen(false);
            }
          }}
        >
          {modes.map((m, i) => (
            <button
              key={m.name}
              ref={(node) => {
                optionRefs.current[i] = node;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={m.name === current.name}
              tabIndex={-1}
              className={`modechip-option${m.name === current.name ? " is-active" : ""}`}
              onClick={() => select(m)}
            >
              <span className="modechip-option-head">
                <span className="modechip-option-label">{m.label}</span>
                {m.name === current.name && (
                  <span className="modechip-check" aria-hidden="true">
                    &#10003;
                  </span>
                )}
              </span>
              <span className="modechip-option-desc">{m.description}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
