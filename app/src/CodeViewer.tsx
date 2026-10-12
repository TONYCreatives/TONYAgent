/**
 * The file viewer: code, pictures, and the things a window cannot draw.
 *
 * **Three kinds, and the core decides which.** `files.read` answers with
 * `text`, `image` or `binary`, because the core has the bytes -- an image is
 * an image because it decodes, a `.zip` is a file this window can name but
 * not draw, and only "that is not there" is an error. A pane that rendered
 * all three as text would show a megabyte of replacement characters for a
 * photograph; one that refused everything it could not draw would be useless
 * for the half of a project that is not source.
 *
 * **It is editable when the user says so, and read-only when the agent is
 * working.** The read-only switch is the user's; the turn lock overrides it,
 * because a file being written underneath a caret is a worse thing to offer
 * than a disabled one. Both are stated in the header rather than implied by
 * whether the caret appears.
 *
 * **Editing is a textarea over the highlighted rows.** Not a rich editor and
 * not a second renderer: the highlighted `<pre>` is what the eye reads, and a
 * transparent textarea sits exactly on top of it, so the caret, the
 * selection, the undo stack and the input method are the browser's own. The
 * two layers share a font, a line height, a tab size and a gutter width --
 * the last of those is one CSS variable read by both rule sets, because a
 * gutter that drifts one pixel puts the caret in the wrong word.
 *
 * What that buys and what it costs, stated plainly: no autocomplete, no
 * multi-cursor, no bracket matching, and typing at the very bottom of a long
 * file does not scroll the caret into view by itself -- the highlight layer
 * is virtualised and the textarea is not, so the container is the thing that
 * scrolls. It is a viewer that can be typed into, which is what was asked
 * for, rather than an IDE.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { colorFor, paletteFor, PALETTES, tokenize, type Palette, type Token } from "./highlight.js";
import { ListPicker } from "./ListPicker.js";
import { MarkdownText } from "./MarkdownText.js";
import { parseTable, delimiterFor, MAX_TABLE_ROWS } from "./table.js";
import { visibleRange } from "./virtual.js";

/** One file as `files.read` answers it. */
export interface TextFile {
  kind: "text";
  path: string;
  content: string;
  total_lines: number;
  language: string;
  size: number;
  truncated?: boolean;
}

export interface ImageFile {
  kind: "image";
  path: string;
  mime: string;
  data: string;
  size: number;
  width: number;
  height: number;
  display_width: number;
  display_height: number;
  downscaled: boolean;
}

export interface BinaryFile {
  kind: "binary";
  path: string;
  size: number;
  reason: string;
}

export type ViewerFile = TextFile | ImageFile | BinaryFile;

interface Props {
  path: string;
  file: ViewerFile | null;
  loading: boolean;
  error: string | null;
  /** The user's switch. The turn lock can force read-only on top of it. */
  readOnly: boolean;
  /** A turn is running: read-only whatever the switch says. */
  locked: boolean;
  onToggleReadOnly: (readOnly: boolean) => void;
  saving: boolean;
  onSave: (content: string) => void;
  /** Throw the buffer away and go back to what is on disk. */
  onDiscard: () => void;
  /** Whether the buffer differs from what is on disk. */
  onDirtyChange: (dirty: boolean) => void;
  palette: string;
  onPalette: (name: string) => void;
  onClose: () => void;
}

/** The row height the CSS uses; the virtualiser needs the same number. */
export const CODE_ROW_HEIGHT = 20;

/** Languages whose text has a rendered view as well as a source view. */
const PREVIEWABLE = new Set(["markdown", "csv"]);

/** The header's path, split so the file name can carry the emphasis. */
function splitPath(path: string): [string, string] {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? ["", path] : [path.slice(0, cut + 1), path.slice(cut + 1)];
}

/** A byte count a person can read. */
function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One line's tokens, with the gaps between them rendered as plain text. */
function Line({ text, tokens, theme }: { text: string; tokens: Token[]; theme: Palette }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  tokens.forEach((token, index) => {
    if (token.start > cursor) {
      parts.push(<span key={`p${index}`}>{text.slice(cursor, token.start)}</span>);
    }
    parts.push(
      <span key={`t${index}`} style={{ color: colorFor(theme, token.kind) }}>
        {text.slice(token.start, token.end)}
      </span>,
    );
    cursor = token.end;
  });
  if (cursor < text.length) parts.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{parts.length ? parts : text}</>;
}

/** A delimited file, as a grid. */
function Table({ text, path }: { text: string; path: string }) {
  const rows = useMemo(() => parseTable(text, delimiterFor(path)), [text, path]);
  if (rows.length === 0) return <div className="code-notice">Nothing to show.</div>;
  const [head, ...body] = rows;
  return (
    <div className="code-table-wrap">
      <table className="code-table">
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th key={index}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length >= MAX_TABLE_ROWS && (
        <p className="code-hint">Showing the first {MAX_TABLE_ROWS.toLocaleString()} rows.</p>
      )}
    </div>
  );
}

/** The scrolling body shared by every text view. */
function TextBody({
  text,
  language,
  theme,
  editable,
  onEdit,
  onSave,
  draft,
}: {
  text: string;
  language: string;
  theme: Palette;
  editable: boolean;
  onEdit: (next: string) => void;
  onSave: () => void;
  draft: string | null;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  // Highlighting is the expensive part, so it runs once per *text*, not per
  // scroll or per render: scrolling re-renders the window, and re-tokenising
  // a 5,000-line file sixty times a second is the difference between a viewer
  // and a space heater.
  const lines = useMemo(() => text.split("\n"), [text]);
  const tokens = useMemo(() => tokenize(text, language), [text, language]);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const measure = () => setViewportHeight(element.clientHeight);
    measure();
    // Absent in jsdom and in older webviews, so its absence is handled rather
    // than assumed: the fallback is a screenful, which is what the
    // virtualiser does with a zero height.
    const Observer = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    if (!Observer) return;
    const observer = new Observer(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);

  const range = visibleRange(lines.length, scrollTop, viewportHeight, CODE_ROW_HEIGHT);
  const totalHeight = lines.length * CODE_ROW_HEIGHT;

  return (
    <div
      className={editable ? "code-body code-body-editing" : "code-body"}
      ref={viewportRef}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      // The palette's own surface, not the window's: code in Dark+ is
      // #1e1e1e on #d4d4d4, and drawing those colours on this app's #202020
      // would make the one thing the theme exists for -- the code -- the one
      // thing that did not change. The selection colour comes with it, so a
      // highlight belongs to the theme rather than to the window.
      style={
        {
          background: theme.background,
          color: theme.foreground,
          "--code-selection": theme.highlight,
        } as React.CSSProperties
      }
      role={editable ? undefined : "textbox"}
      aria-readonly={editable ? undefined : "true"}
      aria-multiline={editable ? undefined : "true"}
      tabIndex={editable ? undefined : 0}
    >
      <div className="code-canvas" style={{ height: totalHeight }}>
        <div
          className="code-lines"
          style={{ paddingTop: range.paddingTop, paddingBottom: range.paddingBottom }}
        >
          {lines.slice(range.start, range.end).map((line, offset) => {
            const number = range.start + offset;
            return (
              <div className="code-line" key={number}>
                <span className="code-gutter" style={{ color: theme.gutter }} aria-hidden="true">
                  {number + 1}
                </span>
                <span className="code-text">
                  <Line text={line} tokens={tokens[number] ?? []} theme={theme} />
                  {line === "" ? " " : ""}
                </span>
              </div>
            );
          })}
        </div>

        {editable && (
          <textarea
            className="code-input"
            value={draft ?? text}
            // `caret-color` is the one thing that cannot be transparent: the
            // text is painted by the layer underneath, and a caret that
            // inherited that transparency would be invisible.
            style={{ caretColor: theme.foreground }}
            onChange={(event) => onEdit(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "s" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                onSave();
              }
            }}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            wrap="off"
            aria-label={`${"Editing"} ${"file"}`}
          />
        )}
      </div>
    </div>
  );
}

export function CodeViewer({
  path,
  file,
  loading,
  error,
  readOnly,
  locked,
  onToggleReadOnly,
  saving,
  onSave,
  onDiscard,
  onDirtyChange,
  palette,
  onPalette,
  onClose,
}: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const [view, setView] = useState<"source" | "preview">("source");
  const theme = paletteFor(palette);
  const [directory, filename] = splitPath(path);

  const text = file?.kind === "text" ? file.content : "";
  const language = file?.kind === "text" ? file.language : "plain";
  const editable = Boolean(file && file.kind === "text" && !readOnly && !locked && !file.truncated);
  const dirty = Boolean(file && file.kind === "text" && draft !== null && draft !== file.content);
  const previewable = file?.kind === "text" && PREVIEWABLE.has(file.language);

  // A new file, or a save that came back with new content, starts clean. The
  // dependency is the *content* rather than the path: saving a file the user
  // is still looking at has to clear the dirty state, and the path has not
  // changed.
  const loaded = file?.kind === "text" ? file.content : null;
  useEffect(() => {
    setDraft(null);
    setView("source");
  }, [path, loaded]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  const body = () => {
    if (error) {
      return (
        <div className="code-notice code-notice-error" role="alert">
          {error}
        </div>
      );
    }
    if (loading) return <div className="code-notice">Reading {path}…</div>;
    if (!file) return <div className="code-notice">Nothing to show.</div>;

    if (file.kind === "image") {
      return (
        <div className="code-image" style={{ background: theme.background }}>
          <img
            src={`data:${file.mime};base64,${file.data}`}
            alt={file.path}
            style={{ maxWidth: "100%", maxHeight: "100%" }}
          />
        </div>
      );
    }

    if (file.kind === "binary") {
      return (
        <div className="code-notice">
          <p>{file.reason}</p>
          <p className="code-hint">
            {readableSize(file.size)} · there is no preview for this kind of file in the window.
          </p>
        </div>
      );
    }

    if (file.truncated) {
      return (
        <div className="code-notice">
          This file is larger than the viewer's limit, so only the beginning is shown. Editing is
          off for a partial read: saving it would write back less than the file holds.
        </div>
      );
    }

    if (previewable && view === "preview") {
      return (
        <div className="code-preview">
          {file.language === "markdown" ? (
            <MarkdownText text={text} />
          ) : (
            <Table text={text} path={file.path} />
          )}
        </div>
      );
    }

    if (text === "") return <div className="code-notice">This file is empty.</div>;

    return (
      <TextBody
        text={text}
        language={language}
        theme={theme}
        editable={editable}
        draft={draft}
        onEdit={setDraft}
        onSave={() => onSave(draft ?? text)}
      />
    );
  };

  const footer = () => {
    if (!file) return "";
    const bits = [readableSize(file.size)];
    if (file.kind === "text") {
      bits.unshift(`${file.total_lines.toLocaleString()} lines`);
      bits.push(file.language);
    }
    if (file.kind === "image") {
      const size =
        `${file.width}×${file.height}` +
        (file.downscaled ? ` (shown at ${file.display_width}×${file.display_height})` : "");
      bits.push(size);
    }
    if (dirty) bits.push("unsaved changes");
    return bits.join(" · ");
  };

  return (
    <section
      className="code-viewer"
      aria-label={`${path}, ${editable ? "editable" : "read only"}`}
      data-locked={locked}
      data-editable={editable}
    >
      <header className="code-header">
        <span className="code-path" title={path}>
          {directory && <span className="code-path-dir">{directory}</span>}
          <span className="code-path-name">{filename}</span>
          {dirty && <span className="code-dirty" title="Unsaved changes">•</span>}
        </span>

        {/*
          The language, named rather than derived from the extension.

          `code-chip-lang` is not decoration: it is the first thing a narrow
          pane gives up (see the container query in `code-viewer.css`), because
          it is the one chip on this bar that says something the header already
          says another way -- `FileSidebar.tsx` is TypeScript, and the footer
          repeats it -- while the path and the read-only state do not.
        */}
        {file?.kind === "text" && (
          <span className="code-chip code-chip-lang">{file.language}</span>
        )}
        {file?.kind === "image" && <span className="code-chip code-chip-lang">image</span>}
        {file?.kind === "binary" && (
          <span className="code-chip code-chip-lang">no preview</span>
        )}
        {file?.kind === "text" && file.truncated && (
          <span className="code-chip code-chip-warn">truncated</span>
        )}

        {previewable && (
          <span className="code-viewswitch">
            <button
              type="button"
              className={view === "source" ? "is-active" : undefined}
              aria-pressed={view === "source"}
              onClick={() => setView("source")}
            >
              Source
            </button>
            <button
              type="button"
              className={view === "preview" ? "is-active" : undefined}
              aria-pressed={view === "preview"}
              onClick={() => setView("preview")}
            >
              {file?.kind === "text" && file.language === "csv" ? "Table" : "Preview"}
            </button>
          </span>
        )}

        {/*
          The lock: a glyph and a word, in two elements.

          The word is what a narrow pane drops (see the container query in
          `code-viewer.css`) -- not the glyph: a padlock still says read-only at
          13px, and the `title` carries the sentence either way, so trimming it
          to its icon loses none of the meaning this chip exists for.
        */}
        <span
          className={locked ? "code-chip code-lock locked" : "code-chip code-lock"}
          title={
            locked
              ? "The agent is working. Editing is off until the turn finishes."
              : readOnly
                ? "Read-only. Turn the lock off to edit this file."
                : "Editable. Changes are saved by you, and the agent is told what changed."
          }
        >
          {/*
            The space between them is in the markup and not only in the CSS
            `gap`, so the chip *reads* as `🔒 read-only` to anything that reads
            the DOM -- a screen reader, and the test that pins this chip's
            text. A whitespace-only text node is not a flex item, so it costs
            the layout nothing.
          */}
          <span className="code-lock-icon">{locked || readOnly ? "🔒" : "🔓"}</span>{" "}
          <span className="code-lock-word">
            {locked ? "agent working" : readOnly ? "read-only" : "editable"}
          </span>
        </span>

        <span className="code-spacer" />

        <button
          type="button"
          className="btn btn-quiet code-toggle"
          onClick={() => onToggleReadOnly(!readOnly)}
          disabled={locked}
          aria-pressed={!readOnly}
          title={
            locked
              ? "The agent is working, so this file is read-only until it stops"
              : readOnly
                ? "Allow editing this file"
                : "Make this file read-only again"
          }
        >
          {readOnly ? "Edit" : "Lock"}
        </button>

        {editable && (
          <>
            <button
              type="button"
              className="btn btn-quiet code-toggle"
              onClick={() => onSave(draft ?? text)}
              disabled={!dirty || saving}
              title={dirty ? "Save (Ctrl+S)" : "No changes to save"}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            {/*
              Discard is a real button rather than an undo stack, because the
              buffer is the only copy of what the user typed: without a way to
              throw it away, a change they regret blocks every other file until
              they save it.
            */}
            {dirty && (
              <button
                type="button"
                className="btn btn-quiet code-toggle"
                onClick={onDiscard}
                title="Throw away these changes and reload the file"
              >
                Discard
              </button>
            )}
          </>
        )}

        {/*
          The theme, in the app's own menu rather than a native `<select>`.

          The select was the one control in the window the platform drew: its
          popup, its focus ring, its `Dark+ (default dark)` in the OS's listbox
          colours, none of which this app can style -- so the viewer shipped a
          control that looked like a different application, next to buttons that
          did not. `ListPicker` is the menu the composer's model chip and the
          settings panel already use; `labelFor` is what lets it show the
          palette's name while carrying its id.
        */}
        <span className="code-theme">
          <ListPicker
            label="Colour theme"
            value={palette}
            options={PALETTES.map((option) => option.name)}
            labelFor={(name) => paletteFor(name).label}
            triggerLabelFor={(name) => paletteFor(name).short}
            placeholder="Theme"
            disabled={false}
            onChange={onPalette}
          />
        </span>

        <button
          type="button"
          className="code-close"
          onClick={onClose}
          // Closing throws the buffer away, and the buffer is the only copy of
          // what the user typed. Save or discard first: a disabled control with
          // a reason is better than a click that silently loses work.
          disabled={dirty}
          title={dirty ? "Save or discard your changes first" : "Close the viewer"}
          aria-label="Close viewer"
        >
          ×
        </button>
      </header>

      {body()}

      <footer className="code-footer">{footer()}</footer>
    </section>
  );
}
