/**
 * The two controls that decide how the agent behaves: how much it may do, and
 * how hard the model may think. Both live in the settings panel, and both are
 * drawn from the one set of parts at the bottom of this file -- the same
 * summary line, the same option rows.
 *
 * **They share a vocabulary because they are one kind of decision.** A
 * permission level and a thinking effort are both "how much may this window do
 * without asking", and a user reading the two side by side should not have to
 * learn two shapes. Permission already had a menu; Thinking was a native
 * `<select>`, which on Windows is a light box with a system font and a system
 * arrow on a black panel -- the one control in this window that visibly came
 * from somewhere else. So both are rendered from the same parts, which is why
 * there is one set of rows here rather than two that happen to look alike.
 *
 * **One is a popover and one is a list, and the difference is how many options
 * there are.** Permission is a ladder of four rungs, and the whole decision is
 * *between* them: what High refuses and Full allows is the thing being chosen, so
 * putting the four behind a press hides exactly the comparison the control exists
 * to support. It is always open. Thinking is a dial whose steps belong to the
 * model -- a provider may name five efforts or a dozen -- so it stays a popover,
 * where the list costs nothing until it is wanted.
 *
 * The two are still one implementation: `ChoiceRow` is the row in both, so the
 * names, the markers, the descriptions and the gain sentences cannot drift apart
 * between the control you press and the control you read.
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

import { useEffect, useRef, useState } from "react";

import { useDismiss } from "./useDismiss.js";
import { useMenuPlacement } from "./useMenuPlacement.js";


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
  /**
   * Whether model-authored code runs on the user's own machine.
   *
   * **The one flag here that is about *where* code runs rather than whether it
   * may.** Everything else narrows; this one changes the containment. Inside
   * Docker a command cannot reach the user's files outside one mounted folder;
   * on the host it can, and it does.
   *
   * Reported over the wire rather than left to the description so the menu can
   * put it in front of the user as a gain and a marker. A permission level that
   * grants your machine and mentions it only in a sentence is a permission
   * level nobody reads before they pick it.
   */
  runs_on_host: boolean;
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
  // Host execution is checked FIRST, and that ordering is the point. Going from
  // High to Full gains three things, and only one of them changes where the
  // agent's commands run. Reporting "can run commands outside the allow-list" as
  // the headline for that step would describe a difference that is real and is
  // also, by far, the smaller one -- so the gain line names the boundary instead.
  if (!here.runs_on_host && above.runs_on_host) {
    return "Runs on this computer, outside the sandbox";
  }
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
 * The four-rung ladder, expanded in place.
 *
 * Rendered nothing at all when the core has not answered. Unread, with nothing
 * to say what is in force, this would be four rows naming a choice nobody has
 * been told the terms of -- and the user cannot tell a real "Medium" from a
 * placeholder one. Absent is better than decorative.
 *
 * **All four rungs are on screen, which is the point of it not being a menu.**
 * The choice here is comparative -- what does stepping up actually buy -- and
 * four options behind a press makes the user hold three of them in their head to
 * compare against the fourth. Expanded, the descriptions and the gain sentences
 * sit one above the next and are read together, which is the only way the ladder
 * is legible as a ladder.
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
    <ChoiceList
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
        // First for the same reason `permissionGain` checks it first: this is
        // the marker that means "your machine", and it has to be the one a user
        // scanning the list actually reads.
        markers: [
          ...(level.runs_on_host ? ["on this computer"] : []),
          ...(level.runs_any_command ? ["any command"] : []),
          ...(level.skips_confirmation ? ["no prompts"] : []),
        ],
        // **On the row it describes, which is the one above the step.**
        // `permissionGain(here, above)` says what stepping up from `here` buys,
        // and rendering that under `here` was legible while each option was
        // alone in a menu and is a contradiction in a ladder: measured on the
        // expanded list, the Medium row read "Edit files. Shell commands are
        // refused." with "Can run shell commands" directly beneath it -- three
        // lines that cannot all be true of one rung. On the higher row the same
        // sentence is a true description of *that* rung, and the ladder reads
        // top to bottom as what each step adds to the one below it.
        gain: i > 0 ? permissionGain(levels[i - 1], level) : null,
      }))}
    />
  );
}

/**
 * The selected rung, spelled out: the detail column beside the ladder.
 *
 * The ladder's rows carry one clause each, which is what makes them
 * comparable -- and what leaves the page's right half blank. This is the
 * other half of that bargain: the full terms of the rung that was clicked,
 * drawn from the same `permission.list` facts the rows' markers come from,
 * so the two can never disagree. It follows the confirmed value rather than
 * hover or focus: clicking a rung *switches* to it, so the value is the
 * clicked rung, and a pane previewing anything else would name terms that
 * are not in force.
 *
 * Rendered nothing when the core has not answered, for the same reason the
 * menu renders nothing: a card naming terms nobody has been told are
 * decoration, not detail.
 */
export function PermissionDetail({
  list,
  value,
}: {
  list: PermissionList | null;
  value: string;
}) {
  const levels = list?.permissions ?? [];
  if (!list || levels.length === 0) return null;
  const index = levels.findIndex((level) => level.name === value);
  const at = index >= 0 ? index : 0;
  const level = levels[at];
  const prev = at > 0 ? levels[at - 1] : undefined;
  const next = levels[at + 1];

  const facts = (level: PermissionInfo): [string, string][] => [
    [
      "Shell commands",
      !level.runs_commands
        ? "Refused entirely"
        : level.runs_any_command
          ? "Any program, no list"
          : "Only the Commands allow-list below",
    ],
    [
      "Before a destructive change",
      level.skips_confirmation ? "Runs without asking" : "Asks first",
    ],
    [
      "Where commands run",
      level.runs_on_host
        ? "On this computer, outside the sandbox"
        : level.runs_commands
          ? "Inside the sandbox, which must be running"
          : "Nowhere — no command runs at this level",
    ],
  ];

  return (
    <div className="perm-detail" role="complementary" aria-label="Permission level in detail">
      <h3>Level in detail</h3>
      <article
        className={`perm-detail-card${index >= 0 ? " is-current" : ""}`}
      >
        <div className="perm-detail-head">
          <span className="permchoice-name">{level.label}</span>
          {index >= 0 && (
            <span className="permchoice-warn" title="The level currently in force">
              in force
            </span>
          )}
          {(level.runs_on_host || level.runs_any_command || level.skips_confirmation) && (
            <span className="perm-detail-markers">
              {[level.runs_on_host ? "on this computer" : null,
                level.runs_any_command ? "any command" : null,
                level.skips_confirmation ? "no prompts" : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          )}
        </div>
        <p className="permchoice-desc">{level.description}</p>
        <dl className="perm-detail-facts">
          {facts(level).map(([term, detail]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
        {prev && (
          <p className="permchoice-gain">
            Steps up from {prev.label}: {permissionGain(prev, level) ?? level.description}
          </p>
        )}
        {next && (
          <p className="permchoice-gain">
            Steps up to {next.label}: {permissionGain(level, next) ?? next.description}
          </p>
        )}
      </article>
    </div>
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

/**
 * What both framings need to draw one control.
 *
 * The popover and the always-open list are given the same thing, and that is
 * deliberate rather than convenient: every fact about the choice -- the names,
 * which one is in force, the markers, the gain sentences -- is supplied here and
 * neither framing is allowed to decide any of it.
 */
interface ChoiceProps {
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
 * The line that says what is in force: the caption, the ladder, the answer.
 *
 * Shared so the two framings cannot disagree about it. In the popover it is
 * inside the button that opens the list; in the expanded one it is a row of its
 * own above the options, and it is still the only place the current value is
 * written -- the list is where a *new* one is picked, not where the current one
 * is reported. That split is the same one `value` and `currentName` make: what
 * the core last confirmed, and what to compare a pick against.
 */
function ChoiceSummary({ label, value, steps }: Pick<ChoiceProps, "label" | "value" | "steps">) {
  return (
    <>
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
    </>
  );
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
 * That measurement is `useMenuPlacement` now rather than this component's own:
 * the model picker and the row menus had the same question to ask and each was
 * answering it with a hardcoded side, which is the bug this component's version
 * had already been fixed for.
 *
 * **One node for the panel, one for the list, and the trigger is inside the
 * panel** -- so a press on the trigger is a press on the surface being used,
 * not a dismissal. That is the contract `useDismiss` is built around.
 *
 * Escape closes it without leaving the panel, and it is registered in the
 * capture phase for that reason: the window treats Escape as "close whatever is
 * open", and this menu is open inside the settings panel.
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
}: ChoiceProps) {
  const [open, setOpen] = useState(false);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  // Nothing to place before the menu first opens, and measuring on mount would
  // read a layout the panel is still settling -- so the render names the
  // stylesheet's own direction until the measurement replaces it, which is why
  // the base rule declares neither anchor (see the block above).
  //
  // Keyed on `open` and not on a mount flag: unlike the two pickers this menu is
  // rendered by `open` alone, so its node is in the DOM in the same commit.
  const placement = useMenuPlacement(open, triggerRef, menuRef);

  useDismiss(open, () => setOpen(false), surfaceRef);

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
        <ChoiceSummary label={label} value={value} steps={steps} />
        <span className="permchoice-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div
          ref={menuRef}
          className="permchoice-menu"
          role="listbox"
          aria-label={label}
          data-dir={placement?.dir ?? "down"}
          style={
            placement ? { maxHeight: `${placement.maxHeight}px` } : undefined
          }
        >
          {options.map((option) => (
            <ChoiceRow
              key={option.name || "default"}
              option={option}
              currentName={currentName}
              role="option"
              busy={busy}
              disabled={disabled}
              // The popover closes on any press, including on the row that is
              // already in force: a menu left open under the cursor after a
              // press that did nothing reads as a press that failed.
              onPress={() => setOpen(false)}
              onPick={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The same control, with every option on screen.
 *
 * No trigger, no `aria-haspopup`, no menu to dismiss -- there is nothing hidden,
 * so there is nothing for Escape to close and nothing for `useDismiss` to watch.
 * The rows are the control: a radio group, because that is what a ladder with one
 * rung in force actually is, and because a screen reader then announces the
 * choice as "one of four, this one selected" rather than as four buttons that
 * happen to be near each other.
 *
 * The summary row above them is not decoration either. The radio group says which
 * one is *picked*; this says which one the core *confirmed*, and the two are not
 * always the same thing for the length of a round trip. Keeping the confirmed one
 * on screen while the rows report a pending press is what stops the panel from
 * claiming a level the orchestrator has not agreed to yet.
 */
function ChoiceList({
  label,
  value,
  currentName,
  valueTitle,
  steps,
  busy,
  disabled,
  options,
  onSelect,
}: ChoiceProps) {
  return (
    <div className="permchoice permchoice-open">
      <div className="permchoice-summary" title={valueTitle}>
        <ChoiceSummary label={label} value={value} steps={steps} />
      </div>
      <div className="permchoice-list" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <ChoiceRow
            key={option.name || "default"}
            option={option}
            currentName={currentName}
            role="radio"
            busy={busy}
            disabled={disabled}
            onPick={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * One option, as a row.
 *
 * **The only place an option is drawn, in either framing.** That is the whole
 * reason it is a component: the popover writes `role="option"` and the expanded
 * list writes `role="radio"`, and if those two were separate markup trees then
 * the marker order, the gain sentences and the disabled rule would be maintained
 * twice -- and the second copy would be the one nobody looked at, because it is
 * the one behind a press.
 *
 * Re-picking the row already in force does nothing, and that check lives here
 * rather than in each caller: it is a fact about the row, not about the framing.
 * Asking the core to set what it already has is a pointless round trip, and one
 * it can refuse for reasons the user did not cause.
 */
interface ChoiceRowProps {
  option: ChoiceOption;
  currentName: string;
  /** `option` inside the popover's listbox, `radio` in the expanded list. */
  role: "option" | "radio";
  busy: boolean;
  disabled: boolean;
  /** Ran on every press, before the pick is considered. The popover's dismiss. */
  onPress?: () => void;
  /** Ran only when the press is a change. */
  onPick: (name: string) => void;
}

function ChoiceRow({
  option,
  currentName,
  role,
  busy,
  disabled,
  onPress,
  onPick,
}: ChoiceRowProps) {
  return (
    <button
      type="button"
      role={role}
      // One or the other, never both, and written out rather than spread: a
      // `role="radio"` with `aria-selected` is an attribute the user agent
      // ignores, and an `aria-checked` on an option is one it does not expect.
      aria-selected={role === "option" ? option.selected : undefined}
      aria-checked={role === "radio" ? option.selected : undefined}
      aria-disabled={busy || disabled ? true : undefined}
      className={`permchoice-item${option.selected ? " is-active" : ""}`}
      // Disabled while a turn is in flight or the core is unreachable, in the
      // expanded list as well as the popover. In the popover the trigger carried
      // this; here the rows are the control, so they carry it themselves -- and
      // switching mid-turn would change the rules underneath a half-built
      // answer, whose reply is keyed to the model that was allowed something
      // else.
      disabled={disabled || busy}
      onClick={() => {
        onPress?.();
        if (option.name !== currentName) onPick(option.name);
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
      {option.gain && <span className="permchoice-gain">{option.gain}</span>}
    </button>
  );
}