/**
 * Choosing a model, from the composer's model chip.
 *
 * The chip used to read "Model -- coming soon" and do nothing when clicked.
 * Everything it needs was already in the core -- `list_models()` fetches the
 * gateway's `/models`, and the dialect knows the URL -- so the only thing that
 * was missing was an RPC to call it through, and a menu to put the answer in.
 *
 * Three decisions that are not visible in the markup:
 *
 * - **Switching is only offered while idle.** A turn in flight has a history
 *   half-built by one model, and binding another mid-turn interleaves their
 *   answers into one conversation. The menu says so rather than being
 *   silently inert.
 * - **The list is fetched once, on first open.** OpenRouter answers with
 *   several hundred entries, and a menu that refetched on every click would
 *   spend a request per click.
 * - **A filter box, because three hundred entries is not a list a person
 *   scans.** It matches on substrings across the namespaced id, which is what
 *   a user actually remembers: "claude", "gpt-5", "qwen".
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { useDismiss } from "./useDismiss.js";
import { useDelayedUnmount } from "./useDelayedUnmount.js";

/** What `models.list` returns. */
export interface ModelList {
  models: string[];
  current: string;
}

interface Props {
  /** The bound model's id, as the core last reported it. */
  model: string;
  /** Whether a turn is in flight. Switching is refused while busy. */
  busy: boolean;
  /** Whether the core is reachable at all. */
  disabled: boolean;
  /** The list, or null while it has not been read yet. */
  list: ModelList | null;
  /** Set when the list could not be read, so the menu can say why. */
  error: string | null;
  onOpen: () => void;
  onClose: () => void;
  onChange: (model: string) => void;
  /** Ask the core for the list. Called at most once per mount. */
  onLoad: () => void;
}

/**
 * The entries matching a filter, in the order the provider sent them.
 *
 * Not re-sorted. The provider groups its ids, and that grouping is the only
 * structure the list has; sorting alphabetically would bury the free models
 * among the paid ones and hide which vendor a name belongs to at a glance.
 */
export function matchingModels(models: string[], filter: string): string[] {
  const needle = filter.trim().toLowerCase();
  if (!needle) return models;
  // Every whitespace-separated term must appear, so "claude sonnet" narrows
  // rather than widening. Matching on the whole string would find nothing.
  const terms = needle.split(/\s+/);
  return models.filter((id) => {
    const haystack = id.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}

/** The id as a short name: the part after the vendor prefix. */
function shortName(id: string): string {
  const slash = id.indexOf("/");
  return slash === -1 ? id : id.slice(slash + 1);
}

export function ModelPicker({
  model,
  busy,
  disabled,
  list,
  error,
  onOpen,
  onClose,
  onChange,
  onLoad,
}: Props) {
  const [filter, setFilter] = useState("");
  // The chip's own open state. Held here rather than in the caller because it
  // is a property of this control: the App has to be able to close it, but
  // nothing else cares whether it is open.
  const [open, setOpen] = useState(false);
  const mounted = useDelayedUnmount(open);
  const filterRef = useRef<HTMLInputElement | null>(null);
  // The wrap, not the menu panel: the chip lives inside it, and a press on the
  // chip is the chip's own toggle. This is also what keeps a press on the
  // filter from dismissing the menu it is the filter for.
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // Whether the list has been asked for. A ref, not state: it gates a fetch
  // and must not itself cause a render, and re-rendering on every open just to
  // remember what was already fetched is how a list gets requested twice.
  //
  // This guard is load-bearing in a way that is easy to undo by accident. The
  // effect depends on `onLoad`, which is an inline arrow in every caller, so
  // it is a new function on every render. Without the ref the effect calls
  // onLoad, the caller's state update re-renders, the arrow is new, the effect
  // runs again -- and the menu fetches until the tab dies. Removing the guard
  // was tried; the test run never finished.
  const loaded = useRef(false);

  function close() {
    setOpen(false);
    onClose();
  }

  function choose(id: string) {
    close();
    onChange(id);
  }

  // Fetched on first open, not on mount. A window that reads several hundred
  // model ids at launch spends a request to render a chip the user may never
  // click, and the core's own reasoning read is the one that has to happen
  // eagerly.
  useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    onLoad();
  }, [open, onLoad]);

  // Anything else closes it: a click elsewhere, Escape, the window losing
  // focus -- but not a click *inside* it, which is the filter being used.
  useDismiss(open, close, wrapRef);

  // The filter is the first thing focused, so a user can type straight away.
  useEffect(() => {
    if (open) filterRef.current?.focus();
    else setFilter("");
  }, [open]);

  const models = list?.models ?? [];
  const shown = useMemo(() => matchingModels(models, filter), [models, filter]);

  function toggle() {
    if (open) {
      close();
      return;
    }
    if (disabled) return;
    setOpen(true);
    onOpen();
  }

  return (
    <div className="modelpicker-wrap" ref={wrapRef}>
      <button
        type="button"
        className="chip"
        onClick={toggle}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={busy ? "Model — stop the turn to switch" : "Choose a model"}
      >
        <span>{model || "No model"}</span>
        <span className="chip-caret">&#9662;</span>
      </button>

      {mounted && (
        <div
          className="modelpicker"
          role="dialog"
          aria-label="Choose a model"
          data-state={open ? "open" : "closed"}
        >
          <input
            ref={filterRef}
            className="modelpicker-filter"
            type="text"
            value={filter}
            placeholder="Filter models..."
            aria-label="Filter models"
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => {
              // Enter picks the first match, which is what a user means by
              // "the one I typed" when the list is three hundred long.
              if (e.key === "Enter" && shown.length > 0) {
                e.preventDefault();
                choose(shown[0]);
              }
            }}
          />

          {/*
            Each state says what is true. A spinner here would claim work is
            happening when the read has failed, and a bare empty list would look
            like a provider with no models.
          */}
          {busy ? (
            <p className="modelpicker-note">
              Stop the turn to switch models. The current one is still answering.
            </p>
          ) : error ? (
            <p className="modelpicker-note is-error">{error}</p>
          ) : list === null ? (
            <p className="modelpicker-note">Loading models...</p>
          ) : shown.length === 0 ? (
            <p className="modelpicker-note">
              {filter
                ? `Nothing matches "${filter}".`
                : "The provider returned no models."}
            </p>
          ) : (
            <ul className="modelpicker-list" role="listbox" aria-label="Models">
              {shown.map((id) => (
                <li key={id}>
                  <button
                    type="button"
                    className={`modelpicker-item${id === model ? " is-current" : ""}`}
                    role="option"
                    aria-selected={id === model}
                    onClick={() => choose(id)}
                  >
                    {/*
                      The vendor is shown separately because the id is
                      namespaced and the vendor is the part that tells you
                      whether you are about to switch to a different family of
                      model.
                    */}
                    <span className="modelpicker-vendor">
                      {id.includes("/") ? id.slice(0, id.indexOf("/")) : ""}
                    </span>
                    <span className="modelpicker-name">{shortName(id)}</span>
                    {id === model && (
                      <span className="modelpicker-current" aria-hidden="true">
                        &#10003;
                      </span>
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
