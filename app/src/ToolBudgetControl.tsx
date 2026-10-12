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

import { Gear } from "./Gear.js";
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

/**
 * The budget in force, in words, for the heading row.
 *
 * Two values are not numbers and must not be drawn as one: zero is the sentinel
 * for "no limit", and a null is the core not having answered yet. "0 per turn"
 * would report the opposite of what the core is holding, and "null" would be a
 * hole in the sentence.
 */
function budgetWords(value: number): string {
  return value === 0 ? "no limit" : `${value} per turn`;
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
                : value === 0
                  ? "Tool call budget: no limit"
                  : `Tool call budget: ${value} per turn`
            }
        aria-label="Tool call budget"
      >
        {/*
          The sidebar's gear, not a glyph of this control's own.
         
          It was four ticks around a dot -- a dial, which is what the thing
          *is* and not what it opens. A gear is the window's own word for "a
          setting you can change", and this button opens a popover that changes
          one, so it says the same thing the rail's Settings does.
         
          A node rather than a path: `Gear` is a filled silhouette and cannot be
          nested inside a stroked svg of a different viewBox -- see the note on
          `glyph` in `IconRail`, which has the same constraint.
        */}
        <Gear />
      </button>

      {mounted && (
        <div
          className="budget-popover"
          role="dialog"
          aria-label="Tool call budget"
          data-state={open ? "open" : "closed"}
        >
          {/*
            The heading row: what this is, and what it is set to.

            The value in force used to be a sentence of its own -- "Currently 7
            per turn" -- that appeared only for a budget no preset covers, which
            meant the one number a reader most needs (the one in force, while a
            draft sits in the field below) was the one usually absent. It is a
            word beside the title now, and it is always there: the head says
            what the core is holding whether or not a pill is lit.
          */}
          <div className="budget-popover-head">
            <p className="budget-popover-title">Tool calls per turn</p>
            <span className="budget-current">
              {value === null ? "reading…" : budgetWords(value)}
            </span>
          </div>

          {/*
            Every answer, one grid: the five counts and the sentinel.

            "No limit" was a full-width button under the pills, which made it
            read as a second control rather than as the sixth answer -- and at
            six equal widths in this popover it would have been left 31px,
            which the words do not fit in. Three columns of two gives it the
            width it needs and the grid the row never had. Zero on the wire
            means no limit; see `AgentSession.set_max_tool_calls`.
          */}
          <div className="budget-grid" role="group" aria-label="Tool call budget">
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
            <button
              type="button"
              className={`budget-preset-none${value === 0 ? " is-active" : ""}`}
              aria-pressed={value === 0}
              disabled={disabled}
              onClick={() => onChange(0)}
            >
              No limit
            </button>
          </div>

          <div className="budget-custom-row">
            <input
              className="budget-custom-input"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_BUDGET}
              step={1}
              value={draft}
              aria-label="Tool calls per turn"
              disabled={disabled}
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
          {/*
            The explanation is a footnote, not a preamble.

            It was four lines of prose between the title and the choices, so
            the thing a reader came for -- the number, and what it is set to --
            was the second thing down and the paragraph was the first. Under
            the controls it still answers "what does the limit do", which is a
            question asked after the value is set rather than before.
          */}
          <p className="budget-popover-hint">
            One call at a time: five tools in one message is five. Past that,
            calls are refused and the turn ends.
          </p>
          {/*
            A real button, not a link. It was `.linkish` -- the same treatment the
            status bar uses for "Logs" -- which in the footer of a popover read as
            body text that happened to be clickable rather than as the way out.
            `.btn` is what every other dismiss in this window is.
          */}
          <button type="button" className="btn budget-done" onClick={onClose}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}
