import { useCallback, useEffect, useRef } from "react";

import type { ChatState } from "./events.js";

interface Props {
  /**
   * What to ask.
   *
   * Deliberately not nullable, for the same reason `ConfirmDialog`'s is not:
   * whether to show it belongs to the `Overlay` the window puts around this,
   * and that overlay keeps the dialog mounted for the length of its exit
   * animation -- so the window holds on to the last request rather than passing
   * null.
   */
  request: NonNullable<ChatState["pendingAsk"]>;
  onRespond: (id: string, answer: string) => void;
}

/**
 * The one surface that asks the user anything.
 *
 * The core is blocked while this is up -- the tool that raised it is suspended
 * on a future, and the turn cannot continue until `user.respond` arrives -- so
 * this is a modal and not a banner, and it is not dismissible by clicking away:
 * a stray click must not be readable as an answer. Escape *does* dismiss it,
 * but only ever by answering with nothing.
 *
 * Two kinds, one dialog. A **question** wants an answer, so it offers the
 * core's options as buttons and a box to write in; a **presentation** wants the
 * user to have seen something, so it shows the content and any reply is theirs
 * to write. The difference is the copy and the buttons, not two components --
 * the difference the core cares about (what a non-answer means) is decided on
 * the core's side of the wire, in `tonyagent.core.user_io`.
 */
export function QuestionDialog({ request, onRespond }: Props) {
  /**
   * The ask already answered, if any.
   *
   * Keyed on the id so the guard releases by itself for the next ask, exactly
   * as `ConfirmDialog` does: a second ask can arrive while this one is still
   * fading out, and a reset that has to be remembered is a reset that gets
   * forgotten.
   */
  const answered = useRef<string | null>(null);
  const note = useRef<HTMLTextAreaElement | null>(null);

  /**
   * Answer once, whichever way the answer arrived.
   *
   * The buttons, the text box and the key handler all come through here rather
   * than calling `onRespond` themselves, because "exactly once" has to be a
   * property of the component: a held-down key emits repeats, and the dialog is
   * still mounted and still listening for the length of its own exit animation.
   */
  const answer = useCallback(
    (text: string) => {
      if (answered.current === request.id) return;
      answered.current = request.id;
      onRespond(request.id, text.trim());
    },
    [request.id, onRespond],
  );

  /**
   * Escape answers with nothing, and nothing behind this dialog hears the key.
   *
   * Capture, and stop here, for the same reason `ConfirmDialog` stops it: the
   * Files overlay and a conversation's row menu both read Escape to mean
   * "close", and neither of them is what the user is looking at.
   *
   * An empty answer rather than a refusal or a "cancelled" state, because there
   * is no third thing to send -- the core treats an empty answer as "no
   * comment", which is a real answer the model can act on, and it is the honest
   * one for a user who reached for the key that gets a screen out of the way.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      answer("");
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [answer]);

  const isPresentation = request.kind === "presentation";
  const hasOptions = !isPresentation && request.options.length > 0;

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="ask-title">
      <h2 id="ask-title">
        {isPresentation ? request.prompt : "The agent has a question"}
      </h2>
      <p className="ask-from">{request.name}</p>

      {isPresentation ? (
        /*
         * `pre-wrap` in the stylesheet rather than a `<pre>` element: the
         * content keeps the line breaks the core wrote and still wraps, so a
         * long line does not run out of the panel the way a `<pre>` would.
         */
        <div className="ask-body">{request.content}</div>
      ) : (
        <p className="ask-question">{request.prompt}</p>
      )}

      {hasOptions && (
        <div className="ask-options">
          {request.options.map((option, index) => (
            <button
              key={option}
              type="button"
              className="btn btn-option"
              /* The first option takes focus, so the keyboard can answer
                 without tabbing through the panel first. */
              autoFocus={index === 0}
              onClick={() => answer(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      <label className="ask-note-label" htmlFor="ask-note">
        {isPresentation ? "Add a note (optional)" : "Or write your own answer"}
      </label>
      <textarea
        id="ask-note"
        ref={note}
        className="ask-note"
        rows={isPresentation ? 3 : 2}
        placeholder={
          isPresentation ? "Anything you want the agent to know." : "Type an answer."
        }
        /* Enter sends, because this is a one-line answer as often as not and
           reaching for the mouse on a modal that already has the keyboard's
           attention is the slower path. Shift+Enter is still a newline. */
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.shiftKey) return;
          event.preventDefault();
          answer(event.currentTarget.value);
        }}
      />

      <div className="modal-actions">
        <button
          type="button"
          className="btn btn-accent"
          onClick={() => answer(note.current?.value ?? "")}
        >
          {isPresentation ? "Acknowledge" : "Send answer"}
        </button>
      </div>
    </div>
  );
}
