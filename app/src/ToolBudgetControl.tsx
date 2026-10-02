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

import { useEffect, useRef, useState } from "react";

import { useDelayedUnmount } from "./useDelayedUnmount.js";
import { useDismiss } from "./useDismiss.js";

/**
 * The values on offer as one-click steps.
 *
 * They are chosen around what a turn actually does -- a handful of lookups, a
 * real investigation, a long refactor -- so a user can pick the shape of the
 * turn they want without knowing what any number costs.
 *
 * Presets *and* a free field, not presets instead of one. A budget nobody can
 * express is a budget that gets rounded to the nearest thing on offer, and the
 * person who wants 7 or 80 is the one who already knows something about the
 * cost. What stops "1000, which reads as unlimited" from being a hazard is the
 * field's ceiling and its refusal, not the absence of a field.
 */
const PRESETS = [3, 5, 10, 20, 50];

/**
 * The most tool calls one turn may be asked for.
 *
 * A cap, because the budget is also a bound on what one turn can cost. It is
 * generous: nobody budgets 200 calls and then uses 200.
 */
export const MAX_BUDGET = 200;

/**
 * A typed budget, or the reason it cannot be one.
 *
 * Mirrors `_h_tools_set` rather than deferring to it. The core's rule is that
 * anything below one is an error and not a clamp, and a client that sent a
 * typed 0 and got a refused RPC back would have already taken the focus away
 * from the field to render the failure. Refusing here keeps the popover open
 * with the text still in it.
 *
 * Returns `{ limit }` for a whole number of calls within range, or `{ reason }`
 * phrased for the person who typed it. A discriminated result rather than a
 * nullable number so the caller cannot apply a half-understood one.
 */
export function parseBudget(text: string): { limit: number } | { reason: string } {
  const raw = text.trim();
  if (!raw) return { reason: "Enter how many tool calls a turn may make." };
  // `Number`, not `parseInt`: parseInt("12abc") is 12, which would accept a
  // number the user did not type.
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    return { reason: `"${raw}" is not a number.` };
  }
  if (!Number.isInteger(value)) {
    return { reason: "A turn can only spend whole tool calls." };
  }
  if (value < 1) {
    return { reason: "A turn has to be allowed at least one tool call." };
  }
  if (value > MAX_BUDGET) {
    return { reason: `${MAX_BUDGET} tool calls is the most one turn may make.` };
  }
  return { limit: value };
}

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

  // The wrap, not the popover panel, because the anchor button lives inside
  // it. A press on the anchor is the anchor's own toggle, and if this counted
  // it as a press outside then the button would open a popover that the press
  // has already asked to close.
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // The typed budget, and why the last attempt was refused. Both are local:
  // this field is a draft until the core agrees, and the popover must survive a
  // refusal with the text still in it, which a round trip through the core
  // cannot promise.
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // The field shows the core's value whenever the popover opens, so it reads as
  // "the budget, which you may change" rather than an empty box. Editing it is
  // then an edit of something true.
  useEffect(() => {
    if (open && value !== null) {
      setDraft(String(value));
      setProblem(null);
    }
  }, [open, value]);

  const apply = () => {
    const parsed = parseBudget(draft);
    if ("reason" in parsed) {
      setProblem(parsed.reason);
      return;
    }
    setProblem(null);
    onChange(parsed.limit);
  };

  // The popover is anchored to a button, so anything else closes it: a press
  // elsewhere, Escape, the window losing focus. A popover that only closes on
  // its own button is one a user has to hunt for the exit to, and this one
  // sits over the transcript they are trying to read.
  //
  // Shared with the row menu and the model picker, because all three grew the
  // same listeners and all three grew the same bug this way: the capture-phase
  // pointerdown fires for presses *inside* the popover too, so clicking a
  // preset dismissed it before the preset's own handler was believed.
  useDismiss(open, onClose, wrapRef);

  return (
    <div className="budget-popover-wrap" ref={wrapRef}>
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

          <div className="budget-custom-row">
            <input
              className="budget-custom-input"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_BUDGET}
              step={1}
              value={draft}
              disabled={disabled}
              aria-label="Tool calls per turn"
              // The value is not clamped on change. Typing "0" on the way to
              // "10" has to be able to pass through the field without the
              // field rewriting what was typed under the cursor.
              onChange={(event) => {
                setDraft(event.target.value);
                setProblem(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  apply();
                }
              }}
            />
            <button
              type="button"
              className="budget-custom-apply"
              disabled={disabled}
              onClick={apply}
            >
              Set
            </button>
          </div>
          {problem && (
            // `role="alert"` because it answers the keystroke that caused it:
            // a user who typed 0 and pressed Enter is still looking at the
            // field, not at the place a message would be read.
            <p className="budget-problem" role="alert">
              {problem}
            </p>
          )}
          <button type="button" className="linkish budget-done" onClick={onClose}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}
