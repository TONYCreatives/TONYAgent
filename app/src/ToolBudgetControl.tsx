/**
 * The per-turn tool call budget, set from the composer.
 *
 * A popover rather than a settings-panel field because this is a decision a
 * user makes *during* a conversation: they hit the cap, the turn says so, and
 * they raise it and ask again. A dialog they have to find and reopen is a
 * dialog they will not, and the cap stays where it was.
 *
 * The number shown is the core's, never the one last typed. This control sits
 * directly above the tool cards whose badges read "Tool call 3/10", and if it
 * disagreed with them the window would carry two truths about the same number.
 */

import { useEffect } from "react";

import { useDelayedUnmount } from "./useDelayedUnmount.js";

/**
 * Offered as one-click steps rather than a free number field.
 *
 * The values are chosen around what a turn actually does -- a handful of
 * lookups, a real investigation, a long refactor -- so a user can pick the
 * shape of the turn they want without knowing what any number costs. A free
 * field would also work, but it invites 1000, which reads as "unlimited" and
 * is not.
 */
const PRESETS = [3, 5, 10, 20, 50];

interface Props {
  /** The budget the core is holding, or null while it is being read. */
  value: number | null;
  /** Whether the core is reachable. */
  disabled: boolean;
  /** Set once the popover has been dismissed, so it can animate out. */
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onChange: (limit: number) => void;
}

export function ToolBudgetControl({
  value,
  disabled,
  open,
  onOpen,
  onClose,
  onChange,
}: Props) {
  // The node has to outlive the dismissal so styles.css can play the exit,
  // which is the same reason the row menu does not unmount on click.
  const mounted = useDelayedUnmount(open);

  // The popover is anchored to a button, so anything else closes it: a click
  // elsewhere, Escape, the window losing focus. A popover that only closes on
  // its own button is one a user has to hunt for the exit to, and this one
  // sits over the transcript they are trying to read.
  //
  // Keyed on `open`, not on `mounted`: the node outlives the dismissal so it
  // can animate out, so an effect watching it would never see the close and
  // would leave four window listeners behind for the rest of the session.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    // Capture, so a press on the anchor toggles rather than being eaten by
    // this closing on the way through.
    window.addEventListener("pointerdown", onClose, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("pointerdown", onClose, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", onClose);
    };
  }, [open, onClose]);

  return (
    <div className="budget-popover-wrap">
      <button
        type="button"
        className="icon-btn tool-budget-btn"
        onClick={open ? onClose : onOpen}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}            title={
              value === null
                ? "Tool call budget — reading"
                : `Tool call budget: ${value} per turn`
            }
        aria-label="Tool call budget"
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
          <circle cx="12" cy="12" r="3.2" />
          <path d="M12 4.2v2.1M12 17.7v2.1M4.2 12h2.1M17.7 12h2.1" />
        </svg>
      </button>

      {mounted && (
        <div
          className="budget-popover"
          role="dialog"
          aria-label="Tool call budget"
          data-state={open ? "open" : "closed"}
        >
          <p className="budget-popover-title">Tool calls per turn</p>
          <p className="budget-popover-hint">
            Counted one call at a time, so a model asking for five tools in one
            message has spent five. Tools past the limit are refused and the
            turn ends.
          </p>
          <div className="budget-presets" role="group" aria-label="Tool call budget">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={`budget-preset${value === preset ? " is-active" : ""}`}
                // `aria-pressed` rather than a check glyph: this is a
                // single-choice group, and the state is the answer.
                aria-pressed={value === preset}
                disabled={disabled}
                onClick={() => onChange(preset)}
              >
                {preset}
              </button>
            ))}
          </div>
          {value !== null && !PRESETS.includes(value) && (
            // A value set from the environment, or a previous session. Shown
            // rather than silently snapped to a preset, so the control never
            // reports a budget the core is not holding.
            <p className="budget-custom">Currently {value} per turn</p>
          )}
          <button type="button" className="linkish budget-done" onClick={onClose}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}
