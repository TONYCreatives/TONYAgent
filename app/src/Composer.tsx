import { useState } from "react";

interface Props {
  busy: boolean;
  disabled: boolean;
  model: string;
  onSend: (text: string) => void;
  onCancel: () => void;
}

/**
 * Composer modes, matching the reference's selector.
 *
 * These are presentation-only for now: there is no protocol method to set a
 * mode, and inventing one client-side would let the UI claim a capability the
 * core does not have. Only Build is active; the rest render as available-looking
 * but inert, which is honest about the current state.
 */
const MODES = ["Build", "Plan", "Mission", "Skills"] as const;
type Mode = (typeof MODES)[number];

export function Composer({ busy, disabled, model, onSend, onCancel }: Props) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("Build");

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
          placeholder="Type a message — / for skills, @ for threads or files"
          disabled={disabled}
          rows={2}
        />

        <div className="composer-row">
          <div className="mode-group" role="group" aria-label="Mode">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                className={`mode${m === mode ? " is-active" : ""}`}
                onClick={() => setMode(m)}
                aria-pressed={m === mode}
              >
                {m}
              </button>
            ))}
          </div>

          <button type="button" className="chip" title="Model — coming soon">
            <span>{model || "No model"}</span>
            <span className="chip-caret">&#9662;</span>
          </button>

          <div className="composer-spacer" />

          <button
            type="button"
            className="icon-btn"
            disabled
            title="Attach — coming soon"
            aria-label="Attach"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>

          {busy ? (
            <button type="button" className="btn" onClick={onCancel}>
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-accent"
              onClick={submit}
              disabled={disabled}
            >
              Continue
            </button>
          )}
        </div>
      </div>
      <p className="hint">Enter to send &middot; Shift+Enter for a new line</p>
    </div>
  );
}
