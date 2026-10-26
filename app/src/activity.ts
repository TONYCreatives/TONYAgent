/**
 * What the agent is doing, read out of the transcript.
 *
 * The window already stores everything a run panel needs -- each tool's status,
 * its one-line summary, the file it changed, the turn's own start -- but it
 * stores it in the shape the *transcript* draws: scattered across messages,
 * interleaved with prose and thinking. A panel that answered "what is running
 * right now?" out of that shape would re-derive the same four facts in the
 * render path on every token delta.
 *
 * So this is the derivation, once, as plain functions. It is deliberately not a
 * component and not a store: `turnActivity` is pure, the panel memoises it, and
 * the reducer stays the only thing that mutates transcript state.
 */

import type { ChatMessage, ChatState, ToolCall } from "./events.js";

/** The four states the Run card can be in, in the order they take precedence. */
export type RunState = "waiting" | "error" | "working" | "idle";

/** One tool call, flattened for a row in the activity feed. */
export interface ActivityStep {
  id: string;
  name: string;
  status: ToolCall["status"];
  /** The core's own one-line outcome, or the tool's name while it is running. */
  summary: string;
  path?: string;
  added?: number;
  removed?: number;
  /**
   * How long the call took, as this window measured it, or null when it did not
   * see both ends.
   *
   * Null is the ordinary case for a restored conversation: tool events are not
   * saved, so the rows have no timestamps. A row with no duration draws none --
   * the alternative is a number that describes the restore rather than the work.
   */
  durationMs: number | null;
}

/** One file the turn touched, with the counts the core reported. */
export interface TouchedFile {
  path: string;
  added: number;
  removed: number;
}

export interface TurnActivity {
  run: RunState;
  /** Chronological, oldest first -- the panel reverses for display. */
  steps: ActivityStep[];
  /** First-touch order, deduplicated by path, counts summed across calls. */
  files: TouchedFile[];
  counts: { running: number; done: number; failed: number };
  /** Milliseconds since the turn started, or null when no turn is running. */
  elapsedMs: number | null;
}

/**
 * The turn's state, and why the order matters.
 *
 * A pending confirmation or question is `waiting` even though `busy` is true:
 * the agent is not working, it is blocked on a person, and that is the one
 * state that should pull the eye away from the transcript. `error` comes next
 * because a turn that failed while a dialog was still open would otherwise
 * report itself as waiting forever.
 */
export function runState(state: ChatState): RunState {
  if (state.pendingConfirm !== null || state.pendingAsk !== null) return "waiting";
  if (state.busy) return "working";
  if (state.error !== null) return "error";
  return "idle";
}

/** Milliseconds between a turn's start and now, floored at zero. */
export function elapsedMs(startedAt: number | null, now: number): number | null {
  if (startedAt === null) return null;
  return Math.max(0, now - startedAt);
}

/**
 * How long one call took, at the sizes a tool call actually takes.
 *
 * Sub-second work is the ordinary case, so it is the one that keeps its
 * precision: `0.4s` says something `0s` does not. Past ten seconds the fraction
 * is noise, and past a minute the reader wants the seconds they can count.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}

/**
 * A token count at the width a 288px panel has.
 *
 * `12.4k`, not `12400`: the number is read at a glance and the exact digit is
 * the kind of thing the usage page is for. One decimal below 100k, whole
 * thousands above it -- `200k` is a round number and `200.0k` is not.
 */
export function formatTokens(n: number): string {
  if (n < 1000) return String(Math.max(0, Math.round(n)));
  const scaled = (value: number, suffix: string) => {
    const text =
      value < 100
        ? value.toFixed(1).replace(/\.0$/, "")
        : String(Math.round(value));
    return `${text}${suffix}`;
  };
  if (n < 1_000_000) return scaled(n / 1000, "k");
  return scaled(n / 1_000_000, "M");
}

/** `m:ss`, and `h:mm:ss` only after an hour -- a run is usually seconds. */
export function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

/** The tools that write the plan. `todo_write` sets the list, `create_goal` the goal. */
const PLAN_WRITERS = new Set(["todo_write", "create_goal"]);

/**
 * Whether this tool can change the plan.
 *
 * Used by the window to decide when a `plan.get` is worth its round trip: the
 * plan has no change event of its own, and refreshing after every tool call
 * would be one request per row to redraw a list that changed at most once. A
 * completion of one of these two is the only moment the plan can differ from
 * what is on screen.
 */
export function isPlanWriter(name: string): boolean {
  return PLAN_WRITERS.has(name);
}

/**
 * The call a plan row can scroll to.
 *
 * The plan card's rows are read-only, and pressing one takes the reader to the
 * call that put it on screen. The plan says nothing about *which* call wrote it
 * -- a list can be replaced by any `todo_write` -- so this is the most recent
 * writer in the transcript, which is the one whose result the card is showing.
 *
 * Null when there is no writer at all: a plan restored from disk comes back
 * without its tool events, so the rows are plain text rather than buttons that
 * scroll nowhere. That is the same rule the Files pane follows for a path it
 * cannot open.
 */
export function lastPlanCall(messages: ChatMessage[]): { id: string; name: string } | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const tools = messages[i].tools;
    for (let j = tools.length - 1; j >= 0; j -= 1) {
      if (isPlanWriter(tools[j].name)) return { id: tools[j].id, name: tools[j].name };
    }
  }
  return null;
}

/**
 * The message this run panel is about.
 *
 * The running turn's own assistant message, when there is one. When the turn is
 * over -- or the conversation was just restored -- the last assistant message
 * that actually did something, so the panel still shows the last run rather
 * than emptying itself the moment the agent stops.
 */
function targetMessage(state: ChatState): (typeof state.messages)[number] | undefined {
  if (state.activeTurnId !== null) {
    const active = state.messages.find((m) => m.id === state.activeTurnId);
    if (active) return active;
  }
  for (let i = state.messages.length - 1; i >= 0; i -= 1) {
    const message = state.messages[i];
    if (message.role === "assistant" && message.tools.length > 0) return message;
  }
  return undefined;
}

/**
 * Everything the Run panel needs, derived in one pass.
 *
 * `files` sums the added/removed counts across calls to the same path: a turn
 * that edits a file in three passes changed it once, and three rows saying
 * "+12 -3" each would overstate what happened. A path is listed on first touch,
 * which is the order the reader watched them appear in.
 */
export function turnActivity(state: ChatState, now = Date.now()): TurnActivity {
  const message = targetMessage(state);
  const calls = message?.tools ?? [];

  const steps: ActivityStep[] = calls.map((call) => ({
    id: call.id,
    name: call.name,
    status: call.status,
    summary: call.detail ?? call.name,
    path: call.path,
    added: call.added,
    removed: call.removed,
    durationMs:
      call.startedAt !== undefined && call.endedAt !== undefined
        ? Math.max(0, call.endedAt - call.startedAt)
        : null,
  }));

  const files: TouchedFile[] = [];
  const byPath = new Map<string, TouchedFile>();
  for (const call of calls) {
    if (!call.path) continue;
    const existing = byPath.get(call.path);
    if (existing) {
      existing.added += call.added ?? 0;
      existing.removed += call.removed ?? 0;
      continue;
    }
    const file = {
      path: call.path,
      added: call.added ?? 0,
      removed: call.removed ?? 0,
    };
    byPath.set(call.path, file);
    files.push(file);
  }

  return {
    run: runState(state),
    steps,
    files,
    counts: {
      running: steps.filter((step) => step.status === "running").length,
      done: steps.filter((step) => step.status === "ok").length,
      failed: steps.filter((step) => step.status === "failed").length,
    },
    elapsedMs: state.busy ? elapsedMs(state.turnStartedAt, now) : null,
  };
}
