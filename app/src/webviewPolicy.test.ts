import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

// `index.html`'s `<meta http-equiv="Content-Security-Policy">` is the one place
// the window's rules live, and nothing in the app source can see them: a CSP
// that forbids something simply makes the browser drop it, with no error in the
// console and no failure in a jsdom test, because jsdom has no CSP enforcement
// at all. Every preview in this app is a `data:` URL rendered by an <img>, so
// this file is the tripwire for a class of bug that is invisible everywhere
// else.
//
// It read `tauri.conf.json` until the shell moved out of Rust. The policy itself
// did not change with the move -- it changed *home* -- and this test moved with
// it, which is the whole point: a policy nobody asserts is a policy that quietly
// stops being one.

/**
 * The policy, read out of the tag.
 *
 * A regex rather than an HTML parser, deliberately: this file must not need a
 * dependency to read one string, and the tag has exactly one attribute worth
 * reading. `[^>]*` rather than `.*` so the multi-line tag matches without the
 * `s` flag.
 */
const policy = (): string => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const tag = /<meta[^>]*http-equiv="Content-Security-Policy"[^>]*>/i.exec(html);
  const content = tag ? /content="([^"]*)"/i.exec(tag[0]) : null;
  return content?.[1] ?? "";
};

/** The policy, split into directives; quoted keywords lose only the quotes. */
const directives = (): Map<string, string[]> => {
  const map = new Map<string, string[]>();
  for (const part of policy().split(";")) {
    const tokens = part.trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) continue;
    map.set(
      tokens[0]!,
      tokens.slice(1).map((source) => source.replace(/^'(.*)'$/, "$1")),
    );
  }
  return map;
};

describe("the webview's content security policy", () => {
  test("the page declares a policy at all", () => {
    // Every other test here reads a directive out of this string, and an empty
    // string would let several of them pass vacuously -- "no http: in img-src"
    // is trivially true of nothing at all. So the tag itself is asserted first.
    assert.match(
      policy(),
      /default-src/,
      "index.html declares no content security policy, so the window has none",
    );
  });

  test("attachment previews are pictures the app builds in memory", () => {
    // Not decoration: every queued attachment gets a thumbnail from
    // `attachments.ts` with no round trip to disk, which can only be a data:
    // URL. Without this the picker and the paste handler both queue a file the
    // user cannot see, and the <img> reports naturalWidth 0.
    const img = directives().get("img-src");
    assert.ok(img, "the policy says nothing about images, so default-src 'self' governs them");
    assert.ok(
      img.includes("data:"),
      `img-src is ${JSON.stringify(img)}: no data:, so every attachment preview is blocked`,
    );
  });

  test("images still come from the app itself and nowhere else", () => {
    // The preview is the reason to open img-src; it is not a licence to pull
    // remote pixels into a page that otherwise talks only to its own origin.
    const img = directives().get("img-src")!;
    assert.ok(img.includes("self"), `img-src is ${JSON.stringify(img)}: no 'self'`);
    for (const scheme of ["http:", "https:"]) {
      assert.ok(
        !img.includes(scheme),
        `img-src is ${JSON.stringify(img)}: it allows ${scheme}, so a remote image could load`,
      );
    }
  });

  test("a directive is present for each thing the app loads", () => {
    // A missing directive is not neutral -- it falls back to default-src, which
    // is 'self'. Listing them makes an accidental deletion loud.
    const policy = directives();
    for (const name of ["default-src", "style-src", "font-src", "img-src"]) {
      assert.ok(policy.has(name), `the policy has no ${name} directive`);
    }
  });

  test("scripts are still 'self' only, so no eval and no inline handlers", () => {
    // Unrelated to previews, and the reason a CSP edit is not a free change:
    // loosening script-src would undo the protections this file is here to
    // make sure nobody loosens by accident.
    const script = directives().get("script-src") ?? directives().get("default-src")!;
    assert.ok(script.includes("self"), `scripts resolve to ${JSON.stringify(script)}`);
    for (const loose of ["unsafe-eval", "unsafe-inline"]) {
      assert.ok(!script.includes(loose), `scripts resolve to ${JSON.stringify(script)}`);
    }
  });
});