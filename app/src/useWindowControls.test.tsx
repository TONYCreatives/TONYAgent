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
 * These tests run the hook against a fake `__TAURI_INTERNALS__`, because the
 * honest assertion is not "the handler fired" but "the command the Rust side
 * registered was named": `show_system_menu` is a name in `lib.rs`, a name in
 * `build.rs` and a name in `capabilities/default.json`, and a typo in any of
 * them is a menu that never opens and a reason that lives only in a console.
 * That it reaches the window at all is `scripts/verify_system_menu.py`'s job:
 * the ACL, the compiled command and the OS's own menu are all facts about the
 * shipped binary.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { dom } from "./test-dom.js";
import { render, press, wait } from "./test-render.js";
import { useWindowControls } from "./useWindowControls.js";

const { window } = dom;

// The hook loads both of these through `import()` so that no component test
// needs Tauri installed. Here they are loaded for real, at the top of the file,
// which puts them in the module registry: the hook's own `import()` is then one
// microtask rather than a file read, so `wait(0)` afterwards is enough for the
// command to have arrived. Without that, a test asserting "nothing happened"
// would be asserting it before the code had been given a chance to.
await import("@tauri-apps/api/core");
await import("@tauri-apps/api/window");

/** Every command name the hook asked the shell to run, in order. */
let commands: string[] = [];

/**
 * Stand in for the Tauri shell.
 *
 * `invoke` is the whole of `@tauri-apps/api/core`'s `invoke` -- it forwards to
 * `__TAURI_INTERNALS__.invoke` -- so recording the names here records exactly
 * what the Rust side would have been asked. `transformCallback` is what
 * `listen` goes through for the resize handler the hook follows.
 */
function insideTauri(): void {
  let nextCallback = 1;
  commands = [];
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {
    invoke: (cmd: string) => {
      commands.push(cmd);
      return Promise.resolve(true);
    },
    transformCallback: () => nextCallback++,
  };
}

function menuWasAskedFor(): boolean {
  return commands.includes("show_system_menu");
}

/** Let the hook's lazy import and the call behind it land. */
async function settled(): Promise<void> {
  await wait(0);
}

function Probe() {
  const controls = useWindowControls();
  return <span>{controls ? (controls.maximized ? "maximized" : "normal") : "no-window"}</span>;
}

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

// --- F10 --------------------------------------------------------------------
describe("the window's system menu shortcut", () => {
  test("F10 asks for the system menu", async () => {
    insideTauri();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10" });
    await settled();
    assert.ok(
      menuWasAskedFor(),
      `nothing was invoked; got ${JSON.stringify(commands)}`,
    );
  });

  test("Alt+Space is somebody else's", async () => {
    // On this machine it is Copilot's: the OS consumes it before a window ever
    // sees it, so the page never gets the key and a binding here would be a
    // line of code that cannot run. Asserting it stays unbound is how a later
    // reader finds out *why* F10 is the one bound.
    insideTauri();
    await render(<Probe />);
    await press(" ", undefined, { code: "Space", altKey: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("Shift+F10 is the context-menu key, not this", async () => {
    // It is the keyboard's way of saying "right-click here", and it belongs to
    // whatever is under the caret -- the transcript, the composer, a message.
    // The window's frame is not what the user is pointing at.
    insideTauri();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10", shiftKey: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("no other modifier rides along", async () => {
    // Ctrl+F10, Alt+F10 and Win+F10 are other people's. A shortcut that fires
    // for all of them is a shortcut that fires while the user is doing something
    // else, which is worse than one that does not exist.
    insideTauri();
    await render(<Probe />);
    for (const modifier of ["ctrlKey", "altKey", "metaKey"] as const) {
      await press("F10", undefined, { code: "F10", [modifier]: true });
    }
    await settled();
    assert.equal(
      menuWasAskedFor(),
      false,
      `a near-miss opened the menu; invoked ${JSON.stringify(commands)}`,
    );
  });

  test("holding the key down does not open it over and over", async () => {
    // The key repeat arrives as the same keydown with `repeat` set, and each one
    // asks the OS for a menu while the last one is still on screen.
    insideTauri();
    await render(<Probe />);
    await press("F10", undefined, { code: "F10", repeat: true });
    await settled();
    assert.equal(menuWasAskedFor(), false);
  });

  test("F10 does not reach the composer as text", async () => {
    // The default is suppressed, and that is the half of this that is easy to
    // leave out: with the caret in the composer, an unhandled F10 is the
    // webview's problem, and the user gets a keypress that does nothing.
    insideTauri();
    await render(<Probe />);
    const event = await press("F10", undefined, { code: "F10" });
    assert.equal(event.defaultPrevented, true, "the key was left to the page");
  });

  test("a function key that is not this one is left alone", async () => {
    // F11 is full screen and F12 is the devtools, and both are the browser's.
    insideTauri();
    await render(<Probe />);
    const event = await press("F11", undefined, { code: "F11" });
    await settled();
    assert.equal(menuWasAskedFor(), false);
    assert.equal(event.defaultPrevented, false);
  });
});

// --- outside the shell ------------------------------------------------------
describe("outside the Tauri shell", () => {
  test("there is no window, and no shortcut bound to nothing", async () => {
    // `useWindowControls` reports null rather than a set of no-ops, so there is
    // no caption to draw. Binding a shortcut here would call into a shell that
    // is not there; the guard is `inTauri()`, the same one that hides the bar.
    commands = [];
    const container = await render(<Probe />);
    assert.match(container.textContent ?? "", /no-window/);
    await press("F10", undefined, { code: "F10" });
    await settled();
    assert.deepEqual(commands, []);
  });
});
