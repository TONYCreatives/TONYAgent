/**
 * How much the agent is allowed to do, as a four-rung bar above the composer.
 *
 * **This is a control that changes a real gate, not a label.** The core's
 * `PERMISSIONS` carry the allow-list each level enforces, and the
 * orchestrator refuses a tool that is not on it. A bar that only changed a
 * prompt would produce an agent that says "I won't run that" and then runs it,
 * which is the failure the mode system's own docstring warns about.
 *
 * Three decisions that are not visible in the markup:
 *
 * - **The levels come from the core, not from here.** `permission.list` sends
 *   the ladder. Hardcoding four labels beside four hand-written tool lists is
 *   how the two drift, and the drift would be invisible: the bar would say
 *   "Medium" while the gate enforced something else.
 * - **Each rung says what it permits, in words.** "Low" alone does not say
 *   whether shell commands are reachable, and that is the only thing a user
 *   needs to know about this control. So the expanded row states the
 *   difference between its neighbours rather than repeating the label.
 * - **Full is stated as what it is.** It adds no tool and lifts no gate; it
 *   stops asking. The bar says so, because a control that reads as "maximum
 *   access" when it is really "no more prompts" would be misleading at exactly
 *   the moment the user is deciding whether to trust a folder.
 */

import { useEffect, useRef, useState } from "react";

import { useDismiss } from "./useDismiss.js";

/** One level, as `permission.list` reports it. */
export interface PermissionInfo {
  name: string;
  label: string;
  description: string;
  /**
   * Whether a shell command is reachable at all.
   *
   * Sent as a boolean rather than inferred from prose so the bar can mark the
   * boundary between Medium and High without parsing a sentence.
   */
  runs_commands: boolean;
  /** Whether a destructive tool runs without asking first. */
  skips_confirmation: boolean;
}

export interface PermissionList {
  permissions: PermissionInfo[];
  /** The level the core reports as in force. */
  permission: string;
}

interface Props {
  /** The levels, or null before `permission.list` has answered. */
  list: PermissionList | null;
  /** The level currently in force. */
  value: string;
  /** A turn is in flight; switching is refused while one is. */
  busy: boolean;
  /** The core is not reachable. */
  disabled: boolean;
  onChange: (name: string) => void;
}

/**
 * The rung above the one shown, in words.
 *
 * Says what changes rather than what the level is called. "Runs commands" is
 * the whole difference between Medium and High, and it is the difference a user
 * is actually deciding on.
 */
function gain(here: PermissionInfo, above?: PermissionInfo): string | null {
  if (!above) return null;
  if (!here.runs_commands && above.runs_commands) return "Can run shell commands";
  if (!here.skips_confirmation && above.skips_confirmation) {
    return "Stops asking before each change";
  }
  return null;
}

export function PermissionBar({
  list,
  value,
  busy,
  disabled,
  onChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useDismiss(open, () => setOpen(false), menuRef);

  // Escape closes the popover, and must not also reach whatever else is
  // listening: the composer treats Escape as "abandon what I am typing".
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open]);

  const levels = list?.permissions ?? [];
  const current = levels.find((level) => level.name === value) ?? levels[0];

  // Unread, with nothing to say what is in force: the bar would be a row of
  // greyed segments naming a choice nobody has been told the terms of. Better
  // absent than decorative.
  if (!list || levels.length === 0) return null;

  const index = levels.findIndex((level) => level.name === value);

  return (
    <div className="permbar">
      <button
        type="button"
        className="permbar-trigger"
        onClick={() => setOpen((was) => !was)}
        disabled={disabled || busy}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current?.description ?? ""}
      >
        <span className="permbar-label">Permission</span>
        {/* The four segments: a ladder, not four buttons. Only the selected one
            is filled, so the bar reads as a position rather than as a set of
            independent choices -- which is what it is. */}
        <span className="permbar-steps" aria-hidden="true">
          {levels.map((level, i) => (
            <span
              key={level.name}
              className={`permbar-step${i <= index ? " is-on" : ""}`}
              data-level={level.name}
            />
          ))}
        </span>
        <span className="permbar-value">{current?.label ?? ""}</span>
      </button>

      {open && (
        <div ref={menuRef} className="permmenu" role="listbox" aria-label="Permission">
          {levels.map((level, i) => {
            const difference = gain(level, levels[i + 1]);
            return (
              <button
                key={level.name}
                type="button"
                role="option"
                aria-selected={level.name === value}
                className={`permmenu-item${
                  level.name === value ? " is-active" : ""
                }`}
                onClick={() => {
                  setOpen(false);
                  if (level.name !== value) onChange(level.name);
                }}
              >
                <span className="permmenu-head">
                  <span className="permmenu-name">{level.label}</span>
                  {level.skips_confirmation && (
                    // Spelled out rather than implied. This is the one rung
                    // where an agent may act without asking, and a user who
                    // cannot see that has no way to make an informed choice
                    // about it.
                    <span className="permmenu-warn">no prompts</span>
                  )}
                </span>
                <span className="permmenu-desc">{level.description}</span>
                {difference && (
                  <span className="permmenu-gain">{difference}</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}