import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "./events.js";
import { MarkdownText } from "./MarkdownText.js";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
}

const STATUS_MARK: Record<"running" | "ok" | "failed", string> = {
  running: "*",
  ok: "+",
  failed: "!",
};

/**
 * Is this the last call the turn can afford?
 *
 * Parsed out of the label rather than carried as a field, because the label
 * is what the core sends and the two could otherwise disagree. The threshold
 * is the last two calls, not one: a model that gets refused on the call it
 * was told it could make has already wasted that call, and the warning that
 * would have helped arrived one step too late.
 */
function isNearLimit(budget: string): boolean {
  const match = /^Tool call (\d+)\/(\d+)$/.exec(budget);
  if (!match) return false;
  const index = Number(match[1]);
  const limit = Number(match[2]);
  if (limit <= 0) return false;
  return index >= limit - 1;
}

/** One tool invocation inside an assistant message. */
function ToolRow({ tool }: { tool: ChatMessage["tools"][number] }) {
  return (
    <div className={`tool tool-${tool.status}`}>
      <span className="tool-mark" aria-hidden="true">
        {STATUS_MARK[tool.status]}
      </span>
      <span className="tool-name">{tool.name}</span>
      {tool.budget && (
        // The number the model also read, so the reader can see the turn
        // approaching its limit rather than discovering it from an error.
        <span
          className={`tool-budget${isNearLimit(tool.budget) ? " is-near-limit" : ""}`}
          title="Tool calls used in this turn"
        >
          {tool.budget}
        </span>
      )}
      {tool.detail && <span className="tool-detail">{tool.detail}</span>}
    </div>
  );
}

/**
 * What the model thought, above the answer it produced.
 *
 * Open while the thinking is still arriving and folded once it is done: the
 * trace is often longer than the answer, and a transcript of a session where
 * every reply is twice its own length is one nobody reads. Folding it is not
 * discarding it -- the text stays on the message and reopens with a click, and
 * it is still in the saved conversation, so a reopened chat shows the same
 * thing this one did.
 *
 * Rendered only when there is something to show. A model that does not
 * reason gets no panel, not an empty one, because a permanently collapsed
 * "Thinking" header on every answer is furniture the user has to learn to
 * ignore.
 */
function ThinkingPanel({ message }: { message: ChatMessage }) {
  const hasReasoning = message.reasoning.trim() !== "";
  // Born folded if this message was restored with its thinking already
  // complete, open if the thinking is still arriving.
  const [open, setOpen] = useState(!message.reasoningComplete);
  // Set once the reader has made their own choice, so finishing the stream
  // does not fold a panel they opened on purpose.
  const touched = useRef(false);

  useEffect(() => {
    if (message.reasoningComplete && !touched.current) setOpen(false);
  }, [message.reasoningComplete]);

  if (!hasReasoning && !message.reasoningTruncated) return null;

  const toggle = () => {
    touched.current = true;
    setOpen((was) => !was);
  };

  return (
    <div className={`thinking${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="thinking-head"
        onClick={toggle}
        aria-expanded={open}
      >
        <span className="thinking-caret">{open ? "▾" : "▸"}</span>
        <span>Thinking</span>
        {message.reasoningTruncated && (
          // The turn produced no answer at all; the notice below says why, and
          // the badge says it without having to open anything.
          <span className="thinking-warn" title={message.reasoningNotice}>
            ran out of budget
          </span>
        )}
        {!message.reasoningComplete && <span className="thinking-live">…</span>}
      </button>
      {message.reasoningNotice && (
        <p className="thinking-notice">{message.reasoningNotice}</p>
      )}
      {open && hasReasoning && <div className="thinking-body">{message.reasoning}</div>}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`row ${isUser ? "row-user" : "row-assistant"}`}>
      <div className={`bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
        {!isUser && <ThinkingPanel message={message} />}
        {/*
          Only assistant text is Markdown. A user's message is shown exactly as
          typed -- someone pasting `**not bold**` meant the asterisks.
        */}
        {message.text &&
          (isUser ? (
            <div className="bubble-text">{message.text}</div>
          ) : (
            <MarkdownText text={message.text} />
          ))}
        {message.tools.length > 0 && (
          <div className="tools">
            {message.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function MessageList({ messages, busy }: Props) {
  // Pin to the bottom as tokens stream in. Keyed on message count rather than
  // text, so this does not fire on every delta.
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, busy]);

  if (messages.length === 0) {
    return (
      <div className="empty">
        <h1>TONYAgent</h1>
        <p>Ask for something. The agent will use its tools to do it.</p>
      </div>
    );
  }

  return (
    <div className="transcript">
      <div className="transcript-inner">
        {messages.map((message) => (
          <Bubble key={message.id} message={message} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
