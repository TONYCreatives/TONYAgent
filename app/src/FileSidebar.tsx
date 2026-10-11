/**
 * The Files pane of the left sidebar.
 *
 * It was a right-hand overlay: its own surface, its own scrim, its own header
 * and a reopen handle for when it was closed. It is a *pane* now -- one of the
 * two the sidebar switches between -- so there is one surface to open, one
 * header above it and nowhere to reopen from: the segmented control that
 * reveals it is also what puts it away. See `.chatlist-tabs` and `.files-pane`.
 *
 * The tree is fed by the parent rather than read from disk. The core already
 * owns the sandbox and the folder, so letting the UI walk the filesystem would
 * be a second source of truth about state the core controls.
 */

import { useMemo, useState } from "react";

export interface TreeEntry {
  /** Path relative to the project root, or the folder name for a directory. */
  name: string;
  kind: "dir" | "file";
  depth: number;
  /** Lines added/removed, when the core reports them. */
  added?: number;
  removed?: number;
}

interface Props {
  entries: TreeEntry[];
  filter: string;
  onFilterChange: (value: string) => void;
  onChooseFolder: () => void;
  /** True once a folder is selected, so the empty state can say which. */
  hasProject: boolean;
}

function Caret({ open }: { open: boolean }) {
  return <span className="tree-caret">{open ? "▾" : "▸"}</span>;
}

function Glyph({ kind }: { kind: "dir" | "file" }) {
  if (kind === "dir") {
    return (
      <svg
        className="tree-icon"
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      </svg>
    );
  }
  return (
    <svg
      className="tree-icon"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export function FilesPane({
  entries,
  filter,
  onFilterChange,
  onChooseFolder,
  hasProject,
}: Props) {
  // Folders open by default; the depth is capped at 1 because the core has no
  // method for enumerating a subtree yet, and inventing a fake tree would be
  // worse than showing a flat list.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(needle));
  }, [entries, filter]);

  return (
    <div className="files-pane" aria-label="Files">

      <label className="sidebar-filter">
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3" />
        </svg>
        <input
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          placeholder="Filter files"
          spellCheck={false}
        />
      </label>

      {visible.length === 0 ? (
        entries.length === 0 ? (
          // The pick button lives here, not only in settings: an empty panel
          // that merely explains itself is the dead end this replaces.
          <div className="sidebar-empty">
            <p>
              {hasProject
                ? "No files touched yet. Files the agent reads or writes show up here."
                : "No folder selected."}
            </p>
            {!hasProject && (
              <button
                type="button"
                className="btn"
                onClick={onChooseFolder}
              >
                Choose folder...
              </button>
            )}
          </div>
        ) : (
          <p className="sidebar-empty">Nothing matches that filter.</p>
        )
      ) : (
        <div className="sidebar-tree">
          {visible.map((entry) => {
            const key = `${entry.kind}:${entry.name}`;
            const isCollapsed = collapsed.has(key);
            return (
              <div
                key={key}
                className="tree-row"
                style={{ paddingLeft: 8 + entry.depth * 14 }}
                onClick={() => {
                  if (entry.kind !== "dir") return;
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  });
                }}
              >
                {entry.kind === "dir" ? (
                  <Caret open={!isCollapsed} />
                ) : (
                  <span className="tree-caret" />
                )}
                <Glyph kind={entry.kind} />
                <span className="tree-name">{entry.name}</span>
                {/*
                  A zero/zero badge is the *absence* of a change, and showing
                  "+0 -0" next to a file would claim it was edited. The counts
                  come from a real line diff in the core, so silence genuinely
                  means the write was a no-op.
                */}
                {entry.added !== undefined && entry.added > 0 && (
                  <span className="tree-add" title={`${entry.added} lines added`}>
                    +{entry.added}
                  </span>
                )}
                {entry.removed !== undefined && entry.removed > 0 && (
                  <span className="tree-del" title={`${entry.removed} lines removed`}>
                    -{entry.removed}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
