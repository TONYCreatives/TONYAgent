/**
 * The app's own title bar.
 *
 * The host creates the window without decorations, so two things Windows used to
 * provide are markup here now, and these are the tests for them:
 *
 * - **The bar is a drag region.** Without `app-drag-region` the window cannot be
 *   moved at all, and nothing in the UI says so -- the window simply has no
 *   handle. The class has to be on the bar *and* on the background regions inside
 *   it, because the press only counts when it lands on an element carrying the
 *   class itself; the controls are separate elements and stay clickable, which is
 *   what the second and third tests here pin down. What the class *does* is in
 *   `useWindowControls.test.tsx`: the press asks the host for the OS's own move
 *   loop, which is what makes the window snappable.
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
 * jsdom there is no host, so the hook reports null by design. The shortcut
 * behind the menu is in `useWindowControls.test.tsx`, where the host can be
 * stood up.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { ReactNode } from "react";

import { TopBar, type Tab } from "./TopBar.js";
import { all, click, contextMenu, one, press, render, setValue, texts } from "./test-render.js";

/** One tab of the strip, as `App` builds them. */
const tab = (over: Partial<Tab> = {}): Tab => ({
  id: "c1",
  title: "Explain the sidecar stdio framing",
  renameable: true,
  ...over,
});

interface Calls {
  minimized: number;
  toggled: number;
  closed: number;
  menus: number;
  selected: string[];
  closedTabs: string[];
  newTabs: number;
  renamed: [string, string][];
}

/** Mount the bar with a caption that records what it was asked to do. */
async function bar(options: {
  maximized?: boolean;
  caption?: boolean;
  busy?: boolean;
  tabs?: Tab[];
  active?: string;
  track?: string;
  onTrackChange?: (track: string) => void;
  status?: ReactNode;
} = {}): Promise<{ container: HTMLElement; calls: Calls & { tracks: string[] } }> {
  const calls: Calls & { tracks: string[] } = {
    minimized: 0,
    toggled: 0,
    closed: 0,
    menus: 0,
    selected: [],
    closedTabs: [],
    newTabs: 0,
    renamed: [],
    tracks: [],
  };
  const withCaption = options.caption ?? true;
  const container = await render(
    <TopBar
      busy={options.busy ?? false}
      tabs={options.tabs ?? [tab()]}
      active={options.active ?? "c1"}
      onSelect={(id) => calls.selected.push(id)}
      onClose={(id) => calls.closedTabs.push(id)}
      onNewTab={() => (calls.newTabs += 1)}
      onRename={(id, title) => calls.renamed.push([id, title])}
      track={options.track}
      onTrackChange={
        options.onTrackChange ?? (options.track !== undefined ? (t) => calls.tracks.push(t) : undefined)
      }
      status={options.status}
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

// --- the track toggle ------------------------------------------------------
describe("the Chat / Build toggle", () => {
  const tracks = (container: HTMLElement) =>
    all(container, '.topbar-modes[aria-label="Track"] .topbar-mode');

  test("it is absent where there is no conversation to mint from", async () => {
    // Trajectory and settings have no conversation in front: a toggle there
    // would mint a chat behind the page. The bar draws it only when the
    // window hands it a press to make.
    const { container } = await bar();
    assert.equal(tracks(container).length, 0, "the toggle drew with no handler");
  });

  test("both tracks are named, and the current one is pressed", async () => {
    const { container } = await bar({ track: "chat" });
    assert.deepEqual(
      tracks(container).map((b) => (b.textContent ?? "").trim()),
      ["Chat", "Build"],
    );
    assert.equal(
      tracks(container).find((b) => b.classList.contains("is-active"))?.textContent,
      "Chat",
    );
  });

  test("pressing a track reports it; the parent owns the state", async () => {
    const { container, calls } = await bar({ track: "build" });
    const chat = tracks(container).find((b) => (b.textContent ?? "").trim() === "Chat")!;

    await click(chat);

    assert.deepEqual(calls.tracks, ["chat"]);
    assert.equal(chat.getAttribute("aria-pressed"), "false", "the parent owns the state");
  });
});

// --- the run pill's slot ---------------------------------------------------
describe("the run pill's slot", () => {
  test("it sits between the track toggle and the window's own controls", async () => {
    // The bar's order is the three questions it answers, left to right: what
    // kind of conversation this is, what is happening in it, and what the window
    // is bound to. The pill is placed, not built, here -- its own behaviour is
    // in `StatusPill.test.tsx` -- and this is the half that says where.
    const { container } = await bar({
      track: "build",
      status: <span className="test-status" />,
    });
    const pill = one(container, ".test-status")!;
    assert.equal(
      pill.previousElementSibling?.getAttribute("aria-label"),
      "Track",
      "the pill is not after the track toggle",
    );
    assert.ok(
      pill.nextElementSibling?.classList.contains("window-controls"),
      "the pill is not before the caption",
    );
  });
});

// --- the drag region -------------------------------------------------------
describe("the title bar as a drag region", () => {
  /** Every element the host will treat as a drag handle. */
  const regions = (container: HTMLElement) => all(container, ".app-drag-region");

  test("the bar is the window's drag handle", async () => {
    // The class is the whole feature. With no decorations there is no caption to
    // grab, so a window without it cannot be moved at all -- and there is no
    // control anywhere in the app that says so.
    const { container } = await bar();
    assert.ok(
      one(container, ".topbar")!.classList.contains("app-drag-region"),
      "the bar carries no drag region at all",
    );
  });

  test("the bar and its background drag; nothing else does", async () => {
    // A press moves the window only when it lands on an element carrying the
    // class *itself*. That makes this set of
    // classes the whole definition of what is draggable -- and it is why the
    // class is on the bar and on the regions inside it that are nothing but
    // background, rather than inherited by everything the bar contains: the
    // caption buttons and the model picker have to stay clickable.
    //
    // Asserted as the exact set rather than as a count, because a class added to
    // the wrong element is the failure being guarded and a count would not see
    // it.
    const { container } = await bar();
    const named = regions(container).map((element) => element.className.split(" ")[0]);
    assert.deepEqual(named, ["topbar", "topbar-mark", "topbar-spacer"]);
  });

  test("no control inside the bar is a drag handle", async () => {
    // The other half, and the one a later edit is most likely to break: adding
    // the class to a button is a one-word change that turns a press into a drag.
    const { container } = await bar();
    for (const control of all(container, "button")) {
      assert.equal(
        control.classList.contains("app-drag-region"),
        false,
        `a button is a drag handle: ${control.getAttribute("aria-label") ?? control.className}`,
      );
    }
  });
});

// --- the mark ---------------------------------------------------------------
describe("the app's mark", () => {
  test("is the window's first element, in the top-left corner", async () => {
    // It used to be in the sidebar's head, and the sidebar is an overlay: the
    // mark is the window's, and a window's mark does not come and go with a
    // panel. Being the bar's *first* child is the assertion -- that is what
    // makes it the leftmost thing in the window.
    const { container } = await bar();
    const first = one(container, ".topbar")!.firstElementChild;

    assert.equal(first?.className.split(" ")[0], "topbar-mark");
    assert.ok(one(container, ".topbar-mark svg"), "the corner draws nothing");
  });

  test("is drawn rather than typed, and is not announced twice", async () => {
    // `AppMark` is `aria-hidden`, and this is the one place that could regress:
    // a wrapper carrying a label of its own would read the app's name out beside
    // the tab that already shows it.
    const { container } = await bar();
    const mark = one(container, ".topbar-mark")!;

    assert.equal(mark.textContent, "");
    assert.equal(mark.getAttribute("aria-label"), null);
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
    // The caption's own three, and not the strip's: `calls` carries the tab
    // callbacks too, and a caption button that reached one of those would be a
    // press landing on the wrong control.
    assert.deepEqual(
      {
        minimized: calls.minimized,
        toggled: calls.toggled,
        closed: calls.closed,
        menus: calls.menus,
      },
      { minimized: 1, toggled: 0, closed: 1, menus: 0 },
    );
    assert.deepEqual(calls.closedTabs, [], "a caption button closed a tab");
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
  test("the strip names the open chats, and marks the one you are in", async () => {
    const { container } = await bar({
      tabs: [
        tab({ id: "a", title: "First chat" }),
        tab({ id: "b", title: "Second chat" }),
      ],
      active: "b",
    });

    assert.deepEqual(texts(container, ".tab-title"), ["First chat", "Second chat"]);
    assert.equal(
      one(container, ".tab.is-active .tab-title")!.textContent,
      "Second chat",
      "the strip does not say which chat is showing",
    );
  });

  test("the busy spinner is still there", async () => {
    // The bar's original job, and the reason it is not only a caption: it is
    // the one place the window says whether it is working. A spinner removed
    // for being decorative is a turn that looks finished.
    const { container } = await bar({
      busy: true,
      tabs: [tab({ id: "a" }), tab({ id: "b" })],
      active: "b",
    });
    // On the tab you are in, and only that one: a spinner on a chat that is not
    // the one on screen says something is happening somewhere else.
    assert.equal(all(container, ".tab-spinner").length, 1);
    assert.ok(one(container, ".tab.is-active .tab-spinner"));
  });

  test("an empty strip has no fallback name, and still offers a way to start", async () => {
    // There is no "TONYAgent" tab. With nothing open the bar is the mark, the
    // strip's "+" and nothing else -- which is what a browser shows with no tabs
    // open at all.
    const { container } = await bar({ tabs: [] });
    assert.deepEqual(texts(container, ".tab-title"), []);
    assert.ok(one(container, ".tab-new"), "an empty strip has no way to open a chat");
  });
});

// --- the strip --------------------------------------------------------------
describe("the tab strip", () => {
  test("pressing a tab selects it, and its X closes it", async () => {
    const { container, calls } = await bar({
      tabs: [
        tab({ id: "a", title: "First chat" }),
        tab({ id: "b", title: "Second chat" }),
      ],
      active: "b",
    });

    await click(all(container, ".tab-open")[0]!);
    assert.deepEqual(calls.selected, ["a"]);

    await click(all(container, ".tab-close")[1]!);
    assert.deepEqual(calls.closedTabs, ["b"], "the X closed the wrong tab");
  });

  test("the + starts a new chat", async () => {
    const { container, calls } = await bar();
    await click(one(container, ".tab-new")!);
    assert.equal(calls.newTabs, 1);
  });

  test("the divider belongs to the tabs, so an empty strip draws none", async () => {
    // It divides the strip from the "+", and it is the strip that gives it a
    // left side. With no tabs open it was a single hairline floating in the bar
    // with nothing on either side of it -- which is what the window showed
    // before the first chat existed.
    const { container } = await bar({ tabs: [] });
    assert.equal(one(container, ".tabs-divider"), null, "a divider with nothing to divide");
    assert.ok(one(container, ".tab-new"), "the way to open a chat went with it");

    const { container: withTabs } = await bar();
    assert.ok(one(withTabs, ".tabs-divider"), "the divider is gone with tabs on screen");
  });

  test("the + is beside the strip, not inside it, so scrolling cannot hide it", async () => {
    // The strip scrolls once a tab would have to go below a readable width, and
    // a "+" at the end of scrolling content is exactly what a full strip hides
    // -- the control a user needs more the more tabs there are. A browser keeps
    // its own "+" outside the scrolling area for the same reason.
    const { container } = await bar();
    const strip = one(container, ".tabs")!;

    assert.equal(one(strip, ".tab-new"), null, "the + scrolls with the tabs");
    assert.equal(one(strip, ".tabs-divider"), null, "the divider scrolls with the tabs");
    assert.equal(
      one(container, ".tabs")!.nextElementSibling?.className.split(" ")[0],
      "tabs-divider",
      "nothing sits between the strip and the divider",
    );
  });

  test("every tab reserves the busy ring's slot, so the title never moves", async () => {
    // The ring used to be inserted into the tab only while busy, and the 12px
    // box plus its gap pushed the title 16px sideways the moment a turn began.
    // The slot is the fix: it is in every tab, occupied only by the open one.
    const { container } = await bar({
      busy: true,
      tabs: [tab({ id: "a" }), tab({ id: "b" })],
      active: "b",
    });

    assert.equal(all(container, ".tab-lead").length, 2, "a tab has no slot for the ring");
    assert.equal(all(container, ".tab-spinner").length, 1, "the ring is on more than the open tab");
    assert.ok(
      one(container, ".tab.is-active .tab-lead .tab-spinner"),
      "the ring is not in the open tab's own slot",
    );

    // And the slot is still there, and still empty, when nothing is running --
    // a slot that only existed while busy would move the title exactly as the
    // inserted ring did.
    const { container: idle } = await bar({ tabs: [tab({ id: "a" })] });
    assert.equal(all(idle, ".tab-lead").length, 1, "the idle tab lost its slot");
    assert.equal(all(idle, ".tab-spinner").length, 0, "an idle tab is drawing a ring");
  });

  test("a right-click offers Rename and Close tab, and not the page's menu", async () => {
    const { container } = await bar();
    const event = await contextMenu(one(container, ".tab")!);

    assert.equal(event.defaultPrevented, true, "the webview menu was not stopped");
    assert.deepEqual(texts(container, ".rowmenu [role='menuitem']"), [
      "Rename",
      "Close tab",
    ]);
  });

  test("Rename is refused on a chat with no messages", async () => {
    // Its name is a placeholder the core replaces with the first thing the user
    // says, and that replacement only fires while the name is still "New chat" --
    // so a name typed in here is a name the chat can never outgrow. The item
    // stays in the menu, where a user finds out that renaming exists at all.
    const { container } = await bar({ tabs: [tab({ renameable: false })] });
    await contextMenu(one(container, ".tab")!);

    const item = one(container, ".rowmenu [role='menuitem']") as HTMLButtonElement;
    assert.equal(item.disabled, true, "an empty chat can be renamed");
    assert.match(item.title, /no messages/, "it does not say why");
  });

  test("Rename opens an editor holding the current name", async () => {
    const { container } = await bar({ tabs: [tab({ title: "Old name" })] });
    await contextMenu(one(container, ".tab")!);
    await click(one(container, ".rowmenu [role='menuitem']")!);

    const input = one(container, ".tab-input") as HTMLInputElement | null;
    assert.ok(input, "Rename opened nothing to type into");
    assert.equal(input.value, "Old name", "the editor did not hold the current name");
  });

  test("Enter saves the typed name, and a blank one is refused", async () => {
    const { container, calls } = await bar({ tabs: [tab({ title: "Old name" })] });
    await contextMenu(one(container, ".tab")!);
    await click(one(container, ".rowmenu [role='menuitem']")!);
    const input = one(container, ".tab-input") as HTMLInputElement;

    await setValue(input, "New name");
    await press("Enter", input);
    assert.deepEqual(calls.renamed, [["c1", "New name"]]);

    // And a name of nothing. The core rejects one, so an editor that closed on it
    // would report a rename that did not happen.
    await contextMenu(one(container, ".tab")!);
    await click(one(container, ".rowmenu [role='menuitem']")!);
    await setValue(one(container, ".tab-input") as HTMLInputElement, "   ");
    await press("Enter", one(container, ".tab-input")!);
    assert.deepEqual(calls.renamed, [["c1", "New name"]]);
  });

  test("Escape keeps the old name", async () => {
    const { container, calls } = await bar({ tabs: [tab({ title: "Old name" })] });
    await contextMenu(one(container, ".tab")!);
    await click(one(container, ".rowmenu [role='menuitem']")!);
    const input = one(container, ".tab-input") as HTMLInputElement;

    await setValue(input, "Discarded");
    await press("Escape", input);
    assert.deepEqual(calls.renamed, []);
  });
});