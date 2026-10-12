/**
 * A value chosen from a list, in the popover the composer's model chip uses.
 *
 * This is the settings panel's provider and model rows. Both were native
 * controls -- a `<select>` and a `<input list>` -- and the panel's own note
 * already admitted why the second one was wrong: "The model list is a set of
 * suggestions, not a closed set." A `<datalist>` renders its suggestions in the
 * platform's own popup, which is the one surface in this window that cannot be
 * styled, so the same list looked like a different application depending on
 * whether it was opened from the composer or from here.
 *
 * **The classes are the composer's, deliberately.** `.modelpicker`,
 * `.modelpicker-filter`, `.modelpicker-list`, `.modelpicker-item` are what make
 * this *the same menu* rather than one that resembles it -- a copy of the
 * styling would drift the first time either was touched.
 *
 * Why this is not `ModelPicker` itself: that component is bound to the
 * composer's chip, which refuses to switch while a turn is in flight, fetches
 * the list on first open and shows the vendor as a separate column. None of
 * those are true of a form row, and threading four flags through it to say so
 * would leave one component that is two components.
 *
 * **`allowFreeText` is not a convenience.** The model row promises that any id
 * can be typed, because a self-hosted gateway serves ids the core has never
 * heard of. A picker that only offered what the provider listed would quietly
 * take that away, so a typed value that matches nothing is offered as its own
 * entry, and an empty field offers the provider's default.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { useDismiss } from "./useDismiss.js";
import { useDelayedUnmount } from "./useDelayedUnmount.js";

interface Props {
  /** Names the control and its popover, for a screen reader. */
  label: string;
  /** What is bound now. Empty means the provider's default. */
  value: string;
  options: string[];
  /** Shown on the trigger when nothing is bound. */
  placeholder: string;
  disabled: boolean;
  /** A suffix for one entry -- "(no key)" for a provider without one. */
  describe?: (value: string) => string;
  /**
   * What to *draw* for a value, when the value is not what a person calls it.
   *
   * A theme is `monokai` and is called "Monokai"; a model id is its own name
   * and has no label. Given one, the list drops the vendor column and shows a
   * single label per row: the column exists to separate an id's namespace from
   * its name, and a label has no namespace to separate.
   */
  labelFor?: (value: string) => string;
  /**
   * What to draw on the *trigger*, when it has less room than the menu does.
   *
   * "Dark+ (default dark)" is the right label for a list of themes and 60px
   * too wide for the chip that opens it; the short name is the same theme. Not
   * a fallback for `labelFor` -- a control with no room for the long name is
   * the only reason to pass it.
   */
  triggerLabelFor?: (value: string) => string;
  /** Whether a typed value that matches nothing may be chosen. */
  allowFreeText?: boolean;
  onChange: (value: string) => void;
}

export function ListPicker({
  label,
  value,
  options,
  placeholder,
  disabled,
  describe,
  labelFor,
  triggerLabelFor,
  allowFreeText = false,
  onChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const filterRef = useRef<HTMLInputElement | null>(null);
  const mounted = useDelayedUnmount(open);

  useDismiss(open, () => setOpen(false), wrapRef);

  useEffect(() => {
    // The filter is the first thing focused, so a user can type straight away.
    if (open) filterRef.current?.focus();
  }, [open]);

  const needle = filter.trim().toLowerCase();
  const shown = useMemo(
    () =>
      options.filter((option) =>
        needle ? option.toLowerCase().includes(needle) : true,
      ),
    [options, needle],
  );

  // Offered above the matches, because it is what the user just typed and the
  // list below it is what the provider happens to know about.
  const typed =
    allowFreeText && filter.trim() && !options.includes(filter.trim())
      ? filter.trim()
      : null;

  const choose = (next: string) => {
    setOpen(false);
    setFilter("");
    onChange(next);
  };

  return (
    <div className="modelpicker-wrap settings-picker" ref={wrapRef}>
      <button
        type="button"
        className="chip"
        onClick={() => (open ? setOpen(false) : setOpen(true))}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        title={label}
      >
        <span>
          {value
            ? triggerLabelFor
              ? triggerLabelFor(value)
              : labelFor
                ? labelFor(value)
                : value
            : placeholder}
        </span>
        <span className="chip-caret">&#9662;</span>
      </button>

      {mounted && (
        <div
          className="modelpicker"
          role="dialog"
          aria-label={label}
          data-state={open ? "open" : "closed"}
        >
          <input
            ref={filterRef}
            className="modelpicker-filter"
            type="text"
            value={filter}
            placeholder={`Filter ${label.toLowerCase()}...`}
            aria-label={`Filter ${label.toLowerCase()}`}
            onChange={(event) => setFilter(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                // The typed value first when there is one, then the first
                // match: Enter means "the one I typed", and failing that the
                // one at the top of what it filtered down to.
                if (typed) choose(typed);
                else if (shown.length > 0) choose(shown[0]);
                else if (allowFreeText && !filter.trim()) choose("");
              }
            }}
          />

          {shown.length === 0 && !typed ? (
            <p className="modelpicker-note">
              {filter ? `Nothing matches "${filter}".` : "There is nothing to choose from."}
            </p>
          ) : (
            <ul className="modelpicker-list" role="listbox" aria-label={label}>
              {allowFreeText && !needle && (
                <li>
                  <button
                    type="button"
                    className={`modelpicker-item${value === "" ? " is-current" : ""}`}
                    role="option"
                    aria-selected={value === ""}
                    onClick={() => choose("")}
                  >
                    <span className="modelpicker-name">{placeholder}</span>
                  </button>
                </li>
              )}
              {typed && (
                <li>
                  <button
                    type="button"
                    className="modelpicker-item"
                    role="option"
                    aria-selected={false}
                    onClick={() => choose(typed)}
                  >
                    <span className="modelpicker-vendor">Use</span>
                    <span className="modelpicker-name">{typed}</span>
                  </button>
                </li>
              )}
              {shown.map((option) => (
                <li key={option}>
                  <button
                    type="button"
                    className={`modelpicker-item${option === value ? " is-current" : ""}`}
                    role="option"
                    aria-selected={option === value}
                    onClick={() => choose(option)}
                  >
                    {labelFor ? (
                      <span className="modelpicker-name">{labelFor(option)}</span>
                    ) : (
                      <>
                        <span className="modelpicker-vendor">
                          {option.includes("/") ? option.slice(0, option.indexOf("/")) : ""}
                        </span>
                        <span className="modelpicker-name">
                          {option.includes("/") ? option.slice(option.indexOf("/") + 1) : option}
                          {describe ? describe(option) : ""}
                        </span>
                      </>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
