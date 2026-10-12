/**
 * Syntax highlighting, and the palettes it draws with.
 *
 * **Why this is hand-written rather than a dependency.** The two obvious
 * candidates are both wrong for this window. Shiki is the real thing --
 * VSCode's own TextMate grammars -- and it is a WASM engine plus a grammar
 * and theme bundle per language, which is megabytes in a window whose entire
 * dependency list is React, and it cannot run in the jsdom test harness the
 * rest of this codebase's UI is verified in. Monaco is a whole editor, for a
 * surface that is deliberately a *viewer*. What is here instead is a
 * scanner: one pass per file, the languages this project actually contains,
 * and the VSCode palettes' own colours so it *looks* like the editor it is
 * imitating.
 *
 * **What it is not.** Not a parser, and not a correctness boundary. A
 * regex scanner cannot know that a `/*` is inside a string in some dialect
 * nobody uses here, or that a template literal interpolates. It highlights
 * the code in this repository and the languages around it, and a language it
 * does not know renders as plain text -- which is honest, where a wrong
 * highlight is quietly misleading.
 *
 * **The shapes are per line, not per file.** The viewer renders one row per
 * line with a gutter, so a token that spans lines (a block comment, a
 * template literal) is split at each newline and reported once per line.
 * That is also what keeps the render a plain `.map()` over lines rather than
 * a re-measure on scroll.
 */

/** What a run of characters *is*, for colouring. Kept coarse on purpose. */
export type TokenKind =
  | "comment"
  | "string"
  | "template"
  | "number"
  | "keyword" // control flow: if, return, for, while, import
  | "declaration" // const, function, class, def, fn, struct
  | "literal" // true, false, null, None, self
  | "type" // type names, class names, decorators
  | "function" // a call or definition name
  | "property" // an object key, a JSON key, a YAML key
  | "tag" // <div> in HTML/XML
  | "attribute" // an HTML/XML attribute name
  | "operator"
  | "punctuation"
  | "heading" // markdown #
  | "emphasis" // markdown **bold** / *italic*
  | "link" // markdown [text](url)
  | "regex";

/** One run of highlighted characters, as columns within its line. */
export interface Token {
  start: number;
  end: number;
  kind: TokenKind;
}

/**
 * A colour scheme, named the way VSCode names its own.
 *
 * `colors` is sparse: a kind with no entry renders in the palette's
 * foreground, which is what VSCode does for punctuation and plain text.
 */
export interface Palette {
  name: string;
  /** The theme's full name, the way the editor's own list writes it. */
  label: string;
  /**
   * What fits on a control.
   *
   * Two names for one theme because they are written in two places with
   * different room: the menu lists "Dark+ (default dark)", where the
   * parenthetical is the point, and the chip in a 38px header says "Dark+",
   * where it is 60px of a bar that is holding a path, two chips and three
   * buttons. VSCode does the same thing with the same theme.
   */
  short: string;
  /** Chrome colours, so the viewer's frame matches the code inside it. */
  background: string;
  foreground: string;
  gutter: string;
  gutterActive: string;
  border: string;
  /** The text cursor / match highlight, when something highlights a line. */
  highlight: string;
  colors: Partial<Record<TokenKind, string>>;
}

/**
 * VSCode's Dark+ -- the default theme of the editor this is imitating.
 *
 * The colours are the theme's own values, not approximations of them:
 * #569CD6 declarations, #C586C0 control flow, #CE9178 strings, #6A9955
 * comments, #DCDCAA functions, #4EC9B0 types, #9CDCFE properties and
 * variables, #B5CEA8 numbers.
 */
const DARK_PLUS: Palette = {
  name: "dark-plus",
  label: "Dark+ (default dark)",
  short: "Dark+",
  background: "#1e1e1e",
  foreground: "#d4d4d4",
  gutter: "#858585",
  gutterActive: "#c6c6c6",
  border: "#2b2b2b",
  highlight: "#264f78",
  colors: {
    comment: "#6a9955",
    string: "#ce9178",
    template: "#ce9178",
    number: "#b5cea8",
    keyword: "#c586c0",
    declaration: "#569cd6",
    literal: "#569cd6",
    type: "#4ec9b0",
    function: "#dcdcaa",
    property: "#9cdcfe",
    tag: "#569cd6",
    attribute: "#9cdcfe",
    operator: "#d4d4d4",
    punctuation: "#d4d4d4",
    heading: "#569cd6",
    emphasis: "#d7ba7d",
    link: "#4ec9b0",
    regex: "#d16969",
  },
};

/** VSCode's Light+ -- the same theme, inverted, for a bright room. */
const LIGHT_PLUS: Palette = {
  name: "light-plus",
  label: "Light+ (default light)",
  short: "Light+",
  background: "#ffffff",
  foreground: "#000000",
  gutter: "#237893",
  gutterActive: "#0b216f",
  border: "#e5e5e5",
  highlight: "#add6ff",
  colors: {
    comment: "#008000",
    string: "#a31515",
    template: "#a31515",
    number: "#098658",
    keyword: "#af00db",
    declaration: "#0000ff",
    literal: "#0000ff",
    type: "#267f99",
    function: "#795e26",
    property: "#001080",
    tag: "#800000",
    attribute: "#e50000",
    operator: "#000000",
    punctuation: "#000000",
    heading: "#0000ff",
    emphasis: "#795e26",
    link: "#267f99",
    regex: "#811f3f",
  },
};

/** Monokai, because it is the palette people ask for by name. */
const MONOKAI: Palette = {
  name: "monokai",
  label: "Monokai",
  short: "Monokai",
  background: "#272822",
  foreground: "#f8f8f2",
  gutter: "#90908a",
  gutterActive: "#c2c2bf",
  border: "#3b3b36",
  highlight: "#49483e",
  colors: {
    comment: "#88846f",
    string: "#e6db74",
    template: "#e6db74",
    number: "#ae81ff",
    keyword: "#f92672",
    declaration: "#66d9ef",
    literal: "#ae81ff",
    type: "#66d9ef",
    function: "#a6e22e",
    property: "#f8f8f2",
    tag: "#f92672",
    attribute: "#a6e22e",
    operator: "#f92672",
    punctuation: "#f8f8f2",
    heading: "#a6e22e",
    emphasis: "#e6db74",
    link: "#66d9ef",
    regex: "#e6db74",
  },
};

export const PALETTES: readonly Palette[] = [DARK_PLUS, LIGHT_PLUS, MONOKAI];

export const DEFAULT_PALETTE = DARK_PLUS.name;

/**
 * The palette for a name, or Dark+ for one this build does not know.
 *
 * Falls back rather than throwing for the same reason `get_permission` does
 * on the core: a stored preference from an older version, or a name typed
 * into a config file, should render as the default theme rather than as an
 * error the user has to diagnose.
 */
export function paletteFor(name: string): Palette {
  return PALETTES.find((p) => p.name === name) ?? DARK_PLUS;
}

/** A colour for a token kind, falling back to the palette's foreground. */
export function colorFor(palette: Palette, kind: TokenKind): string {
  return palette.colors[kind] ?? palette.foreground;
}

// ---------------------------------------------------------------------------
// The scanner
// ---------------------------------------------------------------------------

interface Rule {
  kind: TokenKind;
  re: RegExp;
  /** Classifies a match further: keywords by group, names by shape. */
  refine?: (match: RegExpExecArray) => TokenKind;
  /** Never let a rule match inside this kind (e.g. regex vs division). */
  skip?: boolean;
}

/** Build a sticky rule: it only matches at the scanner's current position. */
function rule(kind: TokenKind, source: string, refine?: Rule["refine"]): Rule {
  return { kind, re: new RegExp(source, "y"), refine };
}

/**
 * A sticky rule that may only match at the *start of a line*.
 *
 * The `m` flag is what makes `^` mean "line start" inside a sticky regex --
 * without it, `^` anchors to offset 0 of the whole file and a markdown
 * heading on line 40 never matches. Markdown and the config formats are
 * line-oriented, so their rules use this and the code scanners use `rule`.
 */
function lineRule(kind: TokenKind, source: string, refine?: Rule["refine"]): Rule {
  return { kind, re: new RegExp(source, "my"), refine };
}

const IDENT = "[A-Za-z_$][A-Za-z0-9_$]*";

/** Keywords per language, split by the colour VSCode gives them. */
interface Keywords {
  /** Control flow and imports: `if`, `return`, `import`. */
  keyword: string[];
  /** Declarations: `const`, `function`, `def`, `fn`. */
  declaration: string[];
  /** `true`, `false`, `null`, `None`, `this`, `self`. */
  literal: string[];
}

const C_LIKE: Keywords = {
  keyword: [
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "break", "continue", "return", "throw", "try", "catch", "finally",
    "new", "delete", "typeof", "instanceof", "in", "of", "await", "async",
    "yield", "import", "export", "from", "as", "with", "assert",
  ],
  declaration: [
    "var", "let", "const", "function", "class", "extends", "implements",
    "interface", "type", "enum", "namespace", "module", "declare", "abstract",
    "public", "private", "protected", "readonly", "static", "get", "set",
    "satisfies", "keyof", "infer", "is",
  ],
  literal: [
    "true", "false", "null", "undefined", "this", "super", "void", "never",
    "any", "unknown", "string", "number", "boolean", "object", "symbol",
    "bigint",
  ],
};

const PYTHON: Keywords = {
  keyword: [
    "if", "elif", "else", "for", "while", "break", "continue", "return",
    "yield", "try", "except", "finally", "raise", "with", "as", "import",
    "from", "in", "is", "not", "and", "or", "await", "async", "assert",
    "del", "global", "nonlocal", "pass", "lambda", "match", "case",
  ],
  declaration: ["def", "class"],
  literal: ["True", "False", "None", "self", "cls", "NotImplemented", "Ellipsis"],
};

const RUST: Keywords = {
  keyword: [
    "if", "else", "match", "loop", "while", "for", "in", "break", "continue",
    "return", "use", "mod", "crate", "super", "self", "where", "as", "await",
    "async", "move", "ref", "dyn", "unsafe", "impl", "trait", "yield",
  ],
  declaration: [
    "fn", "let", "mut", "const", "static", "struct", "enum", "union", "type",
    "pub", "extern", "trait", "impl",
  ],
  literal: ["true", "false", "None", "Some", "Ok", "Err"],
};

const GO: Keywords = {
  keyword: [
    "if", "else", "for", "range", "switch", "case", "default", "break",
    "continue", "return", "go", "defer", "select", "chan", "fallthrough",
    "goto", "import", "package",
  ],
  declaration: ["func", "var", "const", "type", "struct", "interface", "map"],
  literal: ["true", "false", "nil", "iota"],
};

const SQL: Keywords = {
  keyword: [
    "select", "from", "where", "insert", "into", "values", "update", "set",
    "delete", "create", "table", "drop", "alter", "join", "left", "right",
    "inner", "outer", "on", "group", "by", "order", "having", "limit",
    "offset", "union", "all", "distinct", "as", "and", "or", "not", "in",
    "like", "between", "is", "null", "asc", "desc", "case", "when", "then",
    "else", "end", "with", "primary", "key", "foreign", "references",
  ],
  declaration: [
    "int", "integer", "text", "varchar", "char", "boolean", "date",
    "timestamp", "numeric", "decimal", "serial", "uuid", "json", "jsonb",
    "real", "double", "precision", "bigint", "smallint",
  ],
  literal: ["true", "false", "null"],
};

const SHELL_KEYWORDS: Keywords = {
  keyword: [
    "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
    "done", "case", "esac", "in", "function", "return", "break", "continue",
    "export", "local", "readonly", "source", "alias", "set", "unset", "trap",
    "exit", "echo", "cd", "sudo",
  ],
  declaration: [],
  literal: ["true", "false"],
};

const CSHARP: Keywords = {
  keyword: [
    "if", "else", "for", "foreach", "while", "do", "switch", "case",
    "default", "break", "continue", "return", "throw", "try", "catch",
    "finally", "new", "using", "namespace", "in", "is", "as", "await",
    "async", "yield", "lock", "checked", "unchecked",
  ],
  declaration: [
    "class", "struct", "interface", "enum", "record", "public", "private",
    "protected", "internal", "static", "readonly", "const", "virtual",
    "override", "abstract", "sealed", "partial", "delegate", "event",
    "void", "var",
  ],
  literal: ["true", "false", "null", "this", "base", "value"],
};

const RUBY: Keywords = {
  keyword: [
    "if", "elsif", "else", "unless", "while", "until", "for", "in", "do",
    "end", "begin", "rescue", "ensure", "return", "yield", "break", "next",
    "redo", "retry", "raise", "require", "require_relative", "include",
    "extend", "and", "or", "not", "then", "case", "when",
  ],
  declaration: ["def", "class", "module", "attr_accessor", "attr_reader", "attr_writer"],
  literal: ["true", "false", "nil", "self", "super"],
};

const PHP: Keywords = {
  keyword: [
    "if", "else", "elseif", "for", "foreach", "while", "do", "switch",
    "case", "default", "break", "continue", "return", "throw", "try",
    "catch", "finally", "new", "echo", "print", "require", "include",
    "namespace", "use", "as", "and", "or", "xor", "instanceof", "match",
  ],
  declaration: [
    "function", "class", "interface", "trait", "public", "private",
    "protected", "static", "abstract", "final", "const", "var", "global",
  ],
  literal: ["true", "false", "null", "this", "self", "parent"],
};

/** Languages that share the C-family scanner, and their keyword sets. */
const C_FAMILY: Record<string, Keywords> = {
  typescript: C_LIKE,
  javascript: C_LIKE,
  tsx: C_LIKE,
  jsx: C_LIKE,
  java: C_LIKE,
  c: C_LIKE,
  cpp: C_LIKE,
  cs: CSHARP,
  rust: RUST,
  go: GO,
  sql: SQL,
  ruby: RUBY,
  php: PHP,
  shell: SHELL_KEYWORDS,
  python: PYTHON,
};

/**
 * Every language id this build can highlight.
 *
 * Built from the scanners' own tables rather than hand-listed, so a language
 * that gains a keyword set is highlightable in the same edit. A name outside
 * this set renders as plain text -- see `rulesFor`.
 */
const KNOWN_LANGUAGES = new Set<string>([
  ...Object.keys(C_FAMILY),
  "json",
  "html",
  "xml",
  "css",
  "markdown",
  "yaml",
  "toml",
  "ini",
]);

/** Quote characters a language's strings use, longest form first. */
function stringRules(language: string): Rule[] {
  const rules: Rule[] = [];
  if (language === "python") {
    // Docstrings first: `"""` must win over `"`.
    rules.push(rule("string", '(?:[rbfu]{0,2})"""[\\s\\S]*?"""'));
    rules.push(rule("string", "(?:[rbfu]{0,2})'''[\\s\\S]*?'''"));
    rules.push(rule("string", '(?:[rbfu]{0,2})"(?:\\\\.|[^"\\\\\\n])*"'));
    rules.push(rule("string", "(?:[rbfu]{0,2})'(?:\\\\.|[^'\\\\\\n])*'"));
    return rules;
  }
  if (language === "rust") {
    rules.push(rule("string", 'r#*"[\\s\\S]*?"#*'));
    rules.push(rule("string", 'b?"(?:\\\\.|[^"\\\\])*"'));
    rules.push(rule("string", "b?'(?:\\\\.|[^'\\\\])'"));
    return rules;
  }
  if (language === "shell") {
    rules.push(rule("template", '"(?:\\\\.|[^"\\\\])*"'));
    rules.push(rule("string", "'[^']*'"));
    rules.push(rule("string", "`[^`]*`"));
    return rules;
  }
  // The C family, plus the languages that borrow its quoting.
  rules.push(rule("template", "`(?:\\\\.|[^`\\\\])*`"));
  rules.push(rule("string", '"(?:\\\\.|[^"\\\\\\n])*"'));
  rules.push(rule("string", "'(?:\\\\.|[^'\\\\\\n])*'"));
  return rules;
}

/** Comments, longest form first so `//` does not eat `/*`. */
function commentRules(language: string): Rule[] {
  if (language === "python" || language === "shell" || language === "yaml" || language === "toml" || language === "ini" || language === "ruby") {
    return [rule("comment", "#[^\\n]*")];
  }
  if (language === "sql") {
    return [rule("comment", "--[^\\n]*"), rule("comment", "/\\*[\\s\\S]*?\\*/")];
  }
  if (language === "php") {
    return [rule("comment", "/\\*[\\s\\S]*?\\*/"), rule("comment", "//[^\\n]*"), rule("comment", "#[^\\n]*")];
  }
  return [rule("comment", "/\\*[\\s\\S]*?\\*/"), rule("comment", "//[^\\n]*")];
}

/**
 * The rules for one language, in the order they are tried.
 *
 * Order is the whole grammar: a comment before a string, a string before a
 * number, and identifiers last. `self`/`this` are listed as literals so
 * `this.foo` colours the `this` and leaves `foo` a property, which is what
 * VSCode does.
 *
 * **A language this build does not know returns no rules**, so the file
 * renders as plain text. The alternative -- falling through to the C-family
 * scanner -- would colour an unknown language's keywords as if it were
 * JavaScript, which is worse than no colour at all: it is *wrong* colour,
 * presented with the same confidence as the right kind.
 */
function rulesFor(language: string): Rule[] {
  if (language === "plain" || !KNOWN_LANGUAGES.has(language)) return [];
  if (language === "json") return jsonRules();
  if (language === "html" || language === "xml") return markupRules();
  if (language === "css") return cssRules();
  if (language === "markdown") return markdownRules();
  if (language === "yaml" || language === "toml" || language === "ini") {
    return configRules(language);
  }

  const keywords = C_FAMILY[language] ?? C_LIKE;
  const literalSet = new Set(keywords.literal);
  const keywordSet = new Set(keywords.keyword);
  const declarationSet = new Set(keywords.declaration);

  const classify = (match: RegExpExecArray): TokenKind => {
    const word = match[0];
    if (declarationSet.has(word)) return "declaration";
    if (keywordSet.has(word)) return "keyword";
    if (literalSet.has(word)) return "literal";
    // Capitalised names are types or constructors; lowercase followed by "("
    // is a call. VSCode distinguishes them the same way, for the same reason:
    // there is nothing else to go on without resolving anything.
    return /^[A-Z]/.test(word) ? "type" : "function";
  };

  const rules: Rule[] = [
    ...commentRules(language),
    ...stringRules(language),
  ];
  // Decorators and attributes: `@Component`, `#[derive(Debug)]`.
  rules.push(rule("type", "@[A-Za-z_$][\\w$.]*"));
  rules.push(rule("number", "0[xX][0-9a-fA-F_]+|0[bB][01_]+|\\d[\\d_]*(?:\\.\\d[\\d_]*)?(?:[eE][+-]?\\d+)?[a-zA-Z_]*"));
  rules.push(rule("type", `\\b${IDENT}\\b`, classify));
  rules.push(rule("operator", "=>|->|::|\\+\\+|--|&&|\\|\\||[+\\-*/%=<>!&|^~?]+"));
  rules.push(rule("punctuation", "[{}()\\[\\];,.:]"));
  return rules;
}

/** JSON: keys are properties, values are literals/strings/numbers. */
function jsonRules(): Rule[] {
  return [
    rule("property", '"(?:\\\\.|[^"\\\\])*"(?=\\s*:)'),
    rule("string", '"(?:\\\\.|[^"\\\\])*"'),
    rule("literal", "\\b(?:true|false|null)\\b"),
    rule("number", "-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?"),
    rule("punctuation", "[{}\\[\\],:]"),
  ];
}

/** HTML/XML: tags, attribute names, attribute values, entities, comments. */
function markupRules(): Rule[] {
  return [
    rule("comment", "<!--[\\s\\S]*?-->"),
    rule("string", '"[^"]*"'),
    rule("string", "'[^']*'"),
    rule("tag", "</?[A-Za-z][\\w:-]*"),
    // `<!doctype html>` has no name after `</?`, so without this the doctype is
    // the one line of a page that is plain text and a stray `>` gets the tag
    // colour, which reads as a broken tag rather than as a doctype.
    rule("tag", "<![A-Za-z][\\w-]*"),
    rule("tag", "/?>"),
    rule("attribute", "[A-Za-z_:][\\w:.-]*(?=\\s*=)"),
    rule("literal", "&[a-zA-Z#0-9]+;"),
    rule("punctuation", "[=]"),
  ];
}

/**
 * CSS: at-rules, selectors, properties, values.
 *
 * **The values are the change.** The rules used to stop at the property name,
 * so `display: flex;` coloured the `display` and left the `flex` -- and since
 * a stylesheet is mostly values, a CSS file came out looking like prose with
 * its first word in bold. VSCode gives those bare words `#569CD6` (its keyword
 * blue, this file's `declaration`), so that is what the rule near the end is
 * for, and it is the *last* rule that can match a word: property names win
 * over it because they are tried first and require the `:` that a value does
 * not have.
 *
 * The element selector has the same problem in reverse -- `body` is a word at
 * the head of a selector, and rule order alone cannot tell it from a value,
 * because both are just words. The selector form is therefore anchored to the
 * line's start, which is where a selector's first element name is written.
 */
function cssRules(): Rule[] {
  return [
    rule("comment", "/\\*[\\s\\S]*?\\*/"),
    rule("string", '"[^"]*"'),
    rule("string", "'[^']*'"),
    rule("keyword", "@[\\w-]+"),
    rule("literal", "![a-zA-Z-]+"),
    // A custom property, wherever it appears: `--fg` is the same token when it
    // is being defined in `:root` and when it is read back out of `var()`.
    rule("property", "--[\\w-]+"),
    rule("property", "[-\\w]+(?=\\s*:)"),
    rule("number", "#[0-9a-fA-F]{3,8}\\b|\\d+(?:\\.\\d+)?(?:px|em|rem|%|vh|vw|s|ms|fr|deg)?\\b"),
    rule("function", "[\\w-]+(?=\\()"),
    // The selector forms that carry a marker of their own: classes, ids and
    // pseudo-classes. A bare `#main` is not a colour -- the hex rule above
    // only claims it when every character after the `#` is hexadecimal.
    rule("type", "\\.[-_a-zA-Z][\\w-]*|#{1,2}[\\w-]+|:{1,2}[\\w-]+"),
    // `(?!\s*:)` is what keeps a *property* from being read as an element
    // name: this rule may swallow the line's leading spaces, so without it an
    // indented `color: red;` matched here -- at the line's first space, where
    // the property rule cannot match yet -- and every indented declaration in a
    // stylesheet came out the colour of a selector.
    lineRule("type", "^\\s*[a-zA-Z][\\w-]*(?!\\s*:)(?=[\\s,{:.\\[>+~])"),
    rule("declaration", "[-a-zA-Z_][\\w-]*"),
    rule("punctuation", "[{}();:,]"),
  ];
}

/** Markdown: headings, emphasis, code, links, quotes, list markers. */
function markdownRules(): Rule[] {
  return [
    rule("emphasis", "```[\\s\\S]*?```"),
    rule("string", "`[^`\\n]*`"),
    lineRule("heading", "#{1,6}[^\\n]*"),
    rule("emphasis", "\\*\\*[^*\\n]+\\*\\*|__[^_\\n]+__"),
    rule("emphasis", "\\*[^*\\n]+\\*|_[^_\\n]+_"),
    rule("link", "!?\\[[^\\]\\n]*\\]\\([^)\\n]*\\)"),
    rule("link", "\\[[^\\]\\n]*\\]\\[[^\\]\\n]*\\]"),
    lineRule("keyword", "\\s*[-*+]\\s|\\s*\\d+\\.\\s"),
    lineRule("comment", "\\s*>[^\\n]*"),
    lineRule("type", "\\s*(?:---+|===+|\\*\\*\\*+)\\s*$"),
  ];
}

/** YAML / TOML / INI: keys, strings, numbers, comments, booleans. */
function configRules(language: string): Rule[] {
  const rules: Rule[] = [rule("comment", "#[^\\n]*")];
  rules.push(rule("string", '"(?:\\\\.|[^"\\\\])*"'));
  rules.push(rule("string", "'[^']*'"));
  // A key is a bare word or a quoted string before the separator.
  rules.push(rule("property", '"[^"]*"(?=\\s*[:=])'));
  rules.push(rule("property", "'[^']*'(?=\\s*[:=])"));
  rules.push(lineRule("property", "\\s*[\\w.$-]+(?=\\s*[:=])"));
  if (language === "yaml") {
    rules.push(lineRule("keyword", "\\s*-\\s"));
    rules.push(lineRule("type", "\\s*&?\\*?[\\w.$-]+(?=\\s*:\\s*$)"));
  }
  if (language === "toml") {
    rules.push(lineRule("type", "\\s*\\[{1,2}[^\\]]+\\]{1,2}"));
  }
  if (language === "ini") {
    rules.push(lineRule("type", "\\s*\\[[^\\]]+\\]"));
  }
  rules.push(rule("literal", "\\b(?:true|false|yes|no|on|off|null|nil)\\b"));
  rules.push(rule("number", "\\b-?\\d+(?:\\.\\d+)?\\b"));
  rules.push(rule("punctuation", "[:=\\[\\]{},]"));
  return rules;
}

/**
 * Highlight `text` as `language`, one token list per line.
 *
 * One pass, left to right, each rule tried in order at the cursor. A
 * character no rule matches is left *out* of the result rather than emitted
 * as a `plain` token: the renderer fills the gaps, so the token lists stay
 * small on prose-heavy files and a gap carries no meaning that a `plain`
 * token would add.
 *
 * Multi-line constructs (block comments, template literals, docstrings) are
 * split at each newline, because the viewer draws lines:
 * `[[{start,end,kind}], ...]`.
 */
export function tokenize(text: string, language: string): Token[][] {
  // Markup first, because its own scan cannot see the languages inside it:
  // a `<style>` body and a `<script>` body are other languages' text, and the
  // markup rules colour neither -- they colour the tags around it. That was
  // the visible bug: a page with a stylesheet in its head drew the CSS as
  // plain text, and the `=` in `a = 1` inside a script as an attribute.
  if (language === "html" || language === "xml") return tokenizeMarkup(text, language);

  const rules = rulesFor(language);
  const lines = lineStarts(text);
  if (rules.length === 0) return lines.map(() => [] as Token[]);
  return scan(text, lines, rules);
}

/**
 * The single scan: each rule tried in order at the cursor, gaps left out.
 *
 * Extracted so the markup pass can run it over a *masked* copy of the text and
 * keep the offsets, which is what lets one document be highlighted by two
 * scanners -- see `tokenizeMarkup`.
 */
function scan(text: string, lines: number[], rules: Rule[]): Token[][] {
  const result: Token[][] = lines.map(() => [] as Token[]);
  let pos = 0;

  while (pos < text.length) {
    let matched = false;
    for (const r of rules) {
      r.re.lastIndex = pos;
      const m = r.re.exec(text);
      if (!m || m.index !== pos || m[0].length === 0) continue;
      const kind = r.refine ? r.refine(m) : r.kind;
      emit(result, lines, text, pos, pos + m[0].length, kind);
      pos += m[0].length;
      matched = true;
      break;
    }
    if (!matched) pos += 1;
  }
  return result;
}

/** A markup region whose *contents* are another language. */
interface Embedded {
  /** The tag that opens it, without the brackets: `style`, `script`. */
  tag: string;
  language: string;
}

const EMBEDDED: readonly Embedded[] = [
  { tag: "style", language: "css" },
  { tag: "script", language: "javascript" },
];

/** One `<style>`/`<script>` body, as offsets into the whole document. */
interface Block {
  start: number;
  end: number;
  language: string;
}

/**
 * Where the embedded bodies are.
 *
 * A scanner, not a parser, and the difference shows in one place worth naming:
 * `<style>` written *inside an HTML comment* is skipped, because a commented-out
 * stylesheet is a thing real pages contain and reading it as live CSS would
 * colour the comment's own text as if it were the page. A `</style>` inside a
 * CSS string ends the block early for the same reason a real highlighter's
 * simpler cousin does.
 */
function embeddedBlocks(text: string): Block[] {
  const lower = text.toLowerCase();
  const comments = [...lower.matchAll(/<!--[\s\S]*?-->/g)].map((m) => [
    m.index ?? 0,
    (m.index ?? 0) + m[0].length,
  ]);
  const commentedOut = (at: number) =>
    comments.some(([from, to]) => at >= from && at < to);

  const blocks: Block[] = [];
  let at = 0;
  for (;;) {
    // The earliest opening tag of any embedded language at or after `at`, and
    // the first one of each kind that is not inside a comment.
    let best: { tag: string; language: string; start: number; body: number } | null = null;
    for (const { tag, language } of EMBEDDED) {
      const open = new RegExp(`<${tag}\\b[^>]*>`, "g");
      open.lastIndex = at;
      for (let m = open.exec(lower); m; m = open.exec(lower)) {
        if (commentedOut(m.index)) continue;
        if (!best || m.index < best.start) {
          best = { tag, language, start: m.index, body: m.index + m[0].length };
        }
        break;
      }
    }
    if (!best) break;
    const close = lower.indexOf(`</${best.tag}`, best.body);
    blocks.push({
      start: best.body,
      end: close === -1 ? text.length : close,
      language: best.language,
    });
    at = close === -1 ? text.length : close + 2;
  }
  return blocks;
}

/** The same text with the embedded bodies blanked, offsets and newlines kept. */
function blankOut(text: string, blocks: Block[]): string {
  const chars = text.split("");
  for (const block of blocks) {
    for (let index = block.start; index < block.end; index += 1) {
      if (chars[index] !== "\n") chars[index] = " ";
    }
  }
  return chars.join("");
}

/**
 * Markup, with each embedded body highlighted by its own language.
 *
 * The two passes cannot share a scan, so they share the *offsets* instead: the
 * markup pass runs over a copy with the bodies blanked (a space where a
 * character was, a newline where there was one), which leaves every other
 * offset exactly where it was, and the embedded pass runs over the real text of
 * each body and has its results shifted into place. Blanks rather than a
 * skipped range on purpose: a scanner has no notion of skipping, and a blank is
 * the one thing no rule matches.
 */
function tokenizeMarkup(text: string, language: string): Token[][] {
  const lines = lineStarts(text);
  const rules = rulesFor(language);
  const blocks = embeddedBlocks(text);
  const masked = blocks.length > 0 ? blankOut(text, blocks) : text;
  const result = rules.length > 0 ? scan(masked, lines, rules) : lines.map(() => [] as Token[]);

  for (const block of blocks) {
    const inner = text.slice(block.start, block.end);
    const innerLines = lineStarts(inner);
    tokenize(inner, block.language).forEach((row, index) => {
      if (row.length === 0) return;
      const absolute = block.start + innerLines[index];
      const line = lineAt(lines, absolute);
      const column = absolute - lines[line];
      for (const token of row) {
        result[line].push({
          start: token.start + column,
          end: token.end + column,
          kind: token.kind,
        });
      }
    });
  }
  return result;
}

/** Every line's starting offset, plus one past the end as a sentinel. */
function lineStarts(text: string): number[] {
  const starts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") starts.push(index + 1);
  }
  return starts;
}

/** Copy one absolute-offset token into the per-line lists it covers. */
function emit(
  result: Token[][],
  lines: number[],
  text: string,
  start: number,
  end: number,
  kind: TokenKind,
): void {
  let lineIndex = lineAt(lines, start);
  let cursor = start;
  while (cursor < end && lineIndex < lines.length) {
    const lineStart = lines[lineIndex];
    const nextLineStart = lineIndex + 1 < lines.length ? lines[lineIndex + 1] : text.length + 1;
    // The content end of this line, excluding its newline.
    const contentEnd = nextLineStart - 1;
    const segmentEnd = Math.min(end, contentEnd);
    if (segmentEnd > cursor) {
      result[lineIndex].push({
        start: cursor - lineStart,
        end: segmentEnd - lineStart,
        kind,
      });
    }
    if (segmentEnd >= end) break;
    // The token continues past this line's newline.
    lineIndex += 1;
    cursor = lines[lineIndex] ?? end;
  }
}

/** The index of the line containing `offset`. */
function lineAt(lines: number[], offset: number): number {
  let low = 0;
  let high = lines.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (lines[mid] <= offset) low = mid;
    else high = mid - 1;
  }
  return low;
}
