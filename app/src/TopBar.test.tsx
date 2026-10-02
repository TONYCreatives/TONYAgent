/**
 * The app's own title bar.
 *
 * `decorations: false` removed the system bar, so two things Windows used to
 * provide are markup here now, and these are the tests for them:
 *
 * - **The bar is a drag region.** Without `data-tauri-drag-region` the window
 *   cannot be moved at all, and nothing in the UI says so -- the window simply
 *   has no handle. Set to anything other than `"deep"` and almost nothing is
 *   draggable either, because a bare attribute only drags presses that land on
 *   the element itself and every pixel of this bar is covered by a child.
 * - **The caption exists and is wired.** Three glyphs that do nothing are worse
 *   than no glyphs, so each button is asserted against the action it names, and
 *   the middle one is asserted to change what it offers when the window is
 *   maximized.
 * - **A right-click on the bar opens the system menu**, and only that. Windows
 *   answers a right-click on the caption with the window menu, and the webview
 *   answers the same press with its own -- so the bar has to claim it, and the
 *   test asserts both halves: the menu was asked for, and the page's menu was
 *   stopped.
 *
 * The bar is rendered with `controls` supplied rather than calling
 * `useWindowControls` itself, which is what keeps it renderable here at all: in
 * jsdom there is no Tauri shell, so the hook reports null by design. The
 * shortcut behind the menu is in `useWindowControls.test.tsx`, where the shell
 * can be stood up.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { TopBar } from "./TopBar.js";
import { all, click, contextMenu, one, render, texts } from "./test-render.js";

interface Calls {
  minimized: number;
  toggled: number;
  closed: number;
  menus: number;
}

/** Mount the bar with a caption that records what it was asked to do. */
async function bar(options: {
  maximized?: boolean;
  caption?: boolean;
  busy?: boolean;
  title?: string;
} = {}): Promise<{ container: HTMLElement; calls: Calls }> {
  const calls: Calls = { minimized: 0, toggled: 0, closed: 0, menus: 0 };
  const withCaption = options.caption ?? true;
  const container = await render(
    <TopBar
      busy={options.busy ?? false}
      title={options.title ?? "Explain the sidecar stdio framing"}
      controls={
        withCaption
          ? {
              maximized: options.maximized ?? false,
              minimize: () => (calls.minimized += 1),
              toggleMaximize: () => (calls.toggled += 1),
              close: () => (calls.closed += 1),
              showSystemMenu: () => (calls.menus += 1),
            }
          : null
      }
    />,
  );
  return { container, calls };
}

const buttons = (container: HTMLElement) => all(container, ".win-btn");

// --- the drag region -------------------------------------------------------
describe("the title bar as a drag region", () => {
  test("the bar is the window's drag handle", async () => {
    // The attribute is the whole feature. With `decorations: false` there is no
    // caption to grab, so a window without this cannot be moved at all -- and
    // there is no control anywhere in the app that says so.
    const { container } = await bar();
    assert.equal(
      one(container, ".topbar")!.getAttribute("data-tauri-drag-region"),
      "deep",
    );
  });

  test("it is deep rather than bare", async () => {
    // Tauri walks the pressed element's ancestor chain looking for the
    // attribute. A bare one only drags when the press lands on the element
    // itself, and this bar is a tab pill, a title and a caption -- so bare would
    // leave the draggable area down to the padding, which is most of the
    // failure being guarded and none of the feature.
    //
    // Asserted on the literal value rather than in a comment because the bug is
    // a silent one: a bare attribute still looks like a drag region in the
    // markup, in review and in every static check.
    const { container } = await bar();
    const region = one(container, ".topbar")!.getAttribute("data-tauri-drag-region");
    assert.ok(region, "the bar carries no drag region at all");
    assert.notEqual(region, "", "a bare attribute only drags on the element itself");
    assert.notEqual(region, "true", "a bare attribute only drags on the element itself");
  });
});

// --- the caption -----------------------------------------------------------
describe("the caption buttons", () => {
  test("there are three, and close is last", async () => {
    // Windows puts close last, and the position is what has to match for the
    // muscle memory to carry over. Close is also the only one with a class of
    // its own, because it is the only one that changes colour on hover.
    const { container } = await bar();
    assert.equal(buttons(container).length, 3);
    assert.ok(
      buttons(container)[2].classList.contains("is-close"),
      "close is not the last button",
    );
  });

  test("each one is named, because three unlabelled buttons announce as three buttons", async () => {
    const { container } = await bar();
    assert.deepEqual(
      buttons(container).map((b) => b.getAttribute("aria-label")),
      ["Minimize window", "Maximize window", "Close window"],
    );
    assert.deepEqual(
      buttons(container).map((b) => b.getAttribute("title")),
      ["Minimize", "Maximize", "Close"],
    );
  });

  test("the glyphs are drawn, not typed", async () => {
    // "–", "□" and "×" come from whatever font is installed and sit at
    // different baselines in each of them. The caption is the one part of a
    // window whose alignment is judged against the OS, so it has to line up
    // with itself.
    const { container } = await bar();
    assert.equal(texts(container, ".win-btn").join(""), "", "a glyph is a character");
    assert.equal(
      buttons(container).filter((b) => b.querySelector("svg")).length,
      3,
      "a caption button is not drawn",
    );
  });

  test("minimize and close do what they say", async () => {
    const { container, calls } = await bar();
    await click(buttons(container)[0]);
    await click(buttons(container)[2]);
    assert.deepEqual(calls, { minimized: 1, toggled: 0, closed: 1, menus: 0 });
  });

  test("the middle button offers to restore a maximized window", async () => {
    // Wrong in both the directions that matter: "maximize" on a maximized
    // window does nothing visible, and "restore" on a normal one is a label for
    // an action that is not on offer.
    const { container, calls } = await bar({ maximized: true });
    const middle = buttons(container)[1];
    assert.equal(middle.getAttribute("aria-label"), "Restore window");
    assert.equal(middle.getAttribute("title"), "Restore");
    await click(middle);
    assert.equal(calls.toggled, 1);
  });

  test("they are buttons, which is what makes them keyboard-operable", async () => {
    // Windows' own caption has no mnemonics on its buttons -- the system menu is
    // where the keyboard goes, and this bar now opens that same menu on F10 and
    // on a right-click. What the buttons themselves owe a keyboard user is
    // being real buttons: Tab reaches them and Enter or Space presses them,
    // which is true of a `<button>` and false of a `<div>` with a click handler
    // dressed up as one. Asserted on the tag, because jsdom's Enter handling is
    // its own business and the tag is the thing a browser acts on.
    const { container } = await bar();
    for (const button of buttons(container)) {
      assert.equal(button.tagName, "BUTTON");
      assert.equal(button.getAttribute("type"), "button", "a submit in a form");
      assert.notEqual(button.getAttribute("tabindex"), "-1", "out of the tab order");
      assert.equal(button.getAttribute("disabled"), null);
    }
  });

  test("the caption is not drawn where there is no window to caption", async () => {
    // In a browser preview there is nothing to minimize. Three buttons that
    // look like they work and do not are the failure this replaces.
    const { container } = await bar({ caption: false });
    assert.equal(one(container, ".window-controls"), null);
  });
});

// --- the system menu --------------------------------------------------------
describe("a right-click on the title bar", () => {
  test("opens the window's own menu", async () => {
    // Restore, Move, Size, Minimize, Maximize, Close -- and the two in the
    // middle of that list are drag loops the OS runs. Without them an
    // undecorated window cannot be placed or resized, which is why this is on
    // the bar and not only behind Alt+Space.
    const { container, calls } = await bar();
    await contextMenu(one(container, ".topbar")!);
    assert.equal(calls.menus, 1);
  });

  test("and not the webview's menu as well", async () => {
    // Two menus for one right-click, one of them offering to reload a document
    // that is not a document. `preventDefault` is the whole difference and
    // nothing in the markup shows it, which is why it is asserted.
    const { container } = await bar();
    const event = await contextMenu(one(container, ".topbar")!);
    assert.equal(event.defaultPrevented, true, "the webview menu was not stopped");
  });

  test("a right-click on a caption button opens it too", async () => {
    // What Windows does: the caption is the frame, and the frame's menu does
    // not stop at the glyphs. Also the reason the handler is on the header
    // rather than on the one empty patch of bar between the title and the
    // buttons.
    const { container, calls } = await bar();
    await contextMenu(buttons(container)[2]);
    assert.equal(calls.menus, 1);
  });

  test("where there is no window, the page keeps its own right-click", async () => {
    // A browser preview has a document, a selection and a save-as. Swallowing
    // its context menu to open a window menu would take away something that
    // works, in exchange for something that cannot.
    const { container, calls } = await bar({ caption: false });
    const event = await contextMenu(one(container, ".topbar")!);
    assert.equal(calls.menus, 0);
    assert.equal(event.defaultPrevented, false);
  });
});

// --- the bar's original job ------------------------------------------------
describe("the title bar as a top bar", () => {
  test("it names the conversation that is open", async () => {
    const { container } = await bar();
    assert.match(one(container, ".tab-title")!.textContent ?? "", /sidecar/);
  });

  test("the busy spinner is still there", async () => {
    // The bar's original job, and the reason it is not only a caption: it is
    // the one place the window says whether it is working. A spinner removed
    // for being decorative is a turn that looks finished.
    const { container } = await bar({ busy: true });
    assert.ok(one(container, ".tab-spinner"));
  });

  test("a window with no conversation yet still says what it is", async () => {
    const { container } = await bar({ title: "" });
    assert.equal(one(container, ".tab-title")!.textContent, "TONYAgent");
  });
});