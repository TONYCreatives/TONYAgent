/**
 * The run, as one card: what the turn is doing, for how long, and how much of
 * the conversation it has spent.
 *
 * This is the top of the context pane and the only part of it that does not
 * scroll away -- see `ContextPanel`. It answers four questions in the order a
 * reader asks them: *is it working*, *for how long*, *what is it doing*, and
 * *how full is the context*. The first two are the line at the top, the third
 * is the live sentence under it, and the fourth is the meter at the foot.
 *
 * **No model or mode here.** Both are controls, and both live where you change
 * them: the title bar's model menu and the composer's mode chip. A card that
 * repeated them would be a third copy of two facts, one of which the reader
 * cannot act on from inside this pane.
 *
 * The clock is the card's own state, for the reason `ContextPanel` used to give
 * it: a ticker in the window would re-render the transcript every second. Here
 * it re-renders one card.
 *
 * **The status line is the panel's only live region.** It is the one thing that
 * changes while the reader is watching, and it changes a sentence at a time --
 * `Running read_file`, then `Running grep`, then the idle hint. The rows below
 * are not live: a region per row would read the whole feed aloud on every
 * update, and the clock, which changes every second, is deliberately outside it.
 */

import { useEffect, useState } from "react";

import { formatElapsed, formatTokens, type RunState } from "./activity.js";
import type { ContextReply } from "./backend.js";
import type { TurnUsage } from "./events.js";

const LABELS: Record<RunState, string> = {
  idle: "Idle",
  working: "Working",
  waiting: "Waiting",
  error: "Error",
};

const HINTS: Record<RunState, string> = {
  idle: "No turn is running.",
  working: "The agent is working in the transcript.",
  waiting: "The agent needs an answer before it can continue.",
  error: "The last turn failed. The transcript says why.",
};

interface Props {
  run: RunState;
  /** The running turn's start, or null when nothing is running. */
  startedAt: number | null;
  /** What the agent is doing, for the one line under the state. */
  detail: string;
  /** What the last turn spent, or null when the provider reported nothing. */
  usage: TurnUsage | null;
  /** The core's context measurement. `known: false` draws no bar. */
  context: ContextReply;
  onStop: () => void;
  onOpenTrajectory: () => void;
}

/**
 * The turn's token row, or the honest absence of it.
 *
 * `unknown` rather than `0 in / 0 out` when no frame arrived: a provider that
 * reports no usage is not a turn that cost nothing, and a zero here would be
 * the one number on this card that was invented rather than measured. The same
 * rule the context meter already follows -- see `meterText`.
 */
function usageText(usage: TurnUsage | null): string {
  if (usage === null) return "unknown";
  return `${formatTokens(usage.input)} in · ${formatTokens(usage.output)} out`;
}

/** The row's tooltip: the exact counts, and the price when one was published. */
function usageTitle(usage: TurnUsage | null): string {
  if (usage === null) {
    return "The provider did not report usage for this turn";
  }
  const parts = [
    `In: ${usage.input.toLocaleString()} tokens`,
    `Out: ${usage.output.toLocaleString()} tokens`,
  ];
  if (usage.reasoning > 0) {
    parts.push(`of which ${usage.reasoning.toLocaleString()} were thinking`);
  }
  if (usage.cost !== null) {
    parts.push(`Cost: $${usage.cost.toFixed(4)}`);
  }
  return parts.join(" · ");
}

/**
 * The meter's one line, or the honest absence of it.
 *
 * Three cases, and the difference between them is the point of `known` and
 * `window`: a provider that reported no usage reads `unknown`; one that reported
 * usage but publishes no context size reads `12.4k used`; and only a real pair
 * reads as a fraction. A bar at 0% for a long conversation would be confidently
 * wrong, which is the failure `context.get` was written to make impossible.
 */
function meterText(context: ContextReply): string {
  if (!context.known) return "unknown";
  if (context.window > 0) {
    const percent = Math.min(100, Math.round((context.used / context.window) * 100));
    return `${formatTokens(context.used)} / ${formatTokens(context.window)} · ${percent}%`;
  }
  return `${formatTokens(context.used)} used`;
}

export function RunCard({
  run,
  startedAt,
  detail,
  usage,
  context,
  onStop,
  onOpenTrajectory,
}: Props) {
  // A ticker only while a turn is running: an idle card has nothing to count,
  // and a timer that ran anyway would wake the window every second forever.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);

  const elapsed =
    startedAt === null ? null : formatElapsed(Math.max(0, now - startedAt));

  const measured = context.known && context.window > 0;
  const percent = measured
    ? Math.min(100, Math.max(0, (context.used / context.window) * 100))
    : 0;

  return (
    <div className="run-card" data-run={run}>
      <div className="run-line">
        <span className="run-orb" data-run={run} aria-hidden="true" />
        <span className="run-state">{LABELS[run]}</span>
        {elapsed !== null && (
          <span className="run-clock" title="Elapsed time for this turn">
            {elapsed}
          </span>
        )}
      </div>

      {/*
        The live sentence. `polite` rather than `assertive`: a tool starting is
        worth hearing between keystrokes, not worth interrupting the reader for.
        It is also the *only* live region in the pane -- see the file comment.
      */}
      <p className="run-detail" aria-live="polite">
        {run === "working" && detail ? detail : HINTS[run]}
      </p>

      {/*
        What the turn spent, beside how full the conversation is. The two are
        different questions -- one is this turn's bill, the other is how much
        room is left -- and putting the bill first is the order a reader asks
        them in.
      */}
      <div
        className="run-tokens"
        data-known={usage !== null ? "true" : "false"}
        title={usageTitle(usage)}
      >
        <span className="run-context-label">Tokens</span>
        <span className="run-tokens-value">{usageText(usage)}</span>
      </div>

      <div
        className="run-context"
        data-known={context.known ? "true" : "false"}
        title={
          measured
            ? `Context: ${formatTokens(context.used)} of ${formatTokens(context.window)} tokens`
            : "The provider did not report the context size"
        }
      >
        <span className="run-context-label">Context</span>
        {/* The bar is decoration on the number beside it; a reader gets the
            fraction from the text, and the text is what has to be right. */}
        <span className="run-context-bar" aria-hidden="true">
          {measured && (
            <span className="run-context-fill" style={{ width: `${percent}%` }} />
          )}
        </span>
        <span className="run-context-value">{meterText(context)}</span>
      </div>

      <div className="run-actions">
        {run === "working" && (
          <button type="button" className="btn run-stop" onClick={onStop}>
            Stop
          </button>
        )}
        <button
          type="button"
          className="run-link linkish"
          onClick={onOpenTrajectory}
          title="See every event this run produced"
        >
          Open Trajectory
        </button>
      </div>
    </div>
  );
}
