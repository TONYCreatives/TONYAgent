/**
 * Right-hand Files panel.
 *
 * An overlay rather than a third column. Docked, an empty panel held 425px --
 * a third of a 1200px window -- open indefinitely to report that the agent had
 * not touched anything yet, permanently narrowing the transcript. It now floats
 * over it behind a scrim, so it is obviously temporary and clicking away
 * dismisses it.
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
  onToggle: () => void;
  onChooseFolder: () => void;
  /** True once a folder is selected, so the empty state can say which. */
  hasProject: boolean;
  open: boolean;
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

export function FileSidebar({
  entries,
  filter,
  onFilterChange,
  onToggle,
  onChooseFolder,
  hasProject,
  open,
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

  if (!open) {
    return (
      <button
        type="button"
        className="sidebar-reopen"
        onClick={onToggle}
        title="Show files"
        aria-label="Show files"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
      </button>
    );
  }

  return (
    <>
      {/* Dismisses on any click outside the panel, which is the affordance the
          docked version could not offer: there was nothing to dismiss *to*. */}
      <button
        type="button"
        className="sidebar-scrim"
        onClick={onToggle}
        tabIndex={-1}
        aria-label="Close files"
      />
      <aside className="sidebar" aria-label="Files">
      <div className="sidebar-head">
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
        <span className="sidebar-title">Files</span>
        <div className="topbar-spacer" />
        <button
          type="button"
          className="icon-btn"
          onClick={onToggle}
          title="Hide files"
          aria-label="Hide files"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M9 7V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v2" />
            <path d="M4 7h16v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
          </svg>
        </button>
      </div>

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
      </aside>
    </>
  );
}
