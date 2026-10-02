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
}

/** Events that mean the turn is over, successfully or not. */
const TERMINAL = new Set(["turn.finished", "turn.failed"]);

let counter = 0;
/** Monotonic id for messages the frontend creates, not the core. */
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export interface ChatState {
  messages: ChatMessage[];
  busy: boolean;
  /** Set when the core reports turn.failed or an error event arrives. */
  error: string | null;
  /** Non-null while a confirmation.requested is awaiting a response. */
  pendingConfirm: {
    id: string;
    name: string;
    arguments: string;
    description: string;
    destructive: boolean;
  } | null;
}

export const initialState: ChatState = {
  messages: [],
  busy: false,
  error: null,
  pendingConfirm: null,
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
  return state.messages.map((m) => ({ ...m, tools: m.tools.map((t) => ({ ...t })) }));
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

  switch (type) {
    case "turn.started": {
      next.busy = true;
      next.error = null;
      // Create the assistant placeholder eagerly, keyed by the turn id, so the
      // first delta has somewhere to land. `message.started` also carries the
      // turn id, so both paths converge on the same message.
      upsert(next, blankMessage(turnId ?? nextId("a"), "assistant"));
      return next;
    }

    case "message.started": {
      // The core emits this once per assistant message. If `turn.started` was
      // missed (events replayed from a sequence, say) the placeholder is
      // created here instead.
      if (!currentAssistant(next, turnId) && turnId) {
        upsert(next, blankMessage(turnId, "assistant"));
      }
      return next;
    }

    case "reasoning.delta": {
      // Appended exactly like `message.delta`, and kept on its own field. The
      // reasoning panel is the only thing that reads this; folding it into
      // `text` would put a model's scratchpad inside its own answer.
      const target = currentAssistant(next, turnId);
      if (target) {
        target.reasoning += payloadString(payload, "text") ?? "";
        upsert(next, target);
      }
      return next;
    }

    case "reasoning.completed": {
      const target = currentAssistant(next, turnId);
      if (target) {
        // The core sends the authoritative final text, same contract as
        // `message.completed`. Replace rather than append: a dropped delta must
        // not leave a hole that a second copy of the text would fill.
        const final = payloadString(payload, "text");
        if (final !== undefined) target.reasoning = final;
        target.reasoningComplete = true;
        target.reasoningTruncated = payload.truncated === true;
        if (target.reasoningTruncated) {
          target.reasoningNotice = payloadString(payload, "notice");
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
        // The core sends the authoritative final text. Replace rather than
        // append: a delta stream that lost a chunk must not be papered over by
        // duplicating what did arrive.
        const final = payloadString(payload, "text");
        if (final !== undefined) target.text = final;
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

    case "turn.finished": {
      next.busy = false;
      dropEmptyAssistantMessages(next);
      return next;
    }

    case "turn.failed": {
      next.busy = false;
      next.error =
        payloadString(payload, "message") ?? payloadString(payload, "error") ?? "The turn failed.";
      dropEmptyAssistantMessages(next);
      return next;
    }

    case "error": {
      next.busy = false;
      next.error = payloadString(payload, "message") ?? "Backend error.";
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
