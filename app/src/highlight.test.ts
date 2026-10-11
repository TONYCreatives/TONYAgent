/**
 * Tests for the code highlighter and its palettes.
 *
 * Two families of assertion, and the split is deliberate. The *shape* tests
 * are invariants that must hold for every language and every input --
 * one token list per line, tokens in order, no overlap, nothing past the end
 * of its line -- because the viewer renders them positionally and a scanner
 * that violates one would paint text in the wrong place rather than throw.
 * The *colour* tests pin what a specific construct is classified as, which is
 * the part a reader would notice immediately if it drifted.
 *
 * Runs in the plain-Node harness, like the markdown parser's tests and for
 * the same reason: the highlighter is a pure function over text, so it is
 * verified without React, Vite or a window.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_PALETTE,
  PALETTES,
  colorFor,
  paletteFor,
  tokenize,
  type Token,
  type TokenKind,
} from "./highlight.js";

/** The kinds on one line, in order, with the text they cover. */
function spans(text: string, language: string, line = 0): Array<[TokenKind, string]> {
  const source = text.split("\n")[line];
  return tokenize(text, language)[line].map((token) => [
    token.kind,
    source.slice(token.start, token.end),
  ]);
}

/** The kind of the token covering the first character of `needle`, or null. */
function kindOf(text: string, language: string, needle: string, line = 0): TokenKind | null {
  const source = text.split("\n")[line];
  const at = source.indexOf(needle);
  assert.notEqual(at, -1, `${needle} is not on line ${line}`);
  const found = tokenize(text, language)[line].find(
    (token) => token.start <= at && token.end > at,
  );
  return found ? found.kind : null;
}

/** Every invariant the renderer depends on, for one document. */
function assertWellFormed(text: string, language: string): void {
  const lines = text.split("\n");
  const tokens = tokenize(text, language);
  assert.equal(tokens.length, lines.length, `${language}: one list per line`);
  tokens.forEach((row, index) => {
    let cursor = 0;
    for (const token of row as Token[]) {
      assert.ok(
        token.start >= cursor,
        `${language} line ${index}: token overlaps its predecessor`,
      );
      assert.ok(token.end > token.start, `${language} line ${index}: empty token`);
      assert.ok(
        token.end <= lines[index].length,
        `${language} line ${index}: token runs past the line (${token.end} > ${lines[index].length})`,
      );
      cursor = token.end;
    }
  });
}

//: A document per language, written to look like the real thing.
const CORPUS: Array<[string, string]> = [
  [
    "typescript",
    [
      "// a comment",
      'import { readFile } from "node:fs/promises";',
      "",
      "export class Loader {",
      "  private readonly root: string = '/tmp';",
      "  async load(name: string): Promise<number> {",
      "    const count = 42;",
      "    if (count > 0 && name !== '') {",
      "      return count;",
      "    }",
      "    return 0;",
      "  }",
      "}",
      "/* a block",
      "   comment */",
      "const pattern = /ab+c/;",
    ].join("\n"),
  ],
  [
    "python",
    [
      "import os",
      "",
      "class Widget:",
      '    """A docstring.',
      "",
      "    Still inside it.",
      '    """',
      "",
      "    def render(self, scale=1.0):",
      "        # a comment",
      "        total = scale * 3",
      "        if total > 0 and self.visible:",
      "            return True",
      "        return None",
    ].join("\n"),
  ],
  ["json", '{\n  "name": "tonyagent",\n  "count": 12,\n  "ok": true,\n  "none": null\n}'],
  ["css", ".card {\n  color: #ff0000;\n  margin: 4px;\n}\n@media screen {\n  a { color: blue; }\n}"],
  ["html", '<div class="row" id=main>\n  <!-- note -->\n  <span>&amp;</span>\n</div>'],
  ["markdown", "# Title\n\nSome **bold** and `code`.\n\n- item\n> quote\n\n[link](https://example.com)"],
  ["shell", "#!/bin/sh\n# comment\nexport PATH=\"$PATH:/opt\"\nif [ -f x ]; then\n  echo 'done'\nfi"],
  ["yaml", "name: agent\nlist:\n  - one\n  - two\ntrue_key: true"],
  ["toml", "[tools]\nname = \"tonyagent\"\ncount = 3"],
  ["rust", "pub fn main() -> i32 {\n    let x = 1;\n    x\n}"],
  ["go", "package main\n\nfunc main() {\n\tprintln(\"hi\")\n}"],
  ["sql", "SELECT id, name FROM users WHERE age > 18 -- note"],
  ["plain", "nothing to highlight here"],
];

test("every language tokenizes to well-formed per-line spans", () => {
  for (const [language, text] of CORPUS) {
    assertWellFormed(text, language);
  }
});

test("an unknown language renders as plain text", () => {
  const text = "some { text } with // things";
  const tokens = tokenize(text, "brainfuck");
  assert.deepEqual(tokens, [[]], "an unknown language must highlight nothing");
  assertWellFormed(text, "brainfuck");
});

test("an empty document has one empty line", () => {
  assert.deepEqual(tokenize("", "typescript"), [[]]);
});

test("a trailing newline keeps the empty last line", () => {
  const tokens = tokenize("const a = 1;\n", "typescript");
  assert.equal(tokens.length, 2);
  assert.deepEqual(tokens[1], []);
});

// --- what gets which colour ---------------------------------------------------

test("typescript classifies declarations, control flow and literals", () => {
  const code = "export class Loader {\n  if (true) { return null; }\n  const x = 1;\n  foo();\n  Bar();\n}";
  assert.equal(kindOf(code, "typescript", "class"), "declaration");
  // `export`/`import` are control keywords in Dark+ (purple), not storage
  // declarations (blue) -- which is the distinction the two kinds carry.
  assert.equal(kindOf(code, "typescript", "export"), "keyword");
  assert.equal(kindOf(code, "typescript", "if", 1), "keyword");
  assert.equal(kindOf(code, "typescript", "return", 1), "keyword");
  assert.equal(kindOf(code, "typescript", "true", 1), "literal");
  assert.equal(kindOf(code, "typescript", "null", 1), "literal");
  assert.equal(kindOf(code, "typescript", "1", 2), "number");
  // A lowercase call is a function, a capitalised one is a type.
  assert.equal(kindOf(code, "typescript", "foo", 3), "function");
  assert.equal(kindOf(code, "typescript", "Bar", 4), "type");
});

test("typescript strings and comments are what they are", () => {
  const code = 'const s = "text"; // trailing\nconst t = `a ${x} b`;\n/* block */';
  assert.equal(kindOf(code, "typescript", '"text"'), "string");
  assert.equal(kindOf(code, "typescript", "// trailing"), "comment");
  assert.equal(kindOf(code, "typescript", "`a ${x} b`", 1), "template");
  assert.equal(kindOf(code, "typescript", "/* block */", 2), "comment");
});

test("a block comment is split across the lines it covers", () => {
  const code = "/* one\n   two\n   three */\nconst after = 1;";
  for (const line of [0, 1, 2]) {
    const row = spans(code, "typescript", line);
    assert.ok(
      row.some(([kind]) => kind === "comment"),
      `line ${line} of a block comment was not highlighted`,
    );
  }
  // And the line after it is code again, not still a comment.
  assert.equal(kindOf(code, "typescript", "const", 3), "declaration");
  assertWellFormed(code, "typescript");
});

test("a template literal spanning lines is still a template", () => {
  const code = "const s = `first\nsecond`;\nconst after = 1;";
  assert.ok(spans(code, "typescript", 1).some(([kind]) => kind === "template"));
  assert.equal(kindOf(code, "typescript", "const", 2), "declaration");
  assertWellFormed(code, "typescript");
});

test("python classifies def, class, comments and docstrings", () => {
  const code = 'class Widget:\n    """Doc."""\n    def render(self):\n        # note\n        return True';
  assert.equal(kindOf(code, "python", "class"), "declaration");
  assert.equal(kindOf(code, "python", "def", 2), "declaration");
  assert.equal(kindOf(code, "python", '"""Doc."""', 1), "string");
  assert.equal(kindOf(code, "python", "# note", 3), "comment");
  assert.equal(kindOf(code, "python", "return", 4), "keyword");
  assert.equal(kindOf(code, "python", "True", 4), "literal");
  assert.equal(kindOf(code, "python", "self", 2), "literal");
});

test("a python docstring spanning lines stays a string", () => {
  const code = 'def f():\n    """one\n\n    two\n    """\n    return 1';
  // The blank line inside the docstring carries no token, because there is
  // nothing on it to paint -- the invariant is that the *text* lines are
  // still strings and the code after the closing quotes is not.
  assert.ok(spans(code, "python", 1).some(([kind]) => kind === "string"));
  assert.ok(spans(code, "python", 3).some(([kind]) => kind === "string"));
  assert.deepEqual(spans(code, "python", 2), [], "an empty line has no tokens");
  assert.equal(kindOf(code, "python", "return", 5), "keyword");
  assertWellFormed(code, "python");
});

test("json colours keys differently from values", () => {
  const code = '{\n  "name": "tonyagent",\n  "ok": true\n}';
  assert.equal(kindOf(code, "json", '"name"', 1), "property");
  assert.equal(kindOf(code, "json", '"tonyagent"', 1), "string");
  assert.equal(kindOf(code, "json", "true", 2), "literal");
});

test("css separates properties, numbers and selectors", () => {
  const code = ".card {\n  color: #ff0000;\n  margin: 4px;\n}";
  assert.equal(kindOf(code, "css", ".card"), "type");
  assert.equal(kindOf(code, "css", "color", 1), "property");
  assert.equal(kindOf(code, "css", "#ff0000", 1), "number");
  assert.equal(kindOf(code, "css", "4px", 2), "number");
});

test("html colours tags, attributes and attribute values", () => {
  const code = '<div class="row">text</div>';
  assert.equal(kindOf(code, "html", "<div"), "tag");
  assert.equal(kindOf(code, "html", "class"), "attribute");
  assert.equal(kindOf(code, "html", '"row"'), "string");
});

test("markdown colours headings past the first line", () => {
  // The `m` flag on the line rules is what this catches: without it `^`
  // anchors to offset 0 and only the first heading is ever coloured.
  const code = "intro\n\n# Title\n\n## Deeper\n\n- item\n> quote";
  assert.equal(kindOf(code, "markdown", "# Title", 2), "heading");
  assert.equal(kindOf(code, "markdown", "## Deeper", 4), "heading");
  assert.equal(kindOf(code, "markdown", "- item", 6), "keyword");
  assert.equal(kindOf(code, "markdown", "> quote", 7), "comment");
});

test("markdown colours emphasis, code and links", () => {
  const code = "a **bold** word and `code` and [text](https://x.dev)";
  assert.equal(kindOf(code, "markdown", "**bold**"), "emphasis");
  assert.equal(kindOf(code, "markdown", "`code`"), "string");
  assert.equal(kindOf(code, "markdown", "[text](https://x.dev)"), "link");
});

test("yaml and toml colour keys and sections", () => {
  assert.equal(kindOf("name: agent\nother: 2", "yaml", "name"), "property");
  assert.equal(kindOf("[tools]\nname = \"x\"", "toml", "[tools]"), "type");
  assert.equal(kindOf("[tools]\nname = \"x\"", "toml", "name", 1), "property");
});

test("shell colours the shebang line and keywords", () => {
  const code = "#!/bin/sh\nexport PATH=\"$PATH:/opt\"\nif [ -f x ]; then\n  echo 'done'\nfi";
  assert.equal(kindOf(code, "shell", "#", 0), "comment");
  assert.equal(kindOf(code, "shell", "export", 1), "keyword");
  assert.equal(kindOf(code, "shell", '"$PATH:/opt"', 1), "template");
  assert.equal(kindOf(code, "shell", "'done'", 3), "string");
});

// --- palettes -----------------------------------------------------------------

test("the palettes are the editor's own, and named", () => {
  const names = PALETTES.map((p) => p.name);
  assert.deepEqual(names, ["dark-plus", "light-plus", "monokai"]);
  assert.equal(DEFAULT_PALETTE, "dark-plus");
});

test("dark plus is the theme this imitates", () => {
  const dark = paletteFor("dark-plus");
  assert.equal(dark.background, "#1e1e1e");
  assert.equal(dark.colors.keyword, "#c586c0");
  assert.equal(dark.colors.declaration, "#569cd6");
  assert.equal(dark.colors.string, "#ce9178");
  assert.equal(dark.colors.comment, "#6a9955");
  assert.equal(dark.colors.function, "#dcdcaa");
  assert.equal(dark.colors.type, "#4ec9b0");
});

test("an unknown palette name falls back rather than throwing", () => {
  assert.equal(paletteFor("solarized-nothing").name, "dark-plus");
  assert.equal(paletteFor("").name, "dark-plus");
});

test("every palette has a colour for every kind the scanner emits", () => {
  const kinds: TokenKind[] = [
    "comment", "string", "template", "number", "keyword", "declaration",
    "literal", "type", "function", "property", "tag", "attribute",
    "operator", "punctuation", "heading", "emphasis", "link", "regex",
  ];
  for (const palette of PALETTES) {
    const missing = kinds.filter((kind) => !palette.colors[kind]);
    assert.deepEqual(missing, [], `${palette.name} is missing colours`);
  }
});

test("a kind with no colour still gets one from the palette", () => {
  const palette = paletteFor("dark-plus");
  const sparse = { ...palette, colors: {} };
  assert.equal(colorFor(sparse, "keyword"), sparse.foreground);
  assert.equal(colorFor(palette, "keyword"), "#c586c0");
});
