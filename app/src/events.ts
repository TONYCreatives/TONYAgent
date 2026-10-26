/**
 * Reduces the core's event stream into something a component can render.
 *
 * All of this is presentation state. There is no turn logic here on purpose:
 * the core decides what a tool call means and when it is finished, and this
 * layer only reflects that. A second opinion about turn state in the frontend
 * is how the Tkinter app ended up with a `schedule_on_ui` layer that silently
 * dropped callbacks.
 */

import type { CoreEvent } from "./backend.js";

export type Role = "user" | "assistant" | "system";

export interface ToolCall {
  id: string;
  name: string;
  status: "running" | "ok" | "failed";
  /** Human-readable outcome, derived from the core's `result` dict. */
  detail?: string;
  /**
   * The file a mutating tool changed, as reported by the core's
   * `file_change` artifact.
   *
   * Read from the artifact rather than parsed out of `detail`: the detail is
   * an English sentence written for a person ("Written 42 chars to a.py"),
   * and scraping a path out of it means the Files tree breaks the moment
   * someone rewords the message. This is the difference between a number the
   * core measured and a number invented by counting tool calls.
   */
  path?: string;
  added?: number;
  removed?: number;
  /**
   * Where the turn's tool-call budget stands, e.g. "Tool call 3/10".
   *
   * Read from the core rather than counted here. This file is a renderer, and
   * a counter that counted tool cards would disagree with the core the moment
   * a call was refused, a batch was dropped, or a conversation was restored
   * from disk -- and the number on the card is the number that bounds the
   * model's spending.
   */
  budget?: string;
  /**
   * When this window saw the call start and finish.
   *
   * The window's own clock, for the same reason `turnStartedAt` is: the elapsed
   * time the panel prints is a reading of what the user watched, not of a
   * process on the other side of a pipe. Absent on a restored transcript, where
   * the tool events were never saved -- the feed then omits the duration rather
   * than inventing one.
   */
  startedAt?: number;
  endedAt?: number;
  /**
   * A subagent's own work, when this call asked for one.
   *
   * The child runs its own turn on the same bus, and every frame it emits
   * says which parent call it belongs to (`parent_call_id` on the event). This
   * is where those frames accumulate: nested under the card of the call that
   * asked for *that turn*, which is the only place they are allowed to appear.
   * Without it the child's frames were either a second assistant bubble in
   * this transcript or -- after the guard in `turn.started` -- nothing at all.
   *
   * The card is found by call id, never by tool name, and that is load-bearing
   * for the workflow verbs: `send_message` (Phase 6) gives a child it already
   * spawned another turn, so that turn's frames carry the `send_message` call
   * id and nest under *that* card rather than the `subagent` card that created
   * the child.
   */
  child?: SubagentChild;
  /**
   * How much of the turn's prose had been written when this call started.
   *
   * The one thing that keeps the transcript in the order the model worked in.
   * A turn is several passes -- prose, tool calls, more prose, more calls -- and
   * every pass writes into the same message, so without this the rows could
   * only be drawn as a block at the end: the answer first and then the calls
   * that produced it, which reads as a turn that did its work after saying it
   * had. With it, each row is drawn under the words that asked for it.
   *
   * A count of characters rather than an index into the prose, because the text
   * arrives in deltas and grows under the row: the number is a position in a
   * string that is still being written.
   *
   * Absent on a call that was never placed -- a hand-built message in a test, or
   * a transcript restored from before this existed. `MessageList` draws those
   * after the prose, which is where they used to go.
   */
  after?: number;
}

/** One child session's work, as the window was told it. */
export interface SubagentChild {
  /** The child's name, as `list_agents`/`interrupt_agent` address it. */
  name: string;
  /** Its answer: streamed while it works, authoritative on completion. */
  text: string;
  /** The tools the child itself ran, in the order it asked for them. */
  tools: ToolCall[];
  /** Whether the child's turn is still running. */
  running: boolean;
}

/**
 * One thinking pass, placed in the prose the way a tool call is.
 *
 * The core sends `reasoning.completed` once per assistant pass -- the pass that
 * thinks before its tool call, the pass that thinks before the answer -- and
 * each completion carries that pass's thought alone. Storing them in one flat
 * string lost the boundary between them: every thought in a turn stacked into a
 * single block at the very top of the bubble, in the order they were *reported*
 * rather than the order they *happened*. Giving each pass its own run with a
 * position is what lets a reader see "it thought this, then ran that tool,
 * then thought this" -- which is the whole point of showing the thinking.
 *
 * `after` is the mirror of `ToolCall.after`: how much of the turn's prose had
 * been written when this pass started thinking. The model thinks *before* it
 * writes and acts, so a run's mark is the end of the words that preceded the
 * thought -- and the next pass's prose and tool rows land after it.
 */
export interface ReasonRun {
  /** The thought itself: streamed on the deltas, authoritative on completion. */
  text: string;
  /** Prose length when this pass began thinking. See the note above. */
  after: number;
  /** Whether `reasoning.completed` has arrived for *this pass*. */
  complete: boolean;
  /** The model ran out of budget on this pass and wrote nothing. */
  truncated: boolean;
  /** Why, in words. Only ever set alongside `truncated`. */
  notice?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  tools: ToolCall[];
  /**
   * What the model thought, kept beside the answer rather than inside it.
   *
   * The core streams this on its own events precisely so the two do not
   * merge: an answer that arrives with the model's scratchwork interleaved is
   * a different thing from an answer.
   */
  reasoning: string;
  /**
   * Whether `reasoning.completed` has arrived.
   *
   * A restored message is born complete, which is what makes a reopened
   * conversation show its panel folded rather than streaming forever.
   */
  reasoningComplete: boolean;
  /** The model ran out of budget thinking and wrote nothing. */
  reasoningTruncated: boolean;
  /** Why, in words. Only ever set alongside `reasoningTruncated`. */
  reasoningNotice?: string;
  /**
   * Each thinking pass, placed against the prose -- the reasoning counterpart
   * of `tools`.
   *
   * The flat `reasoning` string above is kept (and is what every consumer that
   * only wants "the whole thought" reads), but it cannot say *where* a pass sat
   * relative to the tool rows. This list can, and `runsOf` uses it to interleave
   * thinking with the calls that followed it, in the order they happened.
   *
   * Absent on a hand-built message or one restored from before this existed --
   * which reads as a single pass at the top, the old behaviour, so nothing that
   * only sets `reasoning` has to change to keep working.
   */
  reasonRuns?: ReasonRun[];
  /**
   * Where the current pass's prose begins inside `text`.
   *
   * Carried so `message.completed` can replace *its own* pass and leave the
   * earlier ones alone. The core sends one completion per assistant pass, each
   * carrying that pass's authoritative text, and a completion that overwrote
   * the whole field deleted everything the model had written before its first
   * tool call -- the paragraph explaining what it was about to do, which is
   * exactly the sentence a reader needs to follow the rows below it.
   *
   * Absent on a message that never had a second pass, which is every message a
   * test builds by hand; it reads as zero, the start of the first pass.
   */
  passStart?: number;
}

/** Events that mean the turn is over, successfully or not. */
const TERMINAL = new Set(["turn.finished", "turn.failed"]);

/**
 * What a turn spent, summed by the core from the requests it made.
 *
 * The core sends this once, before the turn's terminal frame, and only when at
 * least one request reported a usage block. `null` in the state therefore means
 * *nobody measured this* -- not zero -- and the panel says `unknown` rather than
 * drawing a number the provider never gave.
 */
export interface TurnUsage {
  input: number;
  output: number;
  /**
   * Thinking tokens, which providers bill as output.
   *
   * Kept apart because a turn that spent everything thinking is a different
   * turn from one that wrote prose, and because adding them to `output` would
   * count the same tokens twice -- see `UsageRecord.total_tokens` in the core.
   */
  reasoning: number;
  /** The gateway's own price, when it published one. */
  cost: number | null;
}

let counter = 0;
/** Monotonic id for messages the frontend creates, not the core. */
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export interface ChatState {
  messages: ChatMessage[];
  busy: boolean;
  /**
   * The turn this window started and is rendering, or null between turns.
   *
   * Turn ids are how the core correlates a turn's frames, and a subagent runs
   * its own turn -- on its own id, inside the parent's turn -- over the same
   * bus (Phase 5). This is what lets the reducer tell "the turn I am showing"
   * from "a child's turn crossing the wire": a frame for any other turn gets
   * no bubble and cannot end this turn. See the `turn.started` case.
   */
  activeTurnId: string | null;
  /**
   * When the running turn started, as this window's clock read it.
   *
   * `Date.now()` rather than the core's `started_at`, because the elapsed
   * counter is a reading of this window's turn, not of the core's process: a
   * frame can sit in the pipe, and a wall clock on the other side would drift
   * from the timer drawing it. Null between turns and on a restored
   * conversation, where there is no start to count from -- the Run card hides
   * the clock rather than showing a number it made up.
   */
  turnStartedAt: number | null;
  /** Set when the core reports turn.failed or an error event arrives. */
  error: string | null;
  /**
   * What the last turn spent, or null when nothing was measured.
   *
   * Cleared when a new turn starts and kept when one ends, so the strip can
   * still report the number after the run has finished -- the alternative is a
   * count that vanishes exactly when the reader has time to look at it.
   *
   * Null on a restored conversation: the number is not saved with the
   * transcript, and inventing one from the message text would be a guess
   * dressed as a measurement.
   */
  turnUsage: TurnUsage | null;
  /** Non-null while a confirmation.requested is awaiting a response. */
  pendingConfirm: {
    id: string;
    name: string;
    arguments: string;
    description: string;
    destructive: boolean;
  } | null;
  /**
   * Non-null while the core is blocked on the user.
   *
   * A question (`ask_user_question`) or a presentation (`present`) is a tool
   * that stops the turn until the user answers, so the window is the only
   * thing that can unblock it. Same lifecycle as `pendingConfirm` above and
   * deliberately the same shape of state; the difference is that an answer is
   * text rather than a yes/no.
   */
  pendingAsk: {
    id: string;
    /** The tool that is asking, shown so the user knows where it came from. */
    name: string;
    /** "question" or "presentation" -- see `QuestionDialog`. */
    kind: string;
    prompt: string;
    content: string;
    options: string[];
  } | null;
}

export const initialState: ChatState = {
  messages: [],
  busy: false,
  activeTurnId: null,
  turnStartedAt: null,
  error: null,
  turnUsage: null,
  pendingConfirm: null,
  pendingAsk: null,
};

/** A message with nothing in it yet, reasoning included. */
export function blankMessage(id: string, role: Role): ChatMessage {
  return {
    id,
    role,
    text: "",
    tools: [],
    reasoning: "",
    reasoningComplete: false,
    reasoningTruncated: false,
    reasonRuns: [],
    passStart: 0,
  };
}

/** Find the assistant message a turn is currently writing into. */
function currentAssistant(state: ChatState, turnId: string | null): ChatMessage | undefined {
  for (let i = state.messages.length - 1; i >= 0; i -= 1) {
    const m = state.messages[i];
    if (m.role === "assistant" && (turnId === null || m.id === turnId)) return m;
  }
  return undefined;
}

/**
 * Whether a turn-scoped frame belongs to a turn this window is not rendering.
 *
 * A subagent's frames carry its own turn id, so they are not this turn's --
 * and the difference matters most for the *terminal* events, which would
 * otherwise end a turn that is still running.
 *
 * A null id is never foreign: `error` also arrives outside a turn, and
 * terminal cleanup for a turn this window never saw start (Phase 4's
 * "an ask cannot outlive its turn") must still land.
 */
function isForeignTurn(state: ChatState, turnId: string | null): boolean {
  return turnId !== null && state.activeTurnId !== null && turnId !== state.activeTurnId;
}

/**
 * Fold one of a subagent's frames into the card of the call that asked for it.
 *
 * A child is not a second assistant: its tool calls, its answer and its
 * running state belong under the card of the call that asked for *that turn*,
 * not in this transcript. The child's frames are the only ones carrying a
 * `parent_call_id`, and routing happens before the turn switch, so no child
 * frame can reach the turn lifecycle at all.
 *
 * **By id, never by name.** Which of the three spawning verbs made the call is
 * irrelevant here, and must stay irrelevant: `send_message` gives an existing
 * child another turn, whose frames carry that call's id, and a name check for
 * `subagent` would strand them.
 *
 * A frame whose card is not in the transcript -- the conversation was switched
 * away, or a restored transcript carries no tool cards -- returns the state
 * unchanged. There is nowhere to show it, and inventing a bubble for it is the
 * bug this replaces.
 */
function applySubagentEvent(state: ChatState, event: CoreEvent): ChatState {
  const callId = event.parent_call_id as string;
  const { type, payload } = event;

  for (const message of state.messages) {
    const call = message.tools.find((t) => t.id === callId);
    if (!call) continue;

    if (!call.child) {
      call.child = { name: event.subagent ?? "", text: "", tools: [], running: false };
    }
    const child = call.child;
    if (event.subagent) child.name = event.subagent;

    switch (type) {
      case "turn.started":
        child.running = true;
        break;
      case "message.delta":
        child.text += payloadString(payload, "text") ?? "";
        break;
      case "message.completed": {
        // The authoritative final text, replacing the streamed one -- the same
        // contract the parent's own message has.
        const final = payloadString(payload, "text");
        if (final !== undefined) child.text = final;
        break;
      }
      case "tool.started":
        child.tools = [
          ...child.tools,
          {
            id: payloadString(payload, "id") ?? String(child.tools.length),
            name: payloadString(payload, "name") ?? "tool",
            status: "running",
          },
        ];
        break;
      case "tool.completed":
      case "tool.failed": {
        const id = payloadString(payload, "id");
        const childCall =
          child.tools.find((t) => t.id === id) ?? child.tools[child.tools.length - 1];
        if (childCall) {
          childCall.status = isFailure(payload.result) || type === "tool.failed" ? "failed" : "ok";
          const detail = describeResult(payload.result);
          if (detail) childCall.detail = detail;
        }
        break;
      }
      case "turn.finished":
      case "turn.failed":
        // The parent's card reports the outcome; this only stops the nested
        // header from claiming the child is still working.
        child.running = false;
        break;
      default:
        // `reasoning.*`, `message.started`, anything unknown: nothing to show
        // yet. The child's thinking is deliberately not folded into its answer.
        break;
    }
    return state;
  }
  return state;
}

/** Mutating helper: replace a message in place, or append it. */
function upsert(state: ChatState, message: ChatMessage): void {
  const index = state.messages.findIndex((m) => m.id === message.id);
  if (index === -1) state.messages.push(message);
  else state.messages[index] = message;
}

function payloadString(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" ? value : undefined;
}

/** Render a tool's `arguments` object as one readable line for the dialog. */
function formatArguments(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Pull a short outcome line out of a tool result.
 *
 * The core sends the tool's own `result.to_dict()`, whose shape differs per
 * tool, so this probes a few conventional keys rather than assuming one. A
 * result it cannot summarise is not an error; the tool row just shows no detail.
 */
/**
 * Pull the `file_change` artifact out of a tool result, if it has one.
 *
 * The core emits this only from tools that actually changed something, so a
 * `read_file` returns nothing here and the tree gains no phantom row.
 */
function readFileChange(result: unknown): { path: string; added: number; removed: number } | null {
  if (!result || typeof result !== "object") return null;
  const artifacts = (result as Record<string, unknown>).artifacts;
  if (!Array.isArray(artifacts)) return null;
  for (const artifact of artifacts) {
    if (!artifact || typeof artifact !== "object") continue;
    const record = artifact as Record<string, unknown>;
    if (record.type !== "file_change") continue;
    const data = record.data as Record<string, unknown> | undefined;
    if (!data || typeof data.path !== "string") continue;
    return {
      path: data.path,
      added: typeof data.added === "number" ? data.added : 0,
      removed: typeof data.removed === "number" ? data.removed : 0,
    };
  }
  return null;
}

/**
 * The turn's tool-call standing, if the core reported one.
 *
 * The core sends it on the event and inside the result the model reads. The
 * event is read here because it is also present on a call the budget
 * *refused* -- and a refused call still gets a card, drawn failed. Reading
 * only `result` would leave that card without a number, which is the one card
 * where the number matters most.
 */
function readBudget(raw: unknown): string | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const label = (raw as Record<string, unknown>).label;
  return typeof label === "string" && label.trim() ? label : undefined;
}

function describeResult(result: unknown): string | undefined {
  if (typeof result === "string") return result.slice(0, 200);
  if (!result || typeof result !== "object") return undefined;
  const record = result as Record<string, unknown>;
  for (const key of ["summary", "message", "output", "stdout", "error"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.slice(0, 200);
  }
  if (record.success === false) return "failed";
  if (record.success === true) return "ok";
  return undefined;
}

/**
 * Did this tool result come back as a failure?
 *
 * Asked of the *result*, not of the event type, because the core emits
 * `tool.completed` for every finished call regardless of outcome -- it has a
 * `tool.failed` type and never sends it. Reading the event type therefore marks
 * every call successful, and a card reading "No project folder selected" is
 * drawn in the colour that means "done". The status is in the payload the core
 * already sends, so this is where the answer has always been.
 *
 * `cancelled` counts: it is not success either, and a stop the user asked for
 * should not be reported as a completed action.
 */
function isFailure(result: unknown): boolean {
  if (!result || typeof result !== "object") return false;
  const status = (result as Record<string, unknown>).status;
  return status === "error" || status === "cancelled";
}

/**
 * Copy the message list deeply enough that a reducer branch may edit it.
 *
 * A shallow `messages.slice()` copies the *array* but not the messages, so
 * `target.tools = [...]` in the tool branches writes through to the caller's
 * state. That happens to be invisible while every caller replaces the whole
 * object -- and then quietly corrupts anything holding an older reference,
 * such as a `useMemo` dependency or a replayed event. Copying the messages and
 * their tool arrays is what makes "returns a new state" true rather than
 * aspirational.
 */
function copyMessages(state: ChatState): ChatMessage[] {
  return state.messages.map((m) => ({
    ...m,
    // The child object is copied too, and its tool list with it. The shallow
    // copy this used to be was enough while a tool call was flat; a nested
    // object would otherwise be written through into the caller's state, which
    // is the exact corruption `copyMessages` exists to prevent.
    tools: m.tools.map((t) => ({
      ...t,
      child: t.child
        ? { ...t.child, tools: t.child.tools.map((c) => ({ ...c })) }
        : undefined,
    })),
    // The thinking runs are copied too: the reducer mutates the open run's text
    // as deltas stream in, and a shallow copy would write through into the
    // caller's state -- the exact corruption `copyMessages` exists to prevent.
    reasonRuns: m.reasonRuns?.map((r) => ({ ...r })),
  }));
}

/**
 * Drop an assistant placeholder the core never wrote to.
 *
 * `turn.started` creates the bubble eagerly so the first delta has somewhere
 * to land, which means any turn that produces no assistant text leaves an
 * empty bubble in the transcript. An empty bubble is worse than no bubble: it
 * reads as a rendering fault, so a user whose key was rejected sees a broken
 * UI next to the error that explains the rejection.
 *
 * Every terminal event routes through here, not just `turn.finished`. That
 * asymmetry was a real bug: a rejected key emits `turn.failed` (or `error`),
 * and the placeholder survived both, so the failure path -- the one a new user
 * hits first -- was the one path that kept the empty bubble.
 *
 * A message that has text, tools, *or* reasoning is kept. Reasoning counts
 * because a model that thought and then ran out of budget produced something
 * worth showing and something worth explaining.
 */
function dropEmptyAssistantMessages(next: ChatState): void {
  next.messages = next.messages.filter(
    (m) => m.text.trim() !== "" || m.tools.length > 0 || m.reasoning.trim() !== "",
  );
}

export function applyEvent(state: ChatState, event: CoreEvent): ChatState {
  const next: ChatState = {
    ...state,
    messages: copyMessages(state),
  };
  const { type, turn_id: turnId, payload } = event;

  // A subagent's frames are routed to the card that spawned them before any
  // turn logic runs, so a child can never move `busy`, raise an error banner
  // or create a message -- the whole class of bugs the active-turn guard was
  // written for.
  if (event.parent_call_id) {
    return applySubagentEvent(next, event);
  }

  switch (type) {
    case "turn.started": {
      // A turn that starts while one is already running is a subagent's, not
      // this window's: a child runs its own turn on its own id inside the
      // parent's turn, and its frames cross the same bus. Rendering it was
      // worse than it sounds -- the child's whole answer appeared as an
      // unlabeled assistant bubble, and the child's `turn.finished` cleared
      // `busy` while the parent was still working, re-enabling a composer the
      // core would refuse. Ignoring it is what keeps the parent's turn the
      // only one on screen.
      if (next.activeTurnId !== null) return state;
      next.busy = true;
      next.error = null;
      // A new turn has spent nothing yet. Leaving the last turn's total here
      // would make the strip report the previous run's tokens while this one
      // is still on its first request.
      next.turnUsage = null;
      next.activeTurnId = turnId ?? nextId("a");
      next.turnStartedAt = Date.now();
      // Create the assistant placeholder eagerly, keyed by the turn id, so the
      // first delta has somewhere to land. `message.started` also carries the
      // turn id, so both paths converge on the same message.
      upsert(next, blankMessage(next.activeTurnId, "assistant"));
      return next;
    }

    case "message.started": {
      // The core emits this once per assistant message, and only ever during
      // the turn that is running -- the parent's. A child's `message.started`
      // is a different turn: creating a placeholder for it here would put the
      // child's answer in this transcript one event after `turn.started`
      // declined to.
      //
      // A turn writes into one message across several passes, so a second
      // `message.started` is the same message beginning a new pass rather than
      // a new message: it moves the boundary `message.completed` replaces up to
      // here, which is what keeps the pass before it. See `passStart`.
      if (turnId && turnId === next.activeTurnId) {
        const target = currentAssistant(next, turnId);
        if (target) {
          target.passStart = target.text.length;
          upsert(next, target);
        } else {
          upsert(next, blankMessage(turnId, "assistant"));
        }
      }
      return next;
    }

    case "reasoning.delta": {
      // Appended exactly like `message.delta`, and kept on its own field. The
      // reasoning panel is the only thing that reads this; folding it into
      // `text` would put a model's scratchpad inside its own answer.
      //
      // The flat `reasoning` still accumulates the whole turn's thought -- it is
      // what a consumer that only wants "the reasoning" reads, and what the
      // empty-bubble guard checks. Alongside it, each pass is tracked as its own
      // run so the transcript can place it in order; the first delta of a pass
      // opens a run at the prose written so far, and later deltas extend it.
      const target = currentAssistant(next, turnId);
      if (target) {
        const chunk = payloadString(payload, "text") ?? "";
        target.reasoning += chunk;
        const runs = (target.reasonRuns ??= []);
        const open = runs[runs.length - 1];
        if (open && !open.complete) {
          open.text += chunk;
        } else {
          runs.push({ text: chunk, after: target.text.length, complete: false, truncated: false });
        }
        upsert(next, target);
      }
      return next;
    }

    case "reasoning.completed": {
      const target = currentAssistant(next, turnId);
      if (target) {
        // The core sends the authoritative final text, same contract as
        // `message.completed` -- but it is authoritative for *this pass* only,
        // because the core emits one completion per assistant pass. Replacing
        // the flat field with it used to delete every earlier pass's thought
        // the moment a second pass completed; the runs below are what keep each
        // pass's text where it belongs, and the flat field is rebuilt from them.
        const final = payloadString(payload, "text");
        const truncated = payload.truncated === true;
        const runs = (target.reasonRuns ??= []);
        const open = runs[runs.length - 1];
        if (open && !open.complete) {
          // Replace rather than append: a dropped delta must not leave a hole a
          // second copy would fill.
          if (final !== undefined) open.text = final;
          open.complete = true;
          open.truncated = truncated;
          if (truncated) open.notice = payloadString(payload, "notice");
        } else if (final !== undefined) {
          // A completion with no matching open run -- a hand-built or restored
          // message -- still gets a pass, so its thought is not dropped.
          runs.push({
            text: final,
            after: target.text.length,
            complete: true,
            truncated,
            ...(truncated ? { notice: payloadString(payload, "notice") } : {}),
          });
        }
        target.reasoning = runs.map((r) => r.text).join("");
        target.reasoningComplete = true;
        target.reasoningTruncated = runs.some((r) => r.truncated);
        if (target.reasoningTruncated) {
          target.reasoningNotice = runs.find((r) => r.truncated)?.notice;
        }
        upsert(next, target);
      }
      return next;
    }

    case "message.delta": {
      const target = currentAssistant(next, turnId);
      if (target) {
        target.text += payloadString(payload, "text") ?? "";
        upsert(next, target);
      }
      return next;
    }

    case "message.completed": {
      const target = currentAssistant(next, turnId);
      if (target) {
        // The core sends the authoritative final text, and it is authoritative
        // for *this pass* only. Replace rather than append: a delta stream that
        // lost a chunk must not be papered over by duplicating what did arrive.
        // Everything written before this pass is kept -- see `passStart`.
        const final = payloadString(payload, "text");
        if (final !== undefined) {
          target.text = target.text.slice(0, target.passStart ?? 0) + final;
        }
        upsert(next, target);
      }
      return next;
    }

    case "tool.started": {
      const target = currentAssistant(next, turnId);
      if (target) {
        target.tools = [
          ...target.tools,
          {
            id: payloadString(payload, "id") ?? String(target.tools.length),
            name: payloadString(payload, "name") ?? "tool",
            status: "running",
            startedAt: Date.now(),
            // Where this call falls in the prose so far. The model writes, then
            // asks for the tool, so this is the end of the words that asked for
            // it -- and the prose of the *next* pass lands after this mark, so
            // the rows and the paragraphs come out in the order they happened.
            after: target.text.length,
          },
        ];
        upsert(next, target);
      }
      return next;
    }

    case "tool.completed":
    case "tool.failed": {
      // Match on the tool call id rather than assuming the last one: the core
      // emits these per call id, and a wrong pairing would show one tool's
      // result under another tool's name.
      const id = payloadString(payload, "id");
      const target = currentAssistant(next, turnId);
      const call = target?.tools.find((t) => t.id === id) ?? target?.tools[target.tools.length - 1];
      if (target && call) {
        call.status = isFailure(payload.result) || type === "tool.failed" ? "failed" : "ok";
        // Stamped once: a repeated completion for the same call (a restored
        // batch, a duplicate frame) must not make the row look longer than the
        // work was.
        call.endedAt ??= Date.now();
        const detail = describeResult(payload.result);
        if (detail) call.detail = detail;
        // The same field the model reads in its own tool result, so the card
        // and the model cannot disagree about how far the turn got.
        const budget = readBudget(payload.tool_call_budget);
        if (budget) call.budget = budget;
        // Only a success carries a change. A failed write changed nothing,
        // and a badge the filesystem contradicts is worse than no badge.
        if (type === "tool.completed") {
          const change = readFileChange(payload.result);
          if (change) {
            call.path = change.path;
            call.added = change.added;
            call.removed = change.removed;
          }
        }
        upsert(next, target);
      }
      return next;
    }

    case "confirmation.requested": {
      // Payload keys mirror core/session.py::_on_confirmation_requested.
      next.pendingConfirm = {
        id: payloadString(payload, "id") ?? "",
        name: payloadString(payload, "name") ?? "tool",
        arguments: formatArguments(payload.arguments),
        description: payloadString(payload, "description") ?? "",
        destructive: payload.destructive === true,
      };
      return next;
    }

    case "confirmation.resolved": {
      next.pendingConfirm = null;
      return next;
    }

    case "user.asked": {
      // Payload keys mirror core/user_io.py::QuestionRequest.to_payload.
      next.pendingAsk = {
        id: payloadString(payload, "id") ?? "",
        name: payloadString(payload, "name") ?? "tool",
        kind: payloadString(payload, "kind") ?? "question",
        prompt: payloadString(payload, "prompt") ?? "",
        content: payloadString(payload, "content") ?? "",
        // Filtered rather than trusted: the options are what the buttons say,
        // and a non-string among them would render as an empty button the user
        // cannot choose between.
        options: Array.isArray(payload.options)
          ? payload.options.filter((option): option is string => typeof option === "string")
          : [],
      };
      return next;
    }

    case "user.resolved": {
      next.pendingAsk = null;
      return next;
    }

    case "turn.usage": {
      // The one number in this window that is a measurement rather than a
      // derivation. Absent entirely when the provider reported nothing -- which
      // is why the state starts null and stays null until a frame arrives.
      if (isForeignTurn(next, turnId)) return state;
      const count = (key: string) => {
        const value = payload[key];
        return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
      };
      const cost = payload.cost;
      next.turnUsage = {
        input: count("input_tokens"),
        output: count("output_tokens"),
        reasoning: count("reasoning_tokens"),
        cost: typeof cost === "number" && Number.isFinite(cost) ? cost : null,
      };
      return next;
    }

    case "turn.finished": {
      // A child's turn ending is not this turn ending. The parent's run has
      // more frames to come -- its tool result, its answer -- and they need
      // the placeholder this turn owns to still be the one they land in.
      if (isForeignTurn(next, turnId)) return state;
      next.activeTurnId = null;
      next.turnStartedAt = null;
      next.busy = false;
      // A cancelled turn is the one path that can end with a dialog still
      // outstanding -- the core settles both, but a turn the user stopped may
      // already be gone before the event lands. A dialog the turn can no
      // longer answer is a dialog that can never be closed, so they go here
      // too rather than waiting for the core to say so. `pendingConfirm` is
      // the same failure with a different button: a stopped turn whose
      // destructive call was still awaiting approval used to leave Allow / Deny
      // on screen over a turn that could no longer act on either.
      next.pendingAsk = null;
      next.pendingConfirm = null;
      dropEmptyAssistantMessages(next);
      return next;
    }

    case "turn.failed": {
      // A child's provider failure is a failed subagent, not a failed turn:
      // the parent reads it in the tool result and carries on. Showing it as a
      // banner mid-turn would report a failure the turn did not have.
      if (isForeignTurn(next, turnId)) return state;
      next.activeTurnId = null;
      next.turnStartedAt = null;
      next.busy = false;
      next.error =
        payloadString(payload, "message") ?? payloadString(payload, "error") ?? "The turn failed.";
      // Same reason as `turn.finished`: a turn that failed while a prompt was
      // up will never answer it.
      next.pendingAsk = null;
      next.pendingConfirm = null;
      dropEmptyAssistantMessages(next);
      return next;
    }

    case "error": {
      if (isForeignTurn(next, turnId)) return state;
      next.activeTurnId = null;
      next.turnStartedAt = null;
      next.busy = false;
      next.error = payloadString(payload, "message") ?? "Backend error.";
      // Deliberately not clearing the dialogs here: `error` also arrives
      // outside a turn (an unknown provider, say), and a stray frame must not
      // close a prompt a live turn is still waiting on. The two terminal turn
      // frames above are the ones that mean "this turn is over".
      dropEmptyAssistantMessages(next);
      return next;
    }

    default:
      // sandbox.* and log are consumed elsewhere; unknown event types are
      // ignored rather than throwing, so the core can add one without
      // breaking an older shell.
      return state;
  }
}

/** Append a locally-composed user message. Sent optimistically, before the
 *  core echoes anything back. */
export function appendUserMessage(state: ChatState, text: string): ChatState {
  return {
    ...state,
    messages: [...state.messages, { ...blankMessage(nextId("u"), "user"), text }],
  };
}

export { TERMINAL };
