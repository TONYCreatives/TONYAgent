/**
 * The window's one live state, in the top bar.
 *
 * It replaced three places saying "working" at once -- the tab spinner, the
 * context panel's card and the status bar's busy word -- with one control whose
 * whole job is the turn. The spinner stays (it says *which tab*), and the card
 * stays (it says *what* and *for how long*); the strip stopped saying it at all,
 * because the strip is the environment's and a turn is not part of the window's
 * environment.
 *
 * The pill is also the run panel's handle when the panel is closed. That is why
 * it exists in Agent even when idle: it is the one control in the top bar that
 * answers "what is happening", and an answer that only appears while something
 * is happening is an answer you cannot learn to look for.
 *
 * **In views with no run panel** -- Code, Trajectory, Settings -- the pill is
 * absent when nothing is running, and a running turn is a signpost rather than a
 * report: pressing it returns to Agent, where the transcript and the panel are.
 * A state control that did nothing in the mode you found it in would be worse
 * than no control at all.
 */

import type { RunState } from "./activity.js";

const WORDS: Record<RunState, string> = {
  idle: "Idle",
  working: "Working",
  waiting: "Waiting",
  error: "Error",
};

const ACTIONS: Record<RunState, string> = {
  idle: "No turn is running",
  working: "The agent is working",
  waiting: "The agent needs an answer",
  error: "The last turn failed",
};

interface Props {
  run: RunState;
  /** What the agent is doing right now, when it is doing something. */
  detail: string;
  /**
   * The run panel, in a view that has one: its state and its toggle.
   *
   * Optional rather than a flag plus a handler, so "there is nowhere to go" is
   * one absence rather than two booleans that could disagree.
   */
  panel?: { open: boolean; onToggle: () => void };
  /** Where a pill in a view without a panel goes: back to Agent. */
  onReturn: () => void;
}

export function StatusPill({ run, detail, panel, onReturn }: Props) {
  // No panel and nothing to report: nothing to draw. A permanently present
  // "Idle" chip in an editor is chrome for a turn that is not in front of you.
  if (!panel && run === "idle") return null;

  const action = panel
    ? panel.open
      ? "Hide the run panel"
      : "Show the run panel"
    : "Show the conversation";
  const name = `${WORDS[run]}${run === "working" && detail ? `, ${detail}` : ""}. ${action}`;

  /*
   * In a view with no run panel the pill is a *dot*, not a pill.
   *
   * The bar there is a place you pass through on the way to Agent, and the one
   * fact worth its width is "a turn is running" -- which the orb says in 6px.
   * The state word and the tool name belong to the transcript, a mode away; a
   * full "Working · read_file" chip in the trajectory's bar reads as a report
   * you can act on there, and there is nothing there to act on.
   *
   * The words are not drawn rather than hidden in CSS, so the dot is what is in
   * the accessibility tree's contents too. The name is still written out in
   * `aria-label` (see above), which is where a reader gets the sentence.
   */
  const dot = !panel;

  return (
    <button
      type="button"
      className={`statuspill${dot ? " is-dot" : ""}`}
      data-run={run}
      aria-label={name}
      aria-expanded={panel ? panel.open : undefined}
      title={`${ACTIONS[run]}. ${action}`}
      onClick={panel ? panel.onToggle : onReturn}
    >
      {/* The same orb the run card draws: one state mark in two places, and the
          card is the detail the pill is the summary of. */}
      <span className="run-orb" data-run={run} aria-hidden="true" />
      {!dot && (
        <>
          <span className="statuspill-state">{WORDS[run]}</span>
          {run === "working" && detail && (
            <>
              <span className="statuspill-sep" aria-hidden="true">
                &middot;
              </span>
              <span className="statuspill-detail">{detail}</span>
            </>
          )}
        </>
      )}
    </button>
  );
}
