/**
 * The files this run touched, with what it did to each.
 *
 * Read from the core's `file_change` artifact rather than from the summary
 * sentence -- the same rule `ToolCall.path` documents. The counts are summed
 * per path by `turnActivity`, so a file edited in three passes is one row with
 * the change the file actually has, not three rows that each overstate their
 * part.
 *
 * Five rows and a remainder. The panel has height for five at the minimum
 * window, and a list long enough to scroll the files past the plan is a list
 * that has stopped being a glance.
 *
 * A row is a button because it goes somewhere: pressing one opens Code at that
 * file. That is the difference between this section and the plan's, where the
 * rows are text unless a call to scroll to exists.
 */

import type { TouchedFile } from "./activity.js";

const LIMIT = 5;

interface Props {
  files: TouchedFile[];
  onOpen: (path: string) => void;
}

/** The file's own name, so the row leads with the part a reader recognises. */
function fileName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** The directory in front of the name, with its trailing separator, or "". */
function folderOf(path: string): string {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut >= 0 ? path.slice(0, cut + 1) : "";
}

export function FilesTouched({ files, onOpen }: Props) {
  if (files.length === 0) {
    return <p className="context-empty">No files touched yet.</p>;
  }

  const visible = files.slice(0, LIMIT);
  const hidden = files.length - visible.length;

  return (
    <div className="files-touched">
      <ul className="file-rows" aria-label="Files changed in this turn">
        {visible.map((file) => (
          <li key={file.path}>
            <button
              type="button"
              className="file-row"
              onClick={() => onOpen(file.path)}
              title={`Open ${file.path} in Code`}
            >
              <span className="file-path">
                {/*
                  One element, with the directory as its own run: the name is
                  what the row is for, and the directory is context that gives
                  way first when the path is long -- see the stylesheet. Keeping
                  the path in one element also keeps the row's gap between the
                  counts and the path, not between two halves of a path.
                */}
                <span className="file-dir">{folderOf(file.path)}</span>
                <span className="file-name">{fileName(file.path)}</span>
              </span>
              <span className="file-counts">
                {file.added > 0 && (
                  <span className="file-added">+{file.added}</span>
                )}
                {file.removed > 0 && (
                  <span className="file-removed">−{file.removed}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {hidden > 0 && <p className="plan-more">+{hidden} more</p>}
    </div>
  );
}
