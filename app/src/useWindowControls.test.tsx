/**
 * The window's keyboard surface, now that it draws its own title bar.
 *
 * `decorations: false` took more than three glyphs. It took the system menu --
 * Alt+Space by default, and the right-click on the caption -- and with it Move
 * and Size, which are drag loops the OS runs and no component can stand in for.
 * An undecorated window has a webview holding the focus, so the page is the
 * only thing that can hear a key at all, and if it does not act the window
 * cannot be placed or resized.
 *
 * **F10, and not Alt+Space.** Alt+Space is the name Windows gives this menu,
 * and on the machine this was built on it belongs to Copilot: the OS takes it
 * before any window sees it. A binding for it would be a line of code that can
 * never run, so there is a test asserting that Alt+Space is *left alone*.
 *
 * These tests run the hook against a fake host, because the honest assertion is
 * not "the handler fired" but "the thing the host was asked to do was named":
 * `system_menu` is a method on the bridge, a name in `bridge.py`, and a Win32
 * call in `win32.py`, and a typo in any of them is a menu that never opens with
 * the reason only in a console. That it reaches the window at all is
 * `scripts/verify_window.py`'s job: the host, the handle and the OS's own menu are all
 * facts about the running process.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { dom } from "./test-dom.js";
import { act } from "react";
import { mouseDown, render, press, wait } from "./test-render.js";
import {
  DRAG_REGION_CLASS,
  edgeAt,
  useWindowControls,
} from "./useWindowControls.js";

const { window } = dom;

// The bridge is a global the host installs, so there is nothing to import and
// nothing to put in the module registry. What matters instead is that the api
// object is in place *before* the render, which is what makes `whenHostReady`
// resolve without waiting for its timeout.
//
// There used to be two real `import()`s here for the same reason, back when the
// hook reached Tauri through the module system. The host is reached through one
// global now, so the whole dance is gone.

/**
 * Every window action the hook asked the host for, in order.
 *
 * A resize carries its edge, because "resize" alone cannot tell a press that
 * asked for the left edge from one that asked for a corner -- and the edge is
 * the whole answer the page has to give.
 */
let actions: string[] = [];

/** What the window says about itself, so a test can decide. */
let maximized = false;

/**
 * Stand in for the window host.
 *
 * `window.pywebview.api` is the entire surface the hook can reach, so recording
 * the action names here records exactly what the host would have been asked to
 * do. `window_control` answers with the state *after* the action, which is the
 * contract the hook relies on to keep the caption in step.
 */
function insideHost(options: { maximized?: boolean } = {}): void {
  actions = [];
  maximized = options.maximized ?? false;
  (window as unknown as Record<string, unknown>).pywebview = {
    api: {
      window_control: (action: string, edge?: string) => {
        actions.push(edge ? `${action}:${edge}` : action);
        if (action === "toggleMaximize") maximized = !maximized;
        return Promise.resolve({ maximized });
      },
      window_state: () => Promise.resolve({ maximized }),
      system_menu: () => {
        actions.push("system_menu");
        return Promise.resolve({ maximized });
      },
    },
  };
}

function menuWasAskedFor(): boolean {
  return actions.includes("system_menu");
}

/** Let the bridge's promise and the state update behind it land. */
async function settled(): Promise<void> {
  await wait(0);
}

function Probe() {
  const controls = useWindowControls();
  return (
    <span>
      {controls ? (controls.maximized ? "maximized" : "normal") : "no-window"}
      {/* The two things the hook presses on: a title-bar region, and a control
          inside it that must keep the press for itself. Empty, so the text the
          tests above assert on is unchanged. */}
      <i className={DRAG_REGION_CLASS} />
      <button type="button" />
    </span>
  );
}

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).pywebview;
});

// --- F10 --------------------------------------------------------------------
describe("the window's system menu shortcut", () => {
  test("F10 asks for the system menu", async () => {
    insideHost();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10" });
    await settled();
    assert.ok(
      menuWasAskedFor(),
      `nothing was invoked; got ${JSON.stringify(actions)}`,
    );
  });

  test("Alt+Space is somebody else's", async () => {
    // On this machine it is Copilot's: the OS consumes it before a window ever
    // sees it, so the page never gets the key and a binding here would be a
    // line of code that cannot run. Asserting it stays unbound is how a later
    // reader finds out *why* F10 is the one bound.
    insideHost();
    await render(<Probe />);
    await press(" ", undefined, { code: "Space", altKey: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("Shift+F10 is the context-menu key, not this", async () => {
    // It is the keyboard's way of saying "right-click here", and it belongs to
    // whatever is under the caret -- the transcript, the composer, a message.
    // The window's frame is not what the user is pointing at.
    insideHost();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10", shiftKey: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("no other modifier rides along", async () => {
    // Ctrl+F10, Alt+F10 and Win+F10 are other people's. A shortcut that fires
    // for all of them is a shortcut that fires while the user is doing something
    // else, which is worse than one that does not exist.
    insideHost();
    await render(<Probe />);
    for (const modifier of ["ctrlKey", "altKey", "metaKey"] as const) {
      await press("F10", undefined, { code: "F10", [modifier]: true });
    }
    await settled();
    assert.equal(
      menuWasAskedFor(),
      false,
      `a near-miss opened the menu; invoked ${JSON.stringify(actions)}`,
    );
  });

  test("holding the key down does not open it over and over", async () => {
    // The key repeat arrives as the same keydown with `repeat` set, and each one
    // asks the OS for a menu while the last one is still on screen.
    insideHost();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10", repeat: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("F10 does not reach the composer as text", async () => {
    // The default is suppressed, and that is the half of this that is easy to
    // leave out: with the caret in the composer, an unhandled F10 is the
    // webview's problem, and the user gets a keypress that does nothing.
    insideHost();
    await render(<Probe />);
    const event = await press("F10", undefined, { code: "F10" });
    assert.equal(event.defaultPrevented, true, "the key was left to the page");
  });

  test("a function key that is not this one is left alone", async () => {
    // F11 is full screen and F12 is the devtools, and both are the browser's.
    insideHost();
    await render(<Probe />);
    const event = await press("F11", undefined, { code: "F11" });
    await settled();
    assert.equal(menuWasAskedFor(), false);
    assert.equal(event.defaultPrevented, false);
  });
});

// --- the window's own gestures ----------------------------------------------
describe("the window's edges and its title bar", () => {
  test("an edge is decided by position, and a corner before either side", () => {
    // A pure function, so the arithmetic is pinned without a window to measure.
    // The corners are the cases that matter: a press equally close to two edges
    // is a corner press, and a host told "left" would resize the wrong way.
    assert.equal(edgeAt(1, 400, 1000, 800), "left");
    assert.equal(edgeAt(999, 400, 1000, 800), "right");
    assert.equal(edgeAt(500, 1, 1000, 800), "top");
    assert.equal(edgeAt(500, 799, 1000, 800), "bottom");
    assert.equal(edgeAt(1, 1, 1000, 800), "top-left");
    assert.equal(edgeAt(999, 1, 1000, 800), "top-right");
    assert.equal(edgeAt(1, 799, 1000, 800), "bottom-left");
    assert.equal(edgeAt(999, 799, 1000, 800), "bottom-right");
    // The eighth pixel in is inside the window; the seventh is on its edge.
    assert.equal(edgeAt(7, 400, 1000, 800), "left");
    assert.equal(edgeAt(8, 400, 1000, 800), null);
    assert.equal(edgeAt(500, 400, 1000, 800), null);
  });

  test("a press on the title bar asks for the OS's move loop", async () => {
    // Not "the window moved". What the page can do is *name* the gesture, and
    // the name is what the host hands to Windows -- so a rename here is a title
    // bar that does nothing, with the reason only in a console.
    insideHost();
    const container = await render(<Probe />);
    const region = container.querySelector(`.${DRAG_REGION_CLASS}`)!;
    const event = await mouseDown(region, { clientX: 400, clientY: 20 });
    await settled();
    assert.deepEqual(actions, ["drag"], `asked for ${JSON.stringify(actions)}`);
    assert.equal(event.defaultPrevented, true, "the press was left to the page");
  });

  test("a press on a control in the bar is the control's", async () => {
    // The class is on the bar and on its empty regions and never on a control:
    // a press that started a window drag is a press the model picker never hears.
    insideHost();
    const container = await render(<Probe />);
    await mouseDown(container.querySelector("button")!, { clientX: 400, clientY: 20 });
    await settled();
    assert.deepEqual(actions, []);
  });

  test("a press near an edge resizes, even on the title bar", async () => {
    // The frame is the frame's before it is the caption's, which is what makes
    // the top few pixels of a title bar resize rather than drag.
    insideHost();
    const container = await render(<Probe />);
    const region = container.querySelector(`.${DRAG_REGION_CLASS}`)!;
    await mouseDown(region, { clientX: 2, clientY: 300 });
    await mouseDown(region, {
      clientX: window.innerWidth - 2,
      clientY: window.innerHeight - 2,
    });
    await settled();
    assert.deepEqual(actions, ["resize:left", "resize:bottom-right"]);
  });

  test("the second press of a double-click maximizes", async () => {
    // What a title bar does everywhere else. The first press has already asked
    // for a move and the OS ends it on the mouse-up, so the maximize lands on
    // top of a window that has been put back where it was.
    insideHost();
    const container = await render(<Probe />);
    await mouseDown(container.querySelector(`.${DRAG_REGION_CLASS}`)!, {
      clientX: 400,
      clientY: 20,
      detail: 2,
    });
    await settled();
    assert.deepEqual(actions, ["toggleMaximize"]);
  });

  test("the cursor names the edge under the pointer", async () => {
    // The window draws no frame, so the cursor is the only thing that says the
    // edge is there at all.
    insideHost();
    await render(<Probe />);
    const move = async (clientX: number) => {
      await act(async () => {
        window.dispatchEvent(
          new window.MouseEvent("mousemove", { bubbles: true, clientX, clientY: 300 }),
        );
      });
    };
    await move(2);
    assert.equal(window.document.documentElement.style.cursor, "ew-resize");
    await move(400);
    assert.equal(window.document.documentElement.style.cursor, "");
  });
});

// --- outside the host -------------------------------------------------------
describe("outside the window host", () => {
  test("there is no window, and no shortcut bound to nothing", async () => {
    // `useWindowControls` reports null rather than a set of no-ops, so there is
    // no caption to draw. Binding a shortcut here would call into a host that is
    // not there; the guard is the api object, the same thing that hides the bar.
    actions = [];
    const container = await render(<Probe />);
    assert.match(container.textContent ?? "", /no-window/);
    await press("F10", undefined, { code: "F10" });
    await settled();
    assert.deepEqual(actions, []);
  });

  test("the caption waits for the host to announce itself", async () => {
    // The bridge is injected *after* the page loads, so there is a real moment
    // in which the window exists and has not said so yet. Drawing the caption
    // then would be three buttons that look like they work and do not -- the
    // same failure as a browser preview, and the reason both report null.
    const container = await render(<Probe />);
    assert.match(container.textContent ?? "", /no-window/);

    insideHost();
    await act(async () => {
      window.dispatchEvent(new window.Event("pywebviewready"));
    });
    assert.match(container.textContent ?? "", /normal/);
  });
});
