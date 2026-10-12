/**
 * What the desktop pet says, derived from the chat state.
 *
 * The state is the reducer's, not a second one. `events.ts` already turns the
 * core's stream into "busy", "which tool is running", "blocked on the user",
 * "failed" — and that is exactly the pet's vocabulary. A second reading of the
 * raw events here would be a second opinion about the same turn, and the two
 * would disagree the first time one of them was changed.
 *
 * **The order below is the whole design.** One thing at a time can be true on the
 * card, and the things are not equally important: a turn that is waiting for the
 * user is *not* working, however busy the reducer still says it is — a tool that
 * stopped to ask a question keeps the turn open while nothing at all happens.
 * So waiting comes first, failure second, work third, and idle last.
 */

import type { ChatState, ToolCall } from "./events.js";

export type PetMood = "idle" | "working" | "waiting" | "failed";

export interface PetStatus {
  mood: PetMood;
  /** The headline: at most a few words, and never a sentence. */
  label: string;
  /** The second line, which may be empty. Whatever is most specific. */
  detail: string;
}

/** The last tool call that has not finished, if the turn is inside one. */
function runningTool(state: ChatState): ToolCall | null {
  for (let i = state.messages.length - 1; i >= 0; i -= 1) {
    const tools = state.messages[i].tools;
    for (let j = tools.length - 1; j >= 0; j -= 1) {
      if (tools[j].status === "running") return tools[j];
    }
  }
  return null;
}

/**
 * The first line of something the user will otherwise be shown in full.
 *
 * A card two inches wide cannot hold a paragraph, and truncating mid-word is
 * worse than stopping at the first line: the tool that failed usually says what
 * it was on the first line, and the rest is stack.
 */
export function firstLine(text: string): string {
  const line = (text ?? "").split("\n").map((one) => one.trim()).find(Boolean) ?? "";
  return line.length > 120 ? `${line.slice(0, 117)}...` : line;
}

export function petStatus(state: ChatState): PetStatus {
  // Waiting first. See the note above: a turn blocked on the user is not working.
  if (state.pendingConfirm) {
    return {
      mood: "waiting",
      label: state.pendingConfirm.destructive ? "Needs your approval" : "Waiting for you",
      detail: firstLine(state.pendingConfirm.description) || state.pendingConfirm.name,
    };
  }
  if (state.pendingAsk) {
    return {
      mood: "waiting",
      label: "Asked you something",
      detail: firstLine(state.pendingAsk.prompt) || state.pendingAsk.name,
    };
  }
  if (state.error) {
    return { mood: "failed", label: "Stopped with an error", detail: firstLine(state.error) };
  }
  if (state.busy) {
    const tool = runningTool(state);
    return {
      mood: "working",
      label: tool ? `Running ${tool.name}` : "Thinking",
      // A running tool has no result yet, so `detail` is usually empty -- and an
      // empty second line is better than the word "undefined" beside a spinner.
      detail: tool?.detail ? firstLine(tool.detail) : "",
    };
  }
  return { mood: "idle", label: "Ready when you are", detail: "" };
}
