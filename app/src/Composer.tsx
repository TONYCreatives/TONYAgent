import { useState } from "react";

/** One entry in the `mode.list` reply. */
export interface ModeInfo {
  name: string;
  label: string;
  description: string;
  writes: boolean;
}

/** What the bound model says about its own thinking. */
export interface ReasoningInfo {
  supported: boolean;
  /** Efforts the model accepts, in the provider's own order. */
  efforts: string[];
  default_effort: string;
  mandatory: boolean;
  effort: string;
}

interface Props {
  busy: boolean;
  disabled: boolean;
  model: string;
  /** Modes from the core, in display order. Never hardcoded here. */
  modes: ModeInfo[];
  /** The mode actually in force, as the core last reported it. */
  mode: string;
  /**
   * Reasoning support for the bound model, or null while it is being read.
   *
   * Null and "not supported" are deliberately different: the first has not
   * answered yet and the control stays put, the second has and the control
   * goes away.
   */
  reasoning: ReasoningInfo | null;
  onReasoningChange: (effort: string) => void;
  onModeChange: (name: string) => void;
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function Composer({
  busy,
  disabled,
  model,
  modes,
  mode,
  reasoning,
  onReasoningChange,
  onModeChange,
  onSend,
  onCancel,
}: Props) {
  const [text, setText] = useState("");

  // Drive the pill highlight from what the core reports, not from local
  // state. A local `setMode` would paint "Plan" the instant it was clicked
  // and leave it painted if the switch were refused -- the exact class of
  // lie this project keeps having to unpick.
  const active = modes.find((m) => m.name === mode);
  const readOnly = active !== undefined && !active.writes;

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
          className={readOnly ? "is-readonly" : undefined}
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
            {modes.map((m) => (
              <button
                key={m.name}
                type="button"
                className={`mode${m.name === mode ? " is-active" : ""}`}
                // The description is the whole point of the mode, and the
                // permission difference is not visible from the label.
                title={m.description}
                onClick={() => onModeChange(m.name)}
                aria-pressed={m.name === mode}
                disabled={disabled}
              >
                {m.label}
              </button>
            ))}
          </div>

          <button type="button" className="chip" title="Model — coming soon">
            <span>{model || "No model"}</span>
            <span className="chip-caret">&#9662;</span>
          </button>

          {/*
            Only for a model that reports a dial. A model that cannot reason,
            and a model that reasons with no choice to make, both get nothing
            here: a control that cannot change anything teaches the reader that
            this row is decoration.
          */}
          {reasoning && reasoning.efforts.length > 0 && (
            <label className="chip thinking-chip" title="How hard the model should think">
              <span className="thinking-chip-label">Thinking</span>
              <select
                className="thinking-select"
                value={reasoning.effort}
                onChange={(e) => onReasoningChange(e.target.value)}
                disabled={disabled || busy}
                aria-label="Thinking effort"
              >
                {/*
                  "default" is the absence of a choice, and it is always
                  offered: the model knows better than a hardcoded guess what
                  its own budget should be.
                */}
                <option value="">default{reasoning.default_effort ? ` (${reasoning.default_effort})` : ""}</option>
                {reasoning.efforts.map((effort) => (
                  <option key={effort} value={effort}>
                    {effort}
                  </option>
                ))}
              </select>
            </label>
          )}

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
              className="icon-btn send-btn"
              onClick={submit}
              disabled={disabled}
              // The icon carries the meaning, so the name has to be in the
              // accessibility tree rather than in the pixels. "Continue" was
              // both wrong as a word and invisible to a screen reader here.
              aria-label="Send"
              title="Send"
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M4.5 12h13" />
                <path d="M12.5 6.5 18.5 12l-6 5.5" />
              </svg>
            </button>
          )}
        </div>
      </div>
      {/*
        A read-only mode is a permission, not a suggestion, so it is stated
        here rather than left to be discovered when a write is refused.
      */}
      <p className="hint">
        {readOnly
          ? `${active.label} mode — the agent can read and search, but writes are refused.`
          : "Enter to send · Shift+Enter for a new line"}
      </p>
    </div>
  );
}
