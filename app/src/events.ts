/**
 * Reduces the core's event stream into something a component can render.
 *
 * All of this is presentation state. There is no turn logic here on purpose:
 * the core decides what a tool call means and when it is finished, and this
 * layer only reflects that. A second opinion about turn state in the frontend
 * is how the Tkinter app ended up with a `schedule_on_ui` layer that silently
 * dropped callbacks.
 */

import type { CoreEvent } from "./backend";

export type Role = "user" | "assistant" | "system";

export interface ToolCall {
  id: string;
  name: string;
  status: "running" | "ok" | "failed";
  /** Human-readable outcome, derived from the core's `result` dict. */
  detail?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  tools: ToolCall[];
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

export function applyEvent(state: ChatState, event: CoreEvent): ChatState {
  const next: ChatState = {
    ...state,
    messages: state.messages.slice(),
  };
  const { type, turn_id: turnId, payload } = event;

  switch (type) {
    case "turn.started": {
      next.busy = true;
      next.error = null;
      // Create the assistant placeholder eagerly, keyed by the turn id, so the
      // first delta has somewhere to land. `message.started` also carries the
      // turn id, so both paths converge on the same message.
      upsert(next, { id: turnId ?? nextId("a"), role: "assistant", text: "", tools: [] });
      return next;
    }

    case "message.started": {
      // The core emits this once per assistant message. If `turn.started` was
      // missed (events replayed from a sequence, say) the placeholder is
      // created here instead.
      if (!currentAssistant(next, turnId) && turnId) {
        upsert(next, { id: turnId, role: "assistant", text: "", tools: [] });
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
        call.status = type === "tool.failed" ? "failed" : "ok";
        const detail = describeResult(payload.result);
        if (detail) call.detail = detail;
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
      // Drop an assistant placeholder the core never wrote to, so an
      // immediately-rejected turn does not leave an empty bubble behind.
      next.messages = next.messages.filter((m) => m.text.trim() !== "" || m.tools.length > 0);
      return next;
    }

    case "turn.failed": {
      next.busy = false;
      next.error =
        payloadString(payload, "message") ?? payloadString(payload, "error") ?? "The turn failed.";
      return next;
    }

    case "error": {
      next.busy = false;
      next.error = payloadString(payload, "message") ?? "Backend error.";
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
    messages: [...state.messages, { id: nextId("u"), role: "user", text, tools: [] }],
  };
}

export { TERMINAL };
