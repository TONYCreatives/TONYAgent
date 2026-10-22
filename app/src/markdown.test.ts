/**
 * Tests for the Markdown parser.
 *
 * The parser is the only thing standing between untrusted model output and the
 * DOM, so the cases that matter most are the ones where a mistake would be a
 * *security* consequence rather than a cosmetic one: a `javascript:` link, a
 * remote image that would phone home, and the guarantee that no path builds
 * raw HTML. Those are pinned below alongside the ordinary structure tests.
 *
 * These run in the same plain-Node harness as the protocol tests, with no
 * React and no build toolchain -- that is why the parser is a separate module
 * from the component that renders its output.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseMarkdown, parseInline, type Block, type Inline } from "./markdown.js";

/** Flatten a token tree to the text a reader would see. */
function textOf(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      switch (n.kind) {
        case "text":
          return n.text;
        case "code":
          return n.text;
        case "break":
          return "\n";
        default:
          return textOf(n.children);
      }
    })
    .join("");
}

function paragraphText(blocks: Block[], index = 0): string {
  const block = blocks[index];
  assert.equal(block.kind, "paragraph");
  return textOf(block.children);
}

/** The inline children of a block that has them, narrowed via a local. */
function childrenOf(blocks: Block[], index = 0): Inline[] {
  const block = blocks[index];
  if (block.kind === "heading" || block.kind === "paragraph") return block.children;
  assert.fail(`block ${index} has no inline children (got ${block.kind})`);
}

test("a plain line is a paragraph of text", () => {
  const blocks = parseMarkdown("hello world");
  assert.equal(blocks.length, 1);
  assert.equal(paragraphText(blocks), "hello world");
});

test("headings carry their level and inline content", () => {
  const blocks = parseMarkdown("# One\n\n### Three **bold**");
  assert.deepEqual(
    blocks.map((b) => (b.kind === "heading" ? b.level : null)),
    [1, 3],
  );
  const three = blocks[1];
  assert.equal(three.kind, "heading");
  assert.equal(textOf(three.children), "Three bold");
});

test("a fenced block keeps its language and body verbatim", () => {
  const blocks = parseMarkdown('```python\nprint("hi")\n*not emphasis*\n```');
  assert.equal(blocks.length, 1);
  const code = blocks[0];
  assert.equal(code.kind, "code");
  assert.equal(code.lang, "python");
  // The body is not re-parsed: emphasis markers inside code stay literal.
  assert.equal(code.text, 'print("hi")\n*not emphasis*');
});

test("an unterminated fence runs to the end instead of failing", () => {
  // This is the streaming case: tokens arrive before the closing fence does.
  const blocks = parseMarkdown("```js\nconst x = 1;");
  assert.equal(blocks[0].kind, "code");
  assert.equal(blocks[0].lang, "js");
  assert.equal(blocks[0].text, "const x = 1;");
});

test("unordered and ordered lists are distinguished", () => {
  const ul = parseMarkdown("- one\n- two");
  assert.equal(ul[0].kind, "list");
  assert.equal(ul[0].ordered, false);
  assert.equal(ul[0].items.length, 2);

  const ol = parseMarkdown("1. first\n2. second");
  assert.equal(ol[0].kind, "list");
  assert.equal(ol[0].ordered, true);
  assert.equal(textOf(ol[0].items[1]), "second");
});

test("a blockquote contains its own nested blocks", () => {
  const blocks = parseMarkdown("> intro\n> - a\n> - b");
  assert.equal(blocks[0].kind, "quote");
  const inner = blocks[0].blocks;
  assert.equal(inner.length, 2);
  assert.equal(inner[0].kind, "paragraph");
  assert.equal(inner[1].kind, "list");
});

test("a horizontal rule is its own block", () => {
  assert.equal(parseMarkdown("above\n\n---\n\nbelow")[1].kind, "hr");
});

test("inline code and emphasis nest without swallowing each other", () => {
  const inline = parseInline("use `npm test` then **stop**");
  assert.deepEqual(
    inline.map((n) => n.kind),
    ["text", "code", "text", "strong"],
  );
  assert.equal(inline[1].kind === "code" && inline[1].text, "npm test");
});

test("a single newline inside a paragraph becomes a line break", () => {
  const blocks = parseMarkdown("step one\nstep two");
  assert.deepEqual(
    childrenOf(blocks).map((n) => n.kind),
    ["text", "break", "text"],
  );
});

test("an intraword underscore is not emphasis", () => {
  // `snake_case` is the single most common false positive this would hit.
  const blocks = parseMarkdown("call snake_case_name here");
  assert.deepEqual(
    childrenOf(blocks).map((n) => n.kind),
    ["text"],
  );
  assert.equal(paragraphText(blocks), "call snake_case_name here");
});

test("an escaped marker is literal text", () => {
  const nodes = parseInline("\\*not emphasis\\*");
  assert.equal(textOf(nodes), "*not emphasis*");
  assert.equal(nodes.some((n) => n.kind === "em"), false);
});

test("only safe URL schemes produce a link; javascript: degrades to text", () => {
  const ok = parseInline("[docs](https://example.com/a)");
  assert.equal(ok[0].kind, "link");
  assert.equal(ok[0].href, "https://example.com/a");

  // The decisive case. A rejected scheme keeps the text but drops the href, so
  // there is no anchor for a click to follow.
  const bad = parseInline("[click](javascript:alert)");
  assert.equal(bad[0].kind, "link");
  assert.equal(bad[0].href, "");
  assert.equal(textOf(bad[0].children), "click");
});

test("a remote image renders as its alt text and loads nothing", () => {
  const nodes = parseInline("![beacon](https://tracker.example/pixel.png)");
  assert.deepEqual(nodes, [{ kind: "text", text: "beacon" }]);
});

test("unmatched markers fall back to literal text and never throw", () => {
  for (const input of ["**unclosed", "`code", "[text](", "> not a quote start", "~~~"]) {
    assert.doesNotThrow(() => parseMarkdown(input));
  }
  assert.equal(textOf(parseInline("**unclosed")), "**unclosed");
});

test("carriage returns are normalised so Windows output parses the same", () => {
  assert.deepEqual(parseMarkdown("a\r\nb"), parseMarkdown("a\nb"));
});

test("parsing is pure: the same input yields the same tree twice", () => {
  const source = "# Title\n\n- a\n- b\n\n> quote";
  assert.deepEqual(parseMarkdown(source), parseMarkdown(source));
});

// --- GFM tables ---------------------------------------------------------------
/*
 * The one GFM extension the parser knows, because model output is full of
 * tables and a table as a paragraph of pipes is the unreadable case. Each
 * test below pins one half of the contract: real tables parse, and
 * almost-tables -- prose with pipes, a setext-shaped pair, a ragged header --
 * stay exactly what they were before tables existed.
 */
function tableAt(blocks: Block[], index = 0) {
  const block = blocks[index];
  assert.equal(block.kind, "table");
  return block;
}

test("a header, a delimiter and rows parse as a table", () => {
  const blocks = parseMarkdown("| name | count |\n| ---- | ----- |\n| widget | 3 |\n| gadget | **5** |");
  assert.equal(blocks.length, 1);
  const table = tableAt(blocks);
  assert.deepEqual(table.align, ["left", "left"]);
  assert.equal(textOf(table.head[0]), "name");
  assert.equal(table.rows.length, 2);
  assert.equal(textOf(table.rows[1][1]), "5");
});

test("leading and trailing pipes are optional padding", () => {
  const blocks = parseMarkdown("name | count\n--- | ---\nwidget | 3");
  assert.equal(blocks.length, 1);
  const table = tableAt(blocks);
  assert.equal(textOf(table.head[1]), "count");
  assert.equal(textOf(table.rows[0][0]), "widget");
});

test("delimiter colons align the column", () => {
  const blocks = parseMarkdown("| a | b | c |\n| :-- | :-: | --: |\n| 1 | 2 | 3 |");
  assert.deepEqual(tableAt(blocks).align, ["left", "center", "right"]);
});

test("pipes without a delimiter row stay a paragraph", () => {
  // The common case: prose mentioning `a | b` must not become a table.
  const blocks = parseMarkdown("use a | b for this\n\nnext");
  assert.equal(blocks[0].kind, "paragraph");
  assert.match(paragraphText(blocks), /a \| b/);
});

test("a word over dashes stays a paragraph and a rule, not a table", () => {
  // Setext-shaped, and single-column tables need a pipe somewhere: without
  // that rule this pair would turn into a one-column table nobody wrote.
  const blocks = parseMarkdown("foo\n---");
  assert.equal(blocks[0].kind, "paragraph");
  assert.equal(blocks[1].kind, "hr");
});

test("a header wider than its delimiter is not a table", () => {
  const blocks = parseMarkdown("| a | b |\n| --- |\n| 1 | 2 |");
  assert.equal(blocks[0].kind, "paragraph");
});

test("an escaped pipe is cell text, not a boundary", () => {
  const blocks = parseMarkdown("| a |\n| --- |\n| x \\| y |");
  assert.equal(textOf(tableAt(blocks).rows[0][0]), "x | y");
});

test("short rows pad and long rows truncate to the header", () => {
  const blocks = parseMarkdown("| a | b |\n| --- | --- |\n| 1 |\n| 2 | 3 | 4 |");
  const table = tableAt(blocks);
  assert.equal(table.rows[0].length, 2);
  assert.equal(textOf(table.rows[0][1]), "");
  assert.equal(table.rows[1].length, 2);
  assert.equal(textOf(table.rows[1][1]), "3");
});

test("a table ends at a blank line and prose follows it", () => {
  const blocks = parseMarkdown("| a |\n| --- |\n| 1 |\n\nafter");
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].kind, "table");
  assert.equal(blocks[1].kind, "paragraph");
});

test("a table never throws on ragged input", () => {
  for (const input of ["|\n| ---", "| a |\n|", "| a |\n| --- |\n|", "|||"]) {
    assert.doesNotThrow(() => parseMarkdown(input));
  }
});
