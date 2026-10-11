import { useRef, useState, type RefObject } from "react";

import {
  MAX_ATTACHMENTS,
  fileSize,
  imagesFromClipboard,
  readFile,
  rejectionReason,
  type PendingAttachment,
} from "./attachments.js";
import { ToolBudgetControl } from "./ToolBudgetControl.js";

/** One entry in the `mode.list` reply. */
export interface ModeInfo {
  name: string;
  label: string;
  description: string;
  writes: boolean;
}

interface Props {
  busy: boolean;
  disabled: boolean;
  /** Modes from the core, in display order. Never hardcoded here. */
  modes: ModeInfo[];
  /** The mode actually in force, as the core last reported it. */
  mode: string;
  onModeChange: (name: string) => void;
  onSend: (text: string, attachments: PendingAttachment[]) => void;
  onCancel: () => void;
  /**
   * How many tool calls one turn may make, or null while it is being read.
   *
   * Null and zero are different things and both are refused: null has not
   * answered yet, zero would refuse every tool and is a different product.
   * The control says "reading" rather than drawing a number it does not have.
   */
  maxToolCalls: number | null;
  budgetOpen: boolean;
  onBudgetOpen: () => void;
  onBudgetClose: () => void;
  onBudgetChange: (limit: number) => void;
  /**
   * The textarea, so the window can move focus into it.
   *
   * Optional and injected rather than imported, because "put the caret here" is
   * the one thing about the composer that belongs to the *window* rather than
   * to the composer: switching conversation closes the sidebar, and a sidebar
   * that closes under the caret without putting it somewhere deliberate leaves
   * a keyboard user tabbing from the top of the document every time. The
   * composer still owns the element; it just does not decide when it is
   * focused.
   */
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}

export function Composer({
  busy,
  disabled,
  modes,
  mode,
  onModeChange,
  onSend,
  onCancel,
  maxToolCalls,
  budgetOpen,
  onBudgetOpen,
  onBudgetClose,
  onBudgetChange,
  inputRef,
}: Props) {
  const [text, setText] = useState("");
  // The files read so far. Held here rather than in the window because they
  // belong to the message being composed, and a send clears them.
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  // Why the last pick was refused, if it was. Local too: it is about the
  // composer field the user is looking at, and it clears when they try again.
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Drive the pill highlight from what the core reports, not from local
  // state. A local `setMode` would paint "Plan" the instant it was clicked
  // and leave it painted if the switch were refused -- the exact class of
  // lie this project keeps having to unpick.
  const active = modes.find((m) => m.name === mode);
  const readOnly = active !== undefined && !active.writes;

  const submit = () => {
    const trimmed = text.trim();
    // A message with files and no words is a real message -- "what is in
    // this screenshot?" -- so the files alone are enough to send. Requiring
    // text would make the obvious use of the feature the one thing it cannot
    // do.
    if ((!trimmed && attachments.length === 0) || busy || disabled) return;
    onSend(trimmed, attachments);
    setText("");
    setAttachments([]);
  };

  /**
   * Take files into the pending strip, with the limits and the reporting.
   *
   * One routine for both ways in -- the file picker and a paste -- because two
   * copies of this is two copies of the rule, and the second one is the one
   * that forgets the limit.
   *
   * Names are made unique against what is already queued, which is why this
   * takes the current list rather than reading state inside an updater: the
   * rename has to happen before `readFile`, so that the name it reports is the
   * name the strip shows. Two screenshots pasted one after the other are both
   * called `pasted-1.png` by the clipboard reader, and two attachments with
   * the same name are a bug -- `removeAttachment` deletes by name, so the
   * first click on either one would remove both.
   */
  const acceptFiles = async (files: File[]) => {
    if (files.length === 0) return;
    setAttachmentError(null);

    const queued = new Set(attachments.map((a) => a.name));
    const named = files.map((file) => {
      if (!queued.has(file.name)) return file;
      const dot = file.name.lastIndexOf(".");
      const stem = dot > 0 ? file.name.slice(0, dot) : file.name;
      const ext = dot > 0 ? file.name.slice(dot) : "";
      let n = 2;
      while (queued.has(`${stem}-${n}${ext}`)) n += 1;
      return new File([file], `${stem}-${n}${ext}`, { type: file.type });
    });

    const room = MAX_ATTACHMENTS - attachments.length;
    if (named.length > room) {
      setAttachmentError(
        `Only ${MAX_ATTACHMENTS} files can go with one message. ${named.length - room} were not added.`,
      );
    }
    const wanted = named.slice(0, room);
    const accepted: PendingAttachment[] = [];
    for (const file of wanted) {
      const reason = rejectionReason(file);
      if (reason) {
        setAttachmentError(reason);
        continue;
      }
      try {
        accepted.push(await readFile(file));
      } catch (error) {
        setAttachmentError(error instanceof Error ? error.message : String(error));
      }
    }
    if (accepted.length > 0) setAttachments((prev) => [...prev, ...accepted]);
  };

  const onFilesChosen = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    // Reset immediately. Without this the same file cannot be picked twice in
    // a row, because the input still holds it and change does not fire.
    event.target.value = "";
    await acceptFiles(files);
  };

  /**
   * Ctrl+V with a picture on the clipboard attaches it.
   *
   * A pasted screenshot is the one attachment nobody has a file for, and
   * making them reach for the file picker to send it would be the whole
   * feature missing.
   *
   * **The default is only cancelled when a picture was actually taken.** A
   * paste with no image on it is a text paste, and swallowing that would
   * break the most ordinary thing a text field does. So the check comes first
   * and `preventDefault` happens after, never the other way round.
   */
  const onPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const images = imagesFromClipboard(event.clipboardData);
    if (images.length === 0) return;
    event.preventDefault();
    void acceptFiles(images);
  };

  const removeAttachment = (name: string) => {
    setAttachments((prev) => prev.filter((a) => a.name !== name));
  };

  return (
    <div className="composer">
      <div className="composer-inner">
        <textarea
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
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

        {/*
          What is about to go. Without this the only sign an attachment exists
          is a message that suddenly contains a screenshot, and there is no way
          to take one back before sending -- a mistake the user finds out about
          only after the model has already answered it.
        */}
        {attachments.length > 0 && (
          <ul className="attach-strip" aria-label="Files to send">
            {attachments.map((file) => (
              <li key={file.name} className="attach-item">
                {file.preview ? (
                  <img className="attach-thumb" src={file.preview} alt="" />
                ) : (
                  <span className="attach-doc" aria-hidden="true">
                    TXT
                  </span>
                )}
                <span className="attach-name" title={file.name}>
                  {file.name}
                </span>
                <span className="attach-size">{fileSize(file.size)}</span>
                <button
                  type="button"
                  className="attach-remove"
                  onClick={() => removeAttachment(file.name)}
                  title={`Remove ${file.name}`}
                  aria-label={`Remove ${file.name}`}
                >
                  &times;
                </button>
              </li>
            ))}
          </ul>
        )}

        {/*
          A refusal is shown here, not logged. "That file type is not
          supported" is the whole feedback a user gets, and a console warning
          is feedback nobody sees.
        */}
        {attachmentError && (
          <p className="attach-error" role="alert">
            {attachmentError}
          </p>
        )}

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

          {/*
            The tool budget sits beside the model rather than in the settings
            panel because it is per turn, not per install: a user who keeps
            hitting the cap is making that decision constantly, and a dialog
            they have to open to raise it is a dialog they will not open.
          */}
          <ToolBudgetControl
            value={maxToolCalls}
            disabled={disabled}
            open={budgetOpen}
            onOpen={onBudgetOpen}
            onClose={onBudgetClose}
            onChange={onBudgetChange}
          />

          <div className="composer-spacer" />

          {/*
            The native folder picker in dialog.ts is not reused here on
            purpose: it hands back a path because the core gives one to the
            sandbox, and this needs the file's bytes. A file input hands back
            a File, so no Rust command, no capability and no rebuild stand
            between picking a screenshot and the model seeing it.
          */}
          <button
            type="button"
            className="icon-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || attachments.length >= MAX_ATTACHMENTS}
            title="Attach an image or a text file"
            aria-label="Attach a file"
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
          <input
            ref={fileInputRef}
            className="file-input"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,image/gif,.txt,.md,.csv,.html,.json,.py,.yaml,.yml,.xml,.sh"
            onChange={onFilesChosen}
          />

          {busy ? (
            // An icon in the send button's own box, not a text pill.
            //
            // It used to be a `btn` with the word "Stop" in it, which is two
            // sizes wider than the icon it replaces -- so the control row
            // reflowed every time a turn started, dragging the model chip and
            // the `+` beside it sideways mid-turn. A control that moves while
            // you are using it is a control you have to hunt for again.
            //
            // Filled like send rather than outlined: this is the button that
            // stops what is happening, and leaving the accent on the send
            // button's own position would make the two hard to tell apart at a
            // glance -- which is precisely when you need to.
            <button
              type="button"
              className="icon-btn stop-btn"
              onClick={onCancel}
              aria-label="Stop"
              title="Stop"
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="currentColor"
                aria-hidden="true"
              >
                <rect x="6" y="6" width="12" height="12" rx="1.5" />
              </svg>
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
