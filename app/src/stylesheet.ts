/**
 * The stylesheet, as the cascade sees it.
 *
 * `styles.css` is an entry: it `@import`s one module per surface out of
 * `styles/`, in the order they were a single file. Everything that needs to
 * read the cascade -- the layout tests, the reduced-motion test, the Python
 * audit -- needs the *concatenation*, not the entry, because the entry is a
 * list of imports and contains no rules at all.
 *
 * So the rule for reading it lives here rather than being written out in the
 * three places that need it, where the third copy would be the one that
 * forgets. `scripts/audit_reduced_motion.py` reads the same concatenation by
 * the same convention, which is why it is spelled out in the entry file's
 * comment too.
 */

import { readFileSync } from "node:fs";

// `../src/`, not `./`: `tsc -p tsconfig.test.json` emits into `.tmp/` and
// copies no other file, so a compiled test resolves its neighbours from there
// rather than from the source tree. The same `../src/` the tests used when they
// read `styles.css` directly.
const SRC = new URL("../src/", import.meta.url);

/** The `@import` order, which is the cascade order. */
export function stylesheetModules(): string[] {
  const entry = readFileSync(new URL("styles.css", SRC), "utf8");
  return [...entry.matchAll(/@import\s+"\.\/styles\/([^"]+)"/g)].map((m) => m[1]);
}

/**
 * Every rule, in cascade order, as one string.
 *
 * Joined with a newline rather than nothing, so a module that ends mid-comment
 * cannot swallow the first line of the next one. The modules are written with
 * their trailing blank lines trimmed, so this introduces no rules of its own.
 */
export function readStylesheet(): string {
  return stylesheetModules()
    .map((name) => readFileSync(new URL(`styles/${name}`, SRC), "utf8").replace(/\s+$/, ""))
    .join("\n");
}

/** The same, with every comment stripped, for asserting that something is absent. */
export function readStylesheetSource(): string {
  return readStylesheet().replace(/\/\*[\s\S]*?\*\//g, "");
}
