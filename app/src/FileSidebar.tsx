/**
 * The Files pane of the left sidebar: the project tree.
 *
 * It used to list only the files the agent had *touched*, built from tool
 * artifacts -- which meant a file nobody had opened yet could not be reached
 * at all, and the pane was a session log wearing a tree's clothes. The rows
 * now come from the core's own walk (`files.tree`), so this is the project,
 * with the agent's changes shown as the `+N`/`-N` badges they always were.
 *
 * The tree is fed by the parent rather than read from disk. The core already
 * owns the sandbox, the folder and the skip rules; letting the UI walk the
 * filesystem would be a second source of truth about all three, and the walk
 * would list files the agent's tools refuse to open.
 *
 * Nesting, collapse and filter are `buildTree`'s -- pure arithmetic over the
 * flat list the core sends, tested without a DOM. This file is the drawing.
 */

import { useMemo, useState } from "react";

import { buildTree, type CoreTreeEntry, type FileChange } from "./filetree.js";
import { Icon } from "./icons.js";

interface Props {
  entries: CoreTreeEntry[];
  /** Per-file change badges, summed from the agent's own artifacts. */
  changes: Map<string, FileChange>;
  filter: string;
  onFilterChange: (value: string) => void;
  onChooseFolder: () => void;
  /** True once a folder is selected, so the empty state can say which. */
  hasProject: boolean;
  /** Open a file in the viewer. */
  onOpenFile: (path: string) => void;
  /** The walk hit its own bound; said out loud rather than hidden. */
  truncated?: boolean;
  loading?: boolean;
}

function Caret({ open }: { open: boolean }) {
  return <span className="tree-caret">{open ? "▾" : "▸"}</span>;
}

function Glyph({ kind }: { kind: "dir" | "file" }) {
  if (kind === "dir") {
    return (
      <Icon name="folder" size={12} className="tree-icon" />
    );
  }
  return (
    <Icon name="file" size={12} className="tree-icon" />
  );
}

export function FilesPane({
  entries,
  changes,
  filter,
  onFilterChange,
  onChooseFolder,
  hasProject,
  onOpenFile,
  truncated = false,
  loading = false,
}: Props) {
  // Which directories are closed. Open by default: the tree the user just
  // asked for is the thing they want to see, not a list of collapsed folders.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const rows = useMemo(
    () => buildTree(entries, changes, collapsed, filter),
    [entries, changes, collapsed, filter],
  );

  const toggle = (path: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="files-pane" aria-label="Files">
      <label className="sidebar-filter">
        <Icon name="search" size={12} />
        <input
          value={filter}
          onChange={(event) => onFilterChange(event.target.value)}
          placeholder="Filter files"
          spellCheck={false}
        />
      </label>

      {rows.length === 0 ? (
        entries.length === 0 ? (
          // The pick button lives here, not only in settings: an empty panel
          // that merely explains itself is the dead end this replaces.
          <div className="sidebar-empty">
            <p>
              {loading
                ? "Reading the project…"
                : hasProject
                  ? "This folder has no files the viewer shows."
                  : "No folder selected."}
            </p>
            {!hasProject && !loading && (
              <button type="button" className="btn" onClick={onChooseFolder}>
                Choose folder...
              </button>
            )}
          </div>
        ) : (
          <p className="sidebar-empty">Nothing matches that filter.</p>
        )
      ) : (
        <div className="sidebar-tree">
          {rows.map((row) => (
            <div
              key={`${row.kind}:${row.path}`}
              className={row.kind === "file" ? "tree-row tree-row-file" : "tree-row"}
              style={{ paddingLeft: 8 + row.depth * 14 }}
              onClick={() => (row.kind === "dir" ? toggle(row.path) : onOpenFile(row.path))}
              // The rows are the tree's controls, so they are reachable and
              // operable from the keyboard rather than click-only.
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                if (row.kind === "dir") toggle(row.path);
                else onOpenFile(row.path);
              }}
              title={row.path}
            >
              {row.kind === "dir" ? <Caret open={row.open} /> : <span className="tree-caret" />}
              <Glyph kind={row.kind} />
              <span className="tree-name">{row.name}</span>
              {/*
                A zero/zero badge is the *absence* of a change, and showing
                "+0 -0" next to a file would claim it was edited. The counts
                come from a real line diff in the core, so silence genuinely
                means the write was a no-op.
              */}
              {row.added !== undefined && (
                <span className="tree-add" title={`${row.added} lines added`}>
                  +{row.added}
                </span>
              )}
              {row.removed !== undefined && (
                <span className="tree-del" title={`${row.removed} lines removed`}>
                  -{row.removed}
                </span>
              )}
            </div>
          ))}
          {truncated && (
            <p className="sidebar-empty">
              The project is larger than this list. The tree stops where the walk did.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
