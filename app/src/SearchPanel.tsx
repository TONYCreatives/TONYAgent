/**
 * Project search.
 *
 * A modal over the core's `search` method, which delegates to the same
 * GrepTool the agent itself uses. That delegation is the point: the files a
 * user can search and the files the model can search are the same set, under
 * the same skip rules and the same path confinement. A frontend that filtered
 * the transcript, or walked the filesystem itself, would answer a different
 * question from the one the agent answers.
 *
 * The rail's search button was disabled precisely because there was nothing
 * real behind it. This is the real thing.
 */

import { useEffect, useRef, useState } from "react";
import { Overlay } from "./Overlay.js";

/** One hit, mirroring the `grep_result` artifact the core returns. */
export interface SearchMatch {
  file: string;
  line: number;
  content: string;
  context?: string;
}

interface Props {
  connected: boolean;
  /** False until a project folder is chosen; grep is confined to it. */
  hasProject: boolean;
  onClose: () => void;
  onSearch: (pattern: string) => Promise<SearchMatch[]>;
}

/**
 * Render a context block, marking the line the pattern actually hit.
 *
 * The core's `_extract_context` prefixes the matching line with ">" and the
 * rest with a space, because a plain text block cannot carry markup. Turning
 * that back into a real element is what makes a nine-line context block
 * scannable instead of nine undifferentiated lines.
 *
 * The leading space is stripped from every line so the <pre> does not indent
 * the whole block, and the marker is dropped rather than shown.
 */
function splitContext(context: string) {
  return context.split("\n").map((line, i) => {
    const isMatch = line.startsWith(">");
    return (
      <span key={i} className={isMatch ? "search-hit-line-on" : undefined}>
        {(isMatch ? line.slice(1) : line).replace(/^ /, "")}
        {"\n"}
      </span>
    );
  });
}

export function SearchPanel({ connected, hasProject, onClose, onSearch }: Props) {
  const [pattern, setPattern] = useState("");
  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus on open so the field is usable immediately: this panel exists to be
  // typed into, and a modal that opens with nothing focused costs a click.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // A result set from a previous pattern must not linger while a new one runs,
  // or the user reads stale hits as the answer to what they just typed.
  const run = async () => {
    if (!pattern.trim()) return;
    setRunning(true);
    setError(null);
    setMatches(null);
    try {
      setMatches(await onSearch(pattern));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Overlay open onDismiss={onClose}>
      <div
        className="modal search-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="search-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="search-title">Search project</h2>

        <div className="settings-row">
          <input
            ref={inputRef}
            className="settings-input"
            type="text"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void run();
            }}
            placeholder="Regular expression"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={!connected || !hasProject}
            aria-label="Search pattern"
          />
          <button
            type="button"
            className="btn btn-accent"
            onClick={() => void run()}
            disabled={!connected || !hasProject || running || !pattern.trim()}
          >
            {running ? "Searching..." : "Search"}
          </button>
        </div>

        {!hasProject ? (
          <p className="settings-hint">
            Choose a project folder first. Search is confined to it, exactly as
            the agent's own file tools are.
          </p>
        ) : (
          <p className="settings-hint">
            Same search the agent runs: skips build output and dependencies, and
            never leaves the project folder.
          </p>
        )}

        {error && <p className="warn">{error}</p>}

        {matches !== null && (
          <div className="search-results">
            <div className="search-count">
              {matches.length === 0
                ? "No matches"
                : `${matches.length} match${matches.length === 1 ? "" : "es"}`}
            </div>
            <div className="search-list">
              {matches.map((m, i) => (
                // The line number is part of the identity: the same file can
                // match twice, and an index key would collide only sometimes,
                // which is worse than never.
                <div className="search-hit" key={`${m.file}:${m.line}:${i}`}>
                  <div className="search-hit-head">
                    <span className="search-hit-file">{m.file}</span>
                    <span className="search-hit-line">:{m.line}</span>
                  </div>
                  <pre className="search-hit-body">
                    {m.context ? splitContext(m.context) : m.content}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Overlay>
  );
}
