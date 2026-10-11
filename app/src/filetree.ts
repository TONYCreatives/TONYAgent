/**
 * The project tree, as rows the sidebar can draw.
 *
 * The core hands back a *flat* list of paths (`files.tree`), because that is
 * what a walk produces and because a nested payload would be the same
 * information with more places to be wrong. Turning it into indented rows --
 * depth, parents, collapse, filter, and the agent's per-file change badges --
 * is pure arithmetic over that list, so it lives here and is verified without
 * React, exactly like the markdown parser and the highlighter.
 *
 * **Collapse is by directory, and a collapsed directory hides its whole
 * subtree.** That is not just the visible row: a file three levels under a
 * collapsed folder must not be reachable by a filter either, or the filter
 * would surface rows the tree is hiding and the two would disagree about
 * what is open.
 */

/** One entry as `files.tree` reports it. */
export interface CoreTreeEntry {
  path: string;
  kind: "dir" | "file";
  size?: number;
}

/** What the agent changed in a file, summed over the session. */
export interface FileChange {
  added: number;
  removed: number;
}

/** One row the pane draws. */
export interface TreeRow {
  path: string;
  /** The last segment, which is what the row shows. */
  name: string;
  kind: "dir" | "file";
  depth: number;
  /** Directories only: whether this row's children are currently shown. */
  open: boolean;
  /** Files only, and only when the agent changed them. */
  added?: number;
  removed?: number;
}

/** The final segment of a project-relative path. */
export function nameOf(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? path : path.slice(cut + 1);
}

/** How deeply nested a path is; a root-level entry is depth 0. */
export function depthOf(path: string): number {
  let depth = 0;
  for (const character of path) if (character === "/") depth += 1;
  return depth;
}

/** Every ancestor directory of a path, nearest last. */
export function ancestorsOf(path: string): string[] {
  const parts = path.split("/");
  const out: string[] = [];
  for (let index = 1; index < parts.length; index += 1) {
    out.push(parts.slice(0, index).join("/"));
  }
  return out;
}

/**
 * The rows to draw, in order.
 *
 * `collapsed` holds the paths of directories whose children are hidden;
 * `filter` is a case-insensitive substring over the full path. A filter
 * keeps every ancestor of a match so the match is reachable rather than
 * floating at an indentation that implies a parent it does not show.
 */
export function buildTree(
  entries: CoreTreeEntry[],
  changes: Map<string, FileChange>,
  collapsed: ReadonlySet<string>,
  filter = "",
): TreeRow[] {
  const needle = filter.trim().toLowerCase();
  const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path));

  let visible = sorted;
  if (needle) {
    const keep = new Set<string>();
    for (const entry of sorted) {
      if (entry.path.toLowerCase().includes(needle)) {
        keep.add(entry.path);
        for (const ancestor of ancestorsOf(entry.path)) keep.add(ancestor);
      }
    }
    visible = sorted.filter((entry) => keep.has(entry.path));
  }

  // A collapsed directory hides its subtree -- unless a filter is on, where
  // hiding a match under a folder the user is not looking at would make the
  // search report nothing for a file that is there.
  if (!needle) {
    visible = visible.filter((entry) => {
      const ancestors = ancestorsOf(entry.path);
      return !ancestors.some((ancestor) => collapsed.has(ancestor));
    });
  }

  return visible.map((entry) => {
    const change = entry.kind === "file" ? changes.get(entry.path) : undefined;
    return {
      path: entry.path,
      name: nameOf(entry.path),
      kind: entry.kind,
      depth: depthOf(entry.path),
      open: entry.kind === "dir" ? !collapsed.has(entry.path) : false,
      ...(change && change.added > 0 ? { added: change.added } : {}),
      ...(change && change.removed > 0 ? { removed: change.removed } : {}),
    };
  });
}

/** Sum the changes the core reported into a path -> badge map. */
export function changesFrom(
  artifacts: Array<{ path?: string; added?: number; removed?: number }>,
): Map<string, FileChange> {
  const out = new Map<string, FileChange>();
  for (const artifact of artifacts) {
    if (!artifact.path) continue;
    const previous = out.get(artifact.path);
    out.set(artifact.path, {
      added: (previous?.added ?? 0) + (artifact.added ?? 0),
      removed: (previous?.removed ?? 0) + (artifact.removed ?? 0),
    });
  }
  return out;
}
