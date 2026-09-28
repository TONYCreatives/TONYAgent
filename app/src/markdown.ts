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
  | { kind: "hr" };

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

    // Paragraph: consecutive plain lines until a blank or another block start.
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !startsBlock(lines[i])) {
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
