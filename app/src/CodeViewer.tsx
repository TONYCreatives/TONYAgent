/**
 * The code viewer: a VSCode-shaped surface for reading project files.
 *
 * **It is a viewer, and the read-only-ness is the design rather than a
 * restriction bolted on.** There is no textarea, no `contenteditable`, no
 * save path and no dirty state anywhere in this file -- the agent's own
 * `write` tool is confirmation-gated, and a UI write path would be a second,
 * quieter door into the project that no gate watches. What the user *can* do
 * is what a reader needs: select, scroll, copy a file, and change the theme.
 *
 * **The lock is the one piece of state the window adds.** While a turn is
 * running the viewer says so -- a chip in the header and `aria-readonly` on
 * the body -- so a long generation is never raced by a half-scrolled read
 * with no indication that the file is being rewritten underneath it. The
 * surfaces that *do* change state (the palette, the scroll position) stay
 * available: they are properties of this window, not of the file.
 *
 * Reads are the parent's job. This component is handed the text, the
 * language and the failures as props, which is what keeps it renderable in
 * jsdom with no backend at all -- the same seam `App` uses for the core.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { colorFor, paletteFor, PALETTES, tokenize, type Palette, type Token } from "./highlight.js";
import { visibleRange } from "./virtual.js";

/** One file as `files.read` answers it. */
export interface SourceFile {
  path: string;
  content: string;
  total_lines: number;
  language: string;
  truncated?: boolean;
}

interface Props {
  /** Project-relative path, shown in the header and used for the language. */
  path: string;
  source: SourceFile | null;
  loading: boolean;
  error: string | null;
  /**
   * True while the agent is working. The viewer is read-only either way;
   * this is the *visible* statement of it, and the reason the chip exists.
   */
  locked: boolean;
  palette: string;
  onPalette: (name: string) => void;
  onClose: () => void;
}

/** The row height the CSS uses; the virtualiser needs the same number. */
export const CODE_ROW_HEIGHT = 20;

/** The header's path, split so the file name can carry the emphasis. */
function splitPath(path: string): [string, string] {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? ["", path] : [path.slice(0, cut + 1), path.slice(cut + 1)];
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

export function CodeViewer({
  path,
  source,
  loading,
  error,
  locked,
  palette,
  onPalette,
  onClose,
}: Props) {
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  // Highlighting is the expensive part, so it runs once per file *content*,
  // not per scroll or per render -- scrolling re-renders the window, and
  // re-tokenising a 5,000-line file 60 times a second is the difference
  // between a viewer and a space heater.
  const lines = useMemo(
    () => (source ? source.content.split("\n") : []),
    [source],
  );
  const tokens = useMemo(
    () => (source ? tokenize(source.content, source.language) : []),
    [source],
  );

  // Measure the viewport once it exists, and again when the window resizes.
  // `ResizeObserver` is absent in jsdom and in older webviews, so its absence
  // is handled rather than assumed -- the fallback is a screenful.
  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const measure = () => setViewportHeight(element.clientHeight);
    measure();
    const Observer = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    if (!Observer) return;
    const observer = new Observer(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [path]);

  const range = visibleRange(lines.length, scrollTop, viewportHeight, CODE_ROW_HEIGHT);
  const [directory, filename] = splitPath(path);
  // Resolved once per render rather than per line: `paletteFor` searches the
  // list, and a 5,000-line file would otherwise search it 5,000 times a frame.
  const theme = paletteFor(palette);

  const copy = () => {
    // Absent in jsdom and in a webview without the permission; the button is
    // a convenience, so a refusal is not an error the user has to clear.
    const clipboard = (globalThis as { navigator?: { clipboard?: { writeText?: (text: string) => Promise<void> } } })
      .navigator?.clipboard;
    if (source && clipboard?.writeText) void clipboard.writeText(source.content);
  };

  return (
    <section className="code-viewer" aria-label={`${path}, read only`} data-locked={locked}>
      <header className="code-header">
        <span className="code-path" title={path}>
          {directory && <span className="code-path-dir">{directory}</span>}
          <span className="code-path-name">{filename}</span>
        </span>

        {source && <span className="code-chip">{source.language}</span>}
        {source?.truncated && <span className="code-chip code-chip-warn">truncated</span>}

        <span
          className={locked ? "code-chip code-lock locked" : "code-chip code-lock"}
          title={
            locked
              ? "The agent is working. This viewer is read-only, and stays read-only."
              : "This viewer is read-only: files are changed by the agent, which asks first."
          }
        >
          {locked ? "🔒 read-only · agent working" : "🔒 read-only"}
        </span>

        <span className="code-spacer" />

        <label className="code-theme">
          <select
            value={palette}
            onChange={(event) => onPalette(event.target.value)}
            aria-label="Colour theme"
            title="Colour theme"
          >
            {PALETTES.map((option) => (
              <option key={option.name} value={option.name}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button type="button" className="btn btn-quiet" onClick={copy} disabled={!source}>
          Copy
        </button>
        <button type="button" className="code-close" onClick={onClose} aria-label="Close viewer">
          ×
        </button>
      </header>

      {error ? (
        <div className="code-notice code-notice-error" role="alert">
          {error}
        </div>
      ) : loading ? (
        <div className="code-notice">Reading {path}…</div>
      ) : !source ? (
        <div className="code-notice">Nothing to show.</div>
      ) : lines.length === 1 && lines[0] === "" ? (
        <div className="code-notice">This file is empty.</div>
      ) : (
        <div
          className="code-body"
          ref={viewportRef}
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
          // The palette's own surface, not the window's: a code area in
          // VSCode's Dark+ is #1e1e1e with #d4d4d4 text, and drawing those
          // colours on this app's #202020 would make the one thing the theme
          // exists for -- the code -- the one thing that did not change.
          style={{ background: theme.background, color: theme.foreground }}
          // Read-only at the accessibility layer too, so a screen reader
          // announces what the chip says rather than leaving it to the eye.
          role="textbox"
          aria-readonly="true"
          aria-multiline="true"
          tabIndex={0}
        >
          <div style={{ height: range.paddingTop }} />
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
          <div style={{ height: range.paddingBottom }} />
        </div>
      )}

      <footer className="code-footer">
        {source
          ? `${source.total_lines.toLocaleString()} lines · ${(
              new TextEncoder().encode(source.content).length / 1024
            ).toFixed(1)} KB · ${source.language}`
          : ""}
      </footer>
    </section>
  );
}
