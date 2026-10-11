/**
 * What a hand edit changed, as line ranges.
 *
 * **Why this exists at all.** When the user edits a file in the viewer, the
 * agent's picture of that file goes stale silently -- and its next answer
 * would be about code that no longer exists in the form it remembers. So the
 * edit is reported with the next message, and this is what computes the
 * report: which lines in the file *as it now stands* differ from what the
 * agent last had.
 *
 * **Line numbers are in the new file**, deliberately. The agent will read
 * the file again; a number that pointed into the old text would send it to
 * the wrong line, which is worse than no number.
 *
 * **Not a general diff, and it says so.** Common prefix and suffix are
 * trimmed first -- which is what makes an edit in a 5,000-line file cost
 * nothing -- and what remains is matched greedily by identical lines. That
 * is exact for the shapes a person typing produces (insert, delete, change a
 * line, change a block) and approximate for a total rewrite, where it
 * reports the rewritten region as changed. An approximation that admits it
 * is worth more here than an exact algorithm nobody can read: the report is
 * prose for a model, not a patch.
 */

/** One changed region, 1-based and inclusive, in the new file. */
export interface LineRange {
  start: number;
  end: number;
}

export interface LineDiff {
  added: number;
  removed: number;
  ranges: LineRange[];
}

/** The trivial answer, used for the no-change and empty cases. */
const NONE: LineDiff = { added: 0, removed: 0, ranges: [] };

/**
 * The line-level difference between two texts.
 *
 * `start` and `end` are equal for a *deletion*: nothing is at that line any
 * more, and the line that now occupies the position is what moved up. That
 * is the honest answer to "which line was modified" when the modification
 * was removing one.
 */
export function diffLines(before: string, after: string): LineDiff {
  if (before === after) return { ...NONE, ranges: [] };

  const oldLines = before.split("\n");
  const newLines = after.split("\n");

  let prefix = 0;
  while (
    prefix < oldLines.length &&
    prefix < newLines.length &&
    oldLines[prefix] === newLines[prefix]
  ) {
    prefix += 1;
  }

  let suffix = 0;
  while (
    suffix < oldLines.length - prefix &&
    suffix < newLines.length - prefix &&
    oldLines[oldLines.length - 1 - suffix] === newLines[newLines.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const oldMiddle = oldLines.slice(prefix, oldLines.length - suffix);
  const newMiddle = newLines.slice(prefix, newLines.length - suffix);

  // Greedy alignment of the middle: each old line claims the earliest
  // still-unclaimed identical new line after the previous claim. Linear in
  // the size of the changed region, which is the region the trim left.
  const positions = new Map<string, number[]>();
  newMiddle.forEach((line, index) => {
    const bucket = positions.get(line);
    if (bucket) bucket.push(index);
    else positions.set(line, [index]);
  });

  const claimedNew = new Set<number>();
  const claimedOld = new Set<number>();
  let cursor = 0;
  oldMiddle.forEach((line, index) => {
    const bucket = positions.get(line);
    if (!bucket) return;
    const at = bucket.find((candidate) => candidate >= cursor && !claimedNew.has(candidate));
    if (at === undefined) return;
    claimedNew.add(at);
    claimedOld.add(index);
    cursor = at + 1;
  });

  const removed = oldMiddle.length - claimedOld.size;
  const added = newMiddle.length - claimedNew.size;
  const ranges: LineRange[] = [];

  // Runs of added lines, as ranges in the new file.
  let runStart: number | null = null;
  newMiddle.forEach((_line, index) => {
    if (!claimedNew.has(index)) {
      if (runStart === null) runStart = index;
      return;
    }
    if (runStart !== null) {
      ranges.push({ start: prefix + runStart + 1, end: prefix + index });
      runStart = null;
    }
  });
  if (runStart !== null) {
    ranges.push({ start: prefix + runStart + 1, end: prefix + newMiddle.length });
  }

  // A deletion has no line of its own to point at, so it is reported where
  // the text used to be: the line that closed the gap, clamped into the file
  // that is left.
  if (removed > 0 && added === 0) {
    const at = Math.min(Math.max(prefix + 1, 1), Math.max(newLines.length, 1));
    ranges.push({ start: at, end: at });
  }

  return { added, removed, ranges };
}

/**
 * The report form the core's `send` takes, built from one file's edit.
 *
 * The counts come from the core's own save (`files.write` reports them, from
 * the same line-diff the agent's tools use) so the badge and the report
 * cannot disagree about how much changed; the *ranges* are this module's,
 * because only the window knows what the user's keystrokes did.
 */
export function editReport(path: string, diff: LineDiff, added: number, removed: number) {
  return {
    path,
    added,
    removed,
    lines: diff.ranges,
  };
}
