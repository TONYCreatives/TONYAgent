/**
 * The two controls that decide how the agent behaves: how much it may do, and
 * how hard the model may think. Both live in the settings panel, and both are
 * drawn by the one `<ChoiceMenu>` at the bottom of this file.
 *
 * **They share a vocabulary because they are one kind of decision.** A
 * permission level and a thinking effort are both "how much may this window do
 * without asking", and a user reading the two side by side should not have to
 * learn two shapes. Permission already had a menu; Thinking was a native
 * `<select>`, which on Windows is a light box with a system font and a system
 * arrow on a black panel -- the one control in this window that visibly came
 * from somewhere else. So both are rendered from the same parts, which is why
 * there is one component here rather than two that happen to look alike.
 *
 * **Neither of these is a display.** `permission.set` writes the level the
 * orchestrator enforces and `reasoning.set` writes the effort the session
 * sends, so a control that only changed a label would describe a state that
 * does not exist. Each one reads its options from the core and reports the
 * level the core last confirmed, never the one that was clicked.
 *
 * Three things that are not visible in the markup:
 *
 * - **The options come from the core, never from here.** The four permission
 *   rungs carry the tool allow-lists they enforce and the effort names are the
 *   provider's. A hardcoded copy of either would drift the moment the core
 *   changed, and the drift would be invisible: the menu would say "Medium"
 *   over a gate that had since become Full.
 * - **Each rung says what it permits, and what the one above it adds.** "Low"
 *   alone does not say whether a shell command is reachable, and that is the
 *   only thing a user needs to know about this control. The labels are names;
 *   the difference between them is the decision.
 * - **Full is stated as what it is.** It runs any command, not only the
 *   allow-listed ones, and it stops asking. Those are two different powers, so
 *   the row marks both. A control that read as "maximum access" when it is
 *   really "no more prompts" would mislead at exactly the moment the user is
 * deciding whether to trust a folder.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { useDismiss } from "./useDismiss.js";

/**
 * Which way a menu opens, and how tall it may be.
 *
 * Measured rather than declared, because the answer is a fact about where the
 * trigger happens to sit and the panel is a scrolling one. These rows are the
 * panel's first group, so the room below them is large and the room above them
 * is whatever is left of the window -- declaring "up" unconditionally put the
 * menu off the top of the screen, and a menu the user cannot see the end of is
 * a menu whose last option cannot be picked.
 */
export type MenuDirection = "up" | "down";

/**
 * The edges a menu is bounded by.
 *
 * Not a `DOMRect`, because the window's bounds are built here rather than
 * measured -- and because the function below reads two numbers and casting a
 * two-field object to a full rectangle would be a lie the type system could not
 * catch.
 */
export interface MenuBounds {
  top: number;
  bottom: number;
}

/**
 * The side with the most room, and that room as a height.
 *
 * Exported because the decision is worth testing without a layout engine:
 * jsdom reports every rectangle as zero, so the rule has to be a function of
 * numbers rather than something only a browser can exercise. A tie opens down,
 * which is the case the settings panel is actually in.
 */
export function measureMenu(
  trigger: MenuBounds,
  bounds: MenuBounds,
  gap = 6,
): { dir: MenuDirection; maxHeight: number } {
  const above = trigger.top - bounds.top - gap;
  const below = bounds.bottom - trigger.bottom - gap;
  const dir: MenuDirection = above > below ? "up" : "down";
  // Floored rather than taken literally. A height of zero is a menu the user
  // cannot click; a menu slightly taller than its room is one that scrolls, and
  // a scrolling menu still has a readable end.
  return { dir, maxHeight: Math.max(120, dir === "up" ? above : below) };
}

/** One level, as `permission.list` reports it. */
export interface PermissionInfo {
  name: string;
  label: string;
  description: string;
  /**
   * Whether a shell command is reachable at all.
   *
   * Sent as a boolean rather than inferred from prose so the menu can mark the
   * boundary between Medium and High without parsing a sentence.
   */
  runs_commands: boolean;
  /** Whether a destructive tool runs without asking first. */
  skips_confirmation: boolean;
  /**
   * Whether commands outside the allow-list run.
   *
   * A separate boolean rather than something read out of `description`, for the
   * same reason as `runs_commands`: this is the difference between High and
   * Full, and a user picking between them must not have to parse a sentence.
   */
  runs_any_command: boolean;
}

export interface PermissionList {
  permissions: PermissionInfo[];
  /** The level the core reports as in force. */
  permission: string;
}

/** What the bound model says about its own thinking, as `reasoning.list` reports it. */
export interface ReasoningInfo {
  supported: boolean;
  /** Efforts the model accepts, in the provider's own order. */
  efforts: string[];
  default_effort: string;
  /** Whether the model thinks whether or not it is asked to. */
  mandatory: boolean;
  /** The effort in force, or `""` for "whatever the model defaults to". */
  effort: string;
}

/**
 * The rung above the one shown, in words.
 *
 * Says what changes rather than what the level is called. "Runs commands" is
 * the whole difference between Medium and High, and it is the difference a user
 * is actually deciding on. Only the first gain is reported, so the sentence
 * stays one clause wide -- a row listing three of them reads as a warning
 * essay and stops being comparable between rungs.
 */
export function permissionGain(
  here: PermissionInfo,
  above?: PermissionInfo,
): string | null {
  if (!above) return null;
  if (!here.runs_commands && above.runs_commands) return "Can run shell commands";
  if (!here.runs_any_command && above.runs_any_command) {
    return "Can run commands outside the allow-list";
  }
  if (!here.skips_confirmation && above.skips_confirmation) {
    return "Stops asking before each change";
  }
  return null;
}

// --- the two controls -----------------------------------------------------

interface PermissionProps {
  /** The levels, or null before `permission.list` has answered. */
  list: PermissionList | null;
  /** The level currently in force, as the core last confirmed it. */
  value: string;
  /** A turn is in flight; switching is refused while one is. */
  busy: boolean;
  /** The core is not reachable. */
  disabled: boolean;
  onChange: (name: string) => void;
}

/**
 * The four-rung ladder, as a menu.
 *
 * Rendered nothing at all when the core has not answered. Unread, with nothing
 * to say what is in force, this would be four rows naming a choice nobody has
 * been told the terms of -- and the user cannot tell a real "Medium" from a
 * placeholder one. Absent is better than decorative.
 */
export function PermissionMenu({
  list,
  value,
  busy,
  disabled,
  onChange,
}: PermissionProps) {
  const levels = list?.permissions ?? [];
  if (!list || levels.length === 0) return null;

  const current = levels.find((level) => level.name === value) ?? levels[0];
  const index = levels.findIndex((level) => level.name === value);

  return (
    <ChoiceMenu
      label="Permission"
      value={current?.label ?? ""}
      currentName={current?.name ?? ""}
      valueTitle={current?.description ?? ""}
      // The four segments: a ladder, not four choices. Only the ones up to and
      // including the current level are filled, so the row reads as a position
      // on a scale rather than as a set of independent buttons -- which is what
      // it is.
      steps={levels.map((level, i) => ({
        key: level.name,
        on: i <= index,
      }))}
      busy={busy}
      disabled={disabled}
      onSelect={onChange}
      options={levels.map((level, i) => ({
        name: level.name,
        selected: level.name === value,
        label: level.label,
        description: level.description,
        markers: [
          ...(level.runs_any_command ? ["any command"] : []),
          ...(level.skips_confirmation ? ["no prompts"] : []),
        ],
        gain: permissionGain(level, levels[i + 1]),
      }))}
    />
  );
}

interface ThinkingProps {
  /**
   * The bound model's own answer, or null while it is being read.
   *
   * Null and "not supported" are deliberately different: the first has not
   * answered yet and the control stays put, the second has and the control
   * goes away. Show a dial for a model that cannot reason, or one that reasons
   * with no choice to make, and the menu offers something that either does
   * nothing or is refused -- which teaches the reader that this row is
   * decoration.
   */
  info: ReasoningInfo | null;
  busy: boolean;
  disabled: boolean;
  onChange: (effort: string) => void;
}

/**
 * How hard the model should think, as a menu.
 *
 * The first option is "default", whose value is the empty string rather than
 * the model's own default effort. Sending `"max"` would pin the model to its
 * default forever, which is the opposite of offering it a choice: the core
 * builds no `reasoning` field at all for an empty effort, and the provider
 * picks. So the label shows what the default is and the value stays empty.
 */
export function ThinkingMenu({ info, busy, disabled, onChange }: ThinkingProps) {
  // **Both negatives are checked here, not left to the caller.** The `efforts`
  // guard used to live in the composer's markup, which meant this component on
  // its own rendered a menu with one entry -- "Default" -- for a model that
  // reports no dial at all: a control offering exactly the choice that does
  // nothing. A caller that forgets the check would get it back silently, so the
  // check belongs to the thing being offered rather than to whoever renders it.
  if (!info || info.efforts.length === 0) return null;

  const defaultLabel = info.default_effort
    ? `Default (${info.default_effort})`
    : "Default";

  return (
    <ChoiceMenu
      label="Thinking"
      // The effort the core reported, never the one last clicked: a local
      // value would keep showing what was asked for even after the core
      // refused it, which is the menu describing a state that does not exist.
      value={info.effort || defaultLabel}
      currentName={info.effort}
      valueTitle="How hard the model should think"
      busy={busy}
      disabled={disabled}
      onSelect={onChange}
      options={[
        {
          name: "",
          selected: info.effort === "",
          label: defaultLabel,
          description:
            "Let the model decide. No effort is sent, so its own default applies.",
          markers: [],
          gain: null,
        },
        ...info.efforts.map((effort) => ({
          name: effort,
          selected: effort === info.effort,
          label: effort,
          // No description, because the core sends none. The names are the
          // provider's and they change with its models, so a sentence written
          // here about "medium" would be a guess about a dial this window
          // cannot see.
          description: null,
          markers: [],
          gain: null,
        })),
      ]}
    />
  );
}

// --- the shared menu ------------------------------------------------------

export interface ChoiceOption {
  /** The value sent to the core. `""` is a real value here, not "nothing". */
  name: string;
  selected: boolean;
  label: string;
  /** `null` renders no second line, rather than an empty one. */
  description: string | null;
  /**
   * Short markers beside the name, e.g. `any command`.
   *
   * Separate from `description` because these are the things a user must
   * notice without reading, and a sentence is the wrong size for that.
   */
  markers: string[];
  /** What the next option up adds, in words. */
  gain: string | null;
}

interface ChoiceMenuProps {
  label: string;
  /** The current value, as a name to show. */
  value: string;
  /**
   * The current value as the core knows it -- the `name` of the selected
   * option, which for a default is `""`.
   *
   * Passed separately from `value` because `value` is a label to read and this
   * is a key to compare. Without it the menu could only ask the core to set
   * what it already has, and would do so on every re-pick.
   */
  currentName: string;
  valueTitle: string;
  /** The filled run, drawn before the value. Omit for a menu with no scale. */
  steps?: { key: string; on: boolean }[];
  busy: boolean;
  disabled: boolean;
  options: ChoiceOption[];
  onSelect: (name: string) => void;
}

/**
 * One row that opens a list of choices, and the list itself.
 *
 * **It opens toward the room it has**, which is the one thing about its
 * direction worth stating. It used to always open upward -- correct while this
 * was a bar pinned to the bottom of the composer, and wrong once it moved into
 * the settings panel, where these rows are the *first* group and there is
 * nothing above them but the window's top edge. The menu is measured on open
 * against the panel it lives in, capped to the room it found, and given
 * `overflow-y: auto` behind that, so the last option is always reachable.
 *
 * **One node for the panel, one for the list, and the trigger is inside the
 * panel** -- so a press on the trigger is a press on the surface being used,
 * not a dismissal. That is the contract `useDismiss` is built around.
 */
function ChoiceMenu({
  label,
  value,
  currentName,
  valueTitle,
  steps,
  busy,
  disabled,
  options,
  onSelect,
}: ChoiceMenuProps) {
  const [open, setOpen] = useState(false);
  // Null until the menu first opens: there is nothing to place before there is
  // anything to place, and measuring on mount would read a layout the panel is
  // still settling.
  const [placement, setPlacement] = useState<{
    dir: MenuDirection;
    maxHeight: number;
  } | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useDismiss(open, () => setOpen(false), surfaceRef);

  // Measured in a layout effect, before paint: measured in an effect the menu
  // would appear at the old position for a frame first, which on a row near the
  // top of the panel is a frame of an off-screen menu.
  useLayoutEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const panel = surfaceRef.current?.closest(".modal");
    // The panel when there is one, the window otherwise. A menu is bounded by
    // the surface it is clipped by, not by the window: inside a scrolling
    // modal anything past the panel's edge is gone even though it is on screen.
    const bounds: MenuBounds = panel?.getBoundingClientRect() ?? {
      top: 0,
      bottom: window.innerHeight,
    };
    setPlacement(
      measureMenu(trigger?.getBoundingClientRect() ?? bounds, bounds),
    );
  }, [open]);

  // Escape closes the menu, and must not also reach the window, which treats
  // Escape as "close whatever is open" -- the settings panel itself. Registered
  // in the capture phase so it runs before the window's own listener rather
  // than after it.
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

  return (
    <div className="permchoice" ref={surfaceRef}>
      <button
        ref={triggerRef}
        type="button"
        className="permchoice-trigger"
        onClick={() => setOpen((was) => !was)}
        disabled={disabled || busy}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={valueTitle}
      >
        <span className="permchoice-label">{label}</span>
        {steps && (
          <span className="permchoice-steps" aria-hidden="true">
            {steps.map((step) => (
              <span
                key={step.key}
                className={`permchoice-step${step.on ? " is-on" : ""}`}
              />
            ))}
          </span>
        )}
        <span className="permchoice-value">{value}</span>
        <span className="permchoice-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div
          className="permchoice-menu"
          role="listbox"
          aria-label={label}
          data-dir={placement?.dir ?? "down"}
          style={
            placement ? { maxHeight: `${placement.maxHeight}px` } : undefined
          }
        >
          {options.map((option) => (
            <button
              key={option.name || "default"}
              type="button"
              role="option"
              aria-selected={option.selected}
              className={`permchoice-item${
                option.selected ? " is-active" : ""
              }`}
              onClick={() => {
                setOpen(false);
                // Re-picking what is already in force asks the core to set
                // what it already has: a pointless round trip, and one that can
                // be refused for reasons the user did not cause.
                if (option.name !== currentName) onSelect(option.name);
              }}
            >
              <span className="permchoice-head">
                <span className="permchoice-name">{option.label}</span>
                {option.markers.map((marker) => (
                  <span key={marker} className="permchoice-warn">
                    {marker}
                  </span>
                ))}
              </span>
              {option.description && (
                <span className="permchoice-desc">{option.description}</span>
              )}
              {option.gain && (
                <span className="permchoice-gain">{option.gain}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}