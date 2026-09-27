import { useState } from "react";

interface Props {
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function Composer({ busy, disabled, onSend, onCancel }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    // An empty message is not an error worth surfacing; just ignore it.
    if (!trimmed || busy || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="composer">
      <div className="composer-inner">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          // Enter sends, Shift+Enter inserts a newline. Matches the Tkinter UI's
          // Ctrl+Enter modifier, minus the modifier, since a web text field
          // already treats Enter as "submit" in the user's mental model.
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={disabled ? "Start the backend to chat" : "Ask TONYAgent to do something..."}
          disabled={disabled}
          rows={1}
        />
        {busy ? (
          <button type="button" className="btn" onClick={onCancel}>
            Stop
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={submit} disabled={disabled}>
            Send
          </button>
        )}
      </div>
      <p className="hint">Enter to send &middot; Shift+Enter for a new line</p>
    </div>
  );
}
