/**
 * A small, dependency-free Markdown parser for assistant text.
 *
 * Why not a library: this module has to be verifiable in the same plain-Node
 * harness as the protocol (`node --test`), with no build toolchain and no
 * network install. It also has to be *safe by construction*. The obvious
 * shortcut -- a renderer that produces an HTML string and hands it to
 * `dangerouslySetInnerHTML` -- turns every model completion into an XSS
 * surface, because assistant text is untrusted output from a remote model.
 * Parsing to a token tree and letting React build the elements means all text
 * is escaped by React and there is no raw-HTML path to get wrong.
 *
 * It deliberately implements a *subset* of CommonMark: the constructs a coding
 * agent actually emits (fenced code, headings, lists, blockquotes, rules, and
 * inline code/emphasis/links). A partial CommonMark implementation is honest
 * here; a "complete" one is a project of its own and the failure mode of a
 * missing feature is plain text, which is what rendered before this existed.
 *
 * GFM tables are the one extension beyond that subset, because model output
 * is full of them (option matrices, API shapes, plan steps) and a table as
 * a paragraph of pipes is the unreadable case. Nothing else from GFM is
 * here: no task lists, no autolinks, no strikethrough beyond the `~~` the
 * inline parser already knew.
 *
 * The parser is pure. It never throws on malformed input and treats a partial
 * stream (an unterminated code fence while tokens are still arriving) as valid
 * input whose fence simply runs to the end.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "strike"; children: Inline[] }
  /** `href` is empty when the URL scheme is not allowed; render as plain text. */
  | { kind: "link"; href: string; children: Inline[] }
  | { kind: "break" };

export type Block =
  | { kind: "heading"; level: number; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "code"; lang: string; text: string }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "table"; align: TableAlign[]; head: Inline[][]; rows: Inline[][][] }
  | { kind: "hr" };

/** One column's alignment, from its delimiter cell's colons. */
export type TableAlign = "left" | "center" | "right";

// --- block-level patterns --------------------------------------------------

const FENCE_RE = /^\s*(`{3,}|~{3,})(.*)$/;
const HEADING_RE = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR_RE = /^\s{0,3}([-*_])\s*(?:\1\s*){2,}$/;
const QUOTE_RE = /^\s{0,3}>\s?(.*)$/;
const UL_RE = /^\s*[-*+]\s+(.*)$/;
const OL_RE = /^\s*\d+[.)]\s+(.*)$/;

/** True when a line would start a non-paragraph block, so a paragraph ends. */
function startsBlock(line: string): boolean {
  return (
    FENCE_RE.test(line) ||
    HEADING_RE.test(line) ||
    HR_RE.test(line) ||
    QUOTE_RE.test(line) ||
    UL_RE.test(line) ||
    OL_RE.test(line)
  );
}

/**
 * Split a table row on its pipes.
 *
 * A backslash-escaped pipe is literal cell text, not a boundary -- without
 * this, a cell holding `a\\|b` would split the row in two. The empty fringes
 * a leading or trailing pipe leaves are dropped, so `| a | b |` is two cells
 * and so is `a | b`; each cell is trimmed, because the spaces around pipes
 * are padding rather than content.
 */
function splitCells(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === "\\" && line[i + 1] === "|") {
      current += "|";
      i++;
      continue;
    }
    if (ch === "|") {
      cells.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  cells.push(current);
  if (cells.length > 0 && cells[0].trim() === "") cells.shift();
  if (cells.length > 0 && cells[cells.length - 1].trim() === "") cells.pop();
  return cells.map((cell) => cell.trim());
}

/**
 * A delimiter row's per-column alignment, or null when it is not one.
 *
 * A delimiter cell is dashes with optional alignment colons (`---`, `:--`,
 * `--:`, `:-:`). Anything else -- prose, a second header -- is not a table,
 * which is what keeps `a | b` lines as paragraphs: without a delimiter row
 * directly beneath, pipes are just text.
 */
function parseDelimiter(line: string): TableAlign[] | null {
  const cells = splitCells(line);
  if (cells.length === 0) return null;
  const aligns: TableAlign[] = [];
  for (const cell of cells) {
    const m = /^(:?)-+(:?)$/.exec(cell);
    if (!m) return null;
    aligns.push(m[1] && m[2] ? "center" : m[2] ? "right" : "left");
  }
  return aligns;
}

interface TableMatch {
  align: TableAlign[];
  head: Inline[][];
  rows: Inline[][][];
  /** The first line after the table. */
  next: number;
}

/**
 * A GFM table starting at `lines[i]`, or null when there is none.
 *
 * Three conditions, each doing a job: the next line parses as a delimiter
 * row (so `a | b` prose never becomes a table), the header holds the same
 * number of cells (a ragged pair is two paragraphs, not a table with a
 * hole), and at least one of the two lines carries a pipe (so `foo` over
 * `---` stays the paragraph-and-rule it always was, rather than a
 * one-column table nobody wrote).
 */
function matchTable(lines: string[], i: number): TableMatch | null {
  const delimiter = lines[i + 1];
  if (delimiter === undefined) return null;
  const aligns = parseDelimiter(delimiter);
  if (!aligns) return null;
  const head = splitCells(lines[i]);
  if (head.length !== aligns.length) return null;
  if (!lines[i].includes("|") && !delimiter.includes("|")) return null;

  const rows: Inline[][][] = [];
  let next = i + 2;
  while (next < lines.length) {
    const line = lines[next];
    // A blank line ends the table; so does anything another block owns. A
    // body row without a pipe ends it too -- it is prose under the table,
    // and swallowing it would merge two blocks into one grid.
    if (line.trim() === "" || startsBlock(line) || !line.includes("|")) break;
    const cells = splitCells(line);
    while (cells.length < aligns.length) cells.push("");
    rows.push(cells.slice(0, aligns.length).map((cell) => parseInline(cell)));
    next++;
  }

  return {
    align: aligns,
    head: head.map((cell) => parseInline(cell)),
    rows,
    next,
  };
}

// --- inline-level parsing --------------------------------------------------

const ESCAPABLE = /[\\`*_[\]()#+\-.!>~|]/;

/**
 * Allow only schemes that cannot execute script.
 *
 * `javascript:` and `data:` URLs are the whole reason this exists. A rejected
 * URL is not dropped -- the link text is kept and rendered without an href, so
 * a model that emits a bad URL degrades to readable text rather than a dead or
 * dangerous link.
 */
function sanitizeHref(raw: string): string {
  const url = raw.trim();
  if (/^(https?:|mailto:)/i.test(url)) return url;
  return "";
}

interface InlineMatch {
  node: Inline;
  length: number;
}

function matchCode(text: string, i: number): InlineMatch | null {
  if (text[i] !== "`") return null;
  const run = /^`+/.exec(text.slice(i))![0];
  const end = text.indexOf(run, i + run.length);
  if (end === -1) return null;
  return {
    node: { kind: "code", text: text.slice(i + run.length, end).trim() },
    length: end + run.length - i,
  };
}

/**
 * `![alt](url)` renders as the alt text only.
 *
 * A remote image in model output is a tracking beacon: loading it tells
 * whoever controls the URL that the turn happened, and from where. There is no
 * reason for a local coding agent to fetch one.
 */
function matchImage(text: string, i: number): InlineMatch | null {
  if (!text.startsWith("![", i)) return null;
  const m = /^!\[([^\]]*)\]\(([^()\s]*)\)/.exec(text.slice(i));
  if (!m) return null;
  return { node: { kind: "text", text: m[1] || "(image)" }, length: m[0].length };
}

function matchLink(text: string, i: number): InlineMatch | null {
  if (text[i] !== "[") return null;
  const m = /^\[([^\]]*)\]\(([^()\s]*)(?:\s+"[^"]*")?\)/.exec(text.slice(i));
  if (!m) return null;
  return {
    node: { kind: "link", href: sanitizeHref(m[2]), children: parseInline(m[1]) },
    length: m[0].length,
  };
}

function matchDelimited(
  text: string,
  i: number,
  marker: string,
  kind: "strong" | "strike",
): InlineMatch | null {
  if (!text.startsWith(marker, i)) return null;
  const start = i + marker.length;
  const end = text.indexOf(marker, start);
  if (end === -1 || end === start) return null;
  return {
    node: { kind, children: parseInline(text.slice(start, end)) },
    length: end + marker.length - i,
  };
}

function matchEm(text: string, i: number): InlineMatch | null {
  const ch = text[i];
  if (ch !== "*" && ch !== "_") return null;
  // Leave `**`/`__` to the strong matcher.
  if (text[i + 1] === ch) return null;
  // An intraword underscore (`snake_case`) is not emphasis. `*` has no such
  // rule, which is why it is the safer marker to reach for.
  if (ch === "_" && /[A-Za-z0-9]/.test(text[i - 1] ?? "")) return null;
  const end = text.indexOf(ch, i + 1);
  if (end === -1 || end === i + 1) return null;
  if (text[end + 1] === ch) return null;
  if (/\s/.test(text[end - 1] ?? "")) return null;
  return {
    node: { kind: "em", children: parseInline(text.slice(i + 1, end)) },
    length: end + 1 - i,
  };
}

function matchEscaped(text: string, i: number): InlineMatch | null {
  if (text[i] !== "\\") return null;
  const next = text[i + 1];
  if (next !== undefined && ESCAPABLE.test(next)) {
    return { node: { kind: "text", text: next }, length: 2 };
  }
  return null;
}

function matchBreak(text: string, i: number): InlineMatch | null {
  if (text[i] !== "\n") return null;
  return { node: { kind: "break" }, length: 1 };
}

/** Parse the inline content of one block: emphasis, code, links, breaks. */
export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let buffer = "";
  let i = 0;
  const flush = () => {
    if (buffer) {
      out.push({ kind: "text", text: buffer });
      buffer = "";
    }
  };

  while (i < text.length) {
    // Order matters. Image before link (both start with `[` after `!`), code
    // before anything that could appear inside it, strong before em so `**`
    // is not read as two `*`s.
    const match =
      matchImage(text, i) ??
      matchCode(text, i) ??
      matchLink(text, i) ??
      matchDelimited(text, i, "**", "strong") ??
      matchDelimited(text, i, "__", "strong") ??
      matchDelimited(text, i, "~~", "strike") ??
      matchEscaped(text, i) ??
      matchEm(text, i) ??
      matchBreak(text, i);

    if (match) {
      flush();
      out.push(match.node);
      i += match.length;
      continue;
    }
    buffer += text[i];
    i += 1;
  }
  flush();
  return out;
}

// --- block-level parsing ---------------------------------------------------

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const fence = FENCE_RE.exec(line);
    if (fence) {
      const marker = fence[1][0];
      const lang = fence[2].trim();
      const closer = new RegExp("^\\s*" + marker + "{3,}\\s*$");
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !closer.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      // Consume the closing fence if there is one. When the stream is still
      // arriving there is not, and the code block simply runs to the end.
      if (i < lines.length) i += 1;
      blocks.push({ kind: "code", lang, text: code.join("\n") });
      continue;
    }

    const heading = HEADING_RE.exec(line);
    if (heading) {
      blocks.push({
        kind: "heading",
        level: heading[1].length,
        children: parseInline(heading[2]),
      });
      i += 1;
      continue;
    }

    if (HR_RE.test(line)) {
      blocks.push({ kind: "hr" });
      i += 1;
      continue;
    }

    if (QUOTE_RE.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length) {
        const m = QUOTE_RE.exec(lines[i]);
        if (!m) break;
        quoteLines.push(m[1]);
        i += 1;
      }
      blocks.push({ kind: "quote", blocks: parseBlocks(quoteLines) });
      continue;
    }

    const ordered = OL_RE.test(line) && !UL_RE.test(line);
    if (UL_RE.test(line) || OL_RE.test(line)) {
      const items: Inline[][] = [];
      while (i < lines.length) {
        const m = ordered ? OL_RE.exec(lines[i]) : UL_RE.exec(lines[i]);
        if (!m) break;
        items.push(parseInline(m[1]));
        i += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    const table = matchTable(lines, i);
    if (table) {
      blocks.push({ kind: "table", align: table.align, head: table.head, rows: table.rows });
      i = table.next;
      continue;
    }

    // Paragraph: consecutive plain lines until a blank or another block start.
    // A table header is not in `startsBlock` (it needs its delimiter to say
    // what it is), so the loop also stops where a table starts -- otherwise
    // the header line would be swallowed as prose before the table is seen.
    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !startsBlock(lines[i]) &&
      !matchTable(lines, i)
    ) {
      paragraph.push(lines[i]);
      i += 1;
    }
    // A single newline inside a paragraph is a hard break here, not the
    // CommonMark soft break. Model output uses one newline between steps, and
    // collapsing those to a space reads worse in a chat transcript than
    // honouring them.
    blocks.push({ kind: "paragraph", children: parseInline(paragraph.join("\n")) });
  }

  return blocks;
}

/** Parse a Markdown document into a renderable block tree. */
export function parseMarkdown(source: string): Block[] {
  const normalized = source.replace(/\r\n?/g, "\n");
  return parseBlocks(normalized.split("\n"));
}
