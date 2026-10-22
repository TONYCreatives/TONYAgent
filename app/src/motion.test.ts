/**
 * The Motion menu's preference: what it remembers, what it applies, and what
 * it reports.
 *
 * Three claims, and all three are about the override rather than the
 * stylesheet: the menu persists across launches, `system` leaves the root
 * alone so the OS media query answers on its own, and anything else is named
 * on the root where both override blocks in `reduced-motion.css` look for it.
 * The stylesheet half is pinned by `reducedMotion.test.ts`; this is the JS
 * half.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { dom } from "./test-dom.js";
import {
  applyMotionPreference,
  isMotionReduced,
  readMotionPreference,
} from "./motion.js";

function withMatchMedia(matches: boolean): () => void {
  const had = Object.getOwnPropertyDescriptor(dom.window, "matchMedia");
  Object.defineProperty(dom.window, "matchMedia", {
    configurable: true,
    writable: true,
    value: () => ({ matches }),
  });
  return () => {
    if (had) Object.defineProperty(dom.window, "matchMedia", had);
    else delete (dom.window as unknown as Record<string, unknown>).matchMedia;
  };
}

describe("readMotionPreference", () => {
  test("it is the system answer when nothing was ever chosen", () => {
    dom.window.localStorage.clear();
    assert.equal(readMotionPreference(), "system");
  });

  test("it remembers the last choice", () => {
    dom.window.localStorage.clear();
    applyMotionPreference("full");
    assert.equal(readMotionPreference(), "full");
  });
});

describe("applyMotionPreference", () => {
  test("system removes the attribute, so the media query answers alone", () => {
    applyMotionPreference("full");
    applyMotionPreference("system");
    assert.equal(dom.window.document.documentElement.getAttribute("data-motion"), null);
  });

  test("anything else is named on the root, where the stylesheet looks", () => {
    applyMotionPreference("reduced");
    assert.equal(dom.window.document.documentElement.getAttribute("data-motion"), "reduced");
    applyMotionPreference("system");
  });
});

describe("isMotionReduced", () => {
  test("full wins over an OS that asks for stillness", () => {
    const restore = withMatchMedia(true);
    try {
      applyMotionPreference("full");
      assert.equal(isMotionReduced(), false);
    } finally {
      applyMotionPreference("system");
      restore();
    }
  });

  test("reduced wins over an OS that does not", () => {
    const restore = withMatchMedia(false);
    try {
      applyMotionPreference("reduced");
      assert.equal(isMotionReduced(), true);
    } finally {
      applyMotionPreference("system");
      restore();
    }
  });

  test("system defers to the OS either way", () => {
    applyMotionPreference("system");
    let restore = withMatchMedia(true);
    assert.equal(isMotionReduced(), true);
    restore();
    restore = withMatchMedia(false);
    assert.equal(isMotionReduced(), false);
    restore();
  });
});
