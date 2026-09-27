import { useEffect, useRef } from "react";
import type { ChatMessage } from "./events";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
}

const STATUS_MARK: Record<"running" | "ok" | "failed", string> = {
  running: "*",
  ok: "+",
  failed: "!",
};

/** One tool invocation inside an assistant message. */
function ToolRow({ tool }: { tool: ChatMessage["tools"][number] }) {
  return (
    <div className={`tool tool-${tool.status}`}>
      <span className="tool-mark" aria-hidden="true">
        {STATUS_MARK[tool.status]}
      </span>
      <span className="tool-name">{tool.name}</span>
      {tool.detail && <span className="tool-detail">{tool.detail}</span>}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`row ${isUser ? "row-user" : "row-assistant"}`}>
      <div className={`bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
        {message.text && <div className="bubble-text">{message.text}</div>}
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
  // Pin to the bottom as tokens stream in. `messages.length` rather than the
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
      {messages.map((message) => (
        <Bubble key={message.id} message={message} />
      ))}
      <div ref={endRef} />
    </div>
  );
}
