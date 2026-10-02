/**
 * The window itself, rendered in jsdom over a fake core.
 *
 * Every other test in this directory tests a piece. This one tests the wiring
 * between them -- and that wiring is exactly what had no coverage at all until
 * `App` grew a `backend` prop, because `App.tsx` constructed `TauriBackend`
 * directly and therefore always spawned a real Python sidecar. So the untested
 * part was not a detail; it was all of the composition, and it was verified only
 * by driving the packaged app over CDP and reading the DOM afterwards.
 *
 * **The fake is a transport, not a backend.** `App` takes the concrete
 * `TauriBackend` and this test builds one over a `FakeTransport`, so the real
 * framing, request ids, reply routing and failure handling all run. Handing
 * `App` a plain object instead would have required declaring an interface that
 * restates the protocol, which is a second thing to keep in sync for no gain.
 *
 * **Replies are automatic.** `App` makes eight calls before it has drawn
 * anything; a test that had to answer each one by hand would be mostly
 * bookkeeping. `FakeCore` answers from a table and records what it was asked,
 * so a test asserts on the *calls* and never has to feed the plumbing.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { act } from "react";

import { App } from "./App.js";
import {
  TauriBackend,
  type CoreEvent,
  type CoreRequest,
  type EventType,
  type LineTransport,
} from "./backend.js";
import { click, one, render, texts, wait } from "./test-render.js";
import { exitDurationMs } from "./useDelayedUnmount.js";
import { dom } from "./test-dom.js";

const { window: domWindow } = dom;

/**
 * A core that answers.
 *
 * Replies arrive on the next tick rather than synchronously, because that is
 * what the real one does: `call()` writes and then waits, and a test whose fake
 * resolved inline would never exercise the await at all.
 */
class FakeTransport implements LineTransport {
  /** Every request the window sent, in order. */
  sent: CoreRequest[] = [];
  private stdout?: (text: string) => void;
  private stderr?: (text: string) => void;
  private exit?: () => void;
  killed = false;

  constructor(private readonly results: Record<string, unknown> = {}) {}

  async start(): Promise<void> {}

  async write(line: string): Promise<void> {
    const request = JSON.parse(line) as CoreRequest;
    this.sent.push(request);
    const result =
      request.method in this.results
        ? this.results[request.method]
        : { __unanswered: request.method };
    setTimeout(() => {
      this.stdout?.(
        JSON.stringify({ id: request.id, result }) + "\n",
      );
    }, 0);
  }

  onStdout(fn: (text: string) => void): void {
    this.stdout = fn;
  }
  onStderr(fn: (text: string) => void): void {
    this.stderr = fn;
  }
  onExit(fn: () => void): void {
    this.exit = fn;
  }
  async kill(): Promise<void> {
    this.killed = true;
    this.exit?.();
  }

  /** Push a core event, exactly as the sidecar would. */
  emit(event: CoreEvent): void {
    this.stdout?.(JSON.stringify(event) + "\n");
  }

  pushStderr(text: string): void {
    this.stderr?.(text);
  }

  /** Every method the window asked for, in order. */
  methods(): string[] {
    return this.sent.map((r) => r.method);
  }
}

/**
 * The startup handshake, answered.
 *
 * These eight are what `App` calls between mounting and having anything on
 * screen. Leaving one out does not fail loudly -- the window catches it, shows
 * the error banner, and carries on -- so a table that omits one silently turns
 * a wiring test into a "the banner appeared" test.
 */
const BOOT = {
  state: {
    provider: "openrouter",
    model: "stealth/space-bunny-alpha",
    base_url: "",
    bound: true,
    project: "",
    mode: "build",
    conversation: "",
  },
  "providers.list": {
    providers: [{ id: "openrouter", name: "OpenRouter", has_key: true }],
  },
  "conversations.list": { conversations: [] },
  "mode.list": {
    modes: [
      { name: "build", label: "Build", writes: true },
      { name: "plan", label: "Plan", writes: false },
    ],
    mode: "build",
  },
  "tools.get": { max_tool_calls: 10 },
  "reasoning.list": null,
};

const conversation = (over: Record<string, unknown> = {}) => ({
  id: "a".repeat(32),
  title: "Invoice questions",
  project: "",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
  message_count: 2,
  ...over,
});

/**
 * A pushed event, in the exact frame the sidecar writes.
 *
 * `event`, `seq` and `turn_id` are not decoration. `ingest` tells an event
 * frame from a reply frame by the first of them, so an event pushed without it
 * is read as a reply and routed nowhere. And `turn_id` is what the assistant
 * message is *keyed by* -- the reducer creates the placeholder on
 * `turn.started` under that id and looks the message up by it on every delta,
 * so a delta with the wrong one is appended to nothing and vanishes.
 */
function pushed(
  type: EventType,
  payload: Record<string, unknown>,
  turnId: string | null = null,
  seq = 1,
): CoreEvent {
  return { event: true, type, seq, turn_id: turnId, payload };
}

interface Mounted {
  container: HTMLElement;
  transport: FakeTransport;
  backend: TauriBackend;
  /** Every path the stubbed folder picker was asked for, in order. */
  picked: (string | null)[];
}

/**
 * Mount the window with the folder picker stubbed.
 *
 * The stub is the point. "New chat" asks for a folder when none is open, and
 * the real picker is a native dialog that cannot open in jsdom -- so without
 * this the one branch where a chat gets a project could only ever be verified
 * by driving the packaged app and watching a dialog appear. That is how the
 * project binding stayed broken for as long as it did: the reply was correct,
 * so nothing that checked the reply ever saw it.
 *
 * `answer` is what the user does: a path, or null for cancel. Both are
 * outcomes the window must handle, so both are reachable from a test.
 */
async function mountWithPicker(
  results: Record<string, unknown>,
  answer: (() => Promise<string | null>) | null,
): Promise<Mounted> {
  const transport = new FakeTransport({ ...BOOT, ...results });
  const backend = new TauriBackend(() => transport);
  const picked: (string | null)[] = [];
  const container = await render(
    <App backend={backend} pickProject={async () => {
      const next = answer ? await answer() : null;
      picked.push(next);
      return next;
    }} />,
  );

  for (let i = 0; i < 50; i++) {
    if (texts(container, ".statusbar").join(" ").includes("openrouter")) break;
    await wait(20);
  }
  await wait(80);
  return { container, transport, backend, picked };
}

/**
 * Mount the window and wait for it to finish booting.
 *
 * The wait is on something observable rather than a sleep: `App` clears its
 * busy state and paints the provider it read, so the status bar holding that
 * name is proof the whole startup path finished. A fixed sleep would be a race
 * that happens to pass on a fast machine and fail on a loaded one.
 */
async function mount(results: Record<string, unknown> = {}): Promise<Mounted> {
  const transport = new FakeTransport({ ...BOOT, ...results });
  const backend = new TauriBackend(() => transport);
  const container = await render(<App backend={backend} />);

  for (let i = 0; i < 50; i++) {
    if (texts(container, ".statusbar").join(" ").includes("openrouter")) break;
    await wait(20);
  }

  // Drain the rest of the handshake. The status bar appearing proves `state` was
  // read and painted, but `tools.get`, `reasoning.list` and the list re-read are
  // still in flight, and node:test awaits between tests -- so their replies can
  // land in the gap and update React outside `act`. The warning that produces
  // is attributed to whichever test happens to be running next, which is worse
  // than no warning at all: it trains you to ignore the line.
  await wait(80);

  return { container, transport, backend, picked: [] };
}

const panel = (c: HTMLElement) => one(c, ".chatlist");
const composerField = (c: HTMLElement) =>
  one(c, ".composer-inner textarea") as HTMLTextAreaElement | null;

/**
 * Deliver something the core pushed, inside `act`.
 *
 * `wait` is already act-wrapped, but it wraps the *timer*, not the delivery. A
 * frame arriving outside `act` schedules a React update that React flushes
 * late, and the assertion after it would be reading a component that has not
 * finished changing -- which is the failure mode the warning is about, so it is
 * worth honouring rather than scrolling past.
 */
async function push(work: () => void): Promise<void> {
  await act(async () => {
    work();
  });
}

describe("the window boots against a core", () => {
  test("it asks for the state it needs to draw itself", async () => {
    const { transport } = await mount();

    const methods = transport.methods();
    // `state` first, and alone at the front: it is the one that says whether a
    // provider is bound, and a window that asked anything else first would
    // flash "not configured" for a frame on every launch.
    assert.equal(methods[0], "state");

    // The rest is a *set*, not a sequence. `tools.get` and `reasoning.list`
    // belong to effects that start as soon as the window connects, so they
    // interleave with the boot sequence rather than following it -- measured,
    // they arrive before `conversations.list`. Asserting an order that does not
    // exist would make this test fail the first time an effect is added, and
    // for no benefit.
    for (const method of [
      "state",
      "providers.list",
      "conversations.list",
      "mode.list",
      "tools.get",
      "reasoning.list",
    ]) {
      assert.ok(methods.includes(method), `${method} was never asked for`);
    }
  });

  test("and paints what the core reported rather than a placeholder", async () => {
    const { container } = await mount();

    const status = texts(container, ".statusbar").join(" ");
    assert.match(status, /openrouter/, "the bound provider is not in the status bar");
    assert.match(status, /space-bunny-alpha/, "the bound model is not in the status bar");

    // No error banner. This is the assertion that would catch a boot call going
    // unanswered: `App` catches the rejection, shows the banner and keeps
    // running, so a broken handshake looks like a working window until you
    // read this far.
    assert.equal(one(container, ".banner"), null, "the window opened with an error on it");
  });

  test("a core that answers nothing is an error, not a silent window", async () => {
    // The negative of the same path, and the reason the table above is
    // exhaustive rather than aspirational.
    const { container } = await mount({ "providers.list": undefined } as never);

    assert.ok(
      one(container, ".banner"),
      "a boot call that was never answered left no visible sign",
    );
  });
});

describe("the sidebar, driven through the window", () => {
  test("picking a conversation closes the panel and hands over the caret", async () => {
    // This is the test that could not be written before `App` took a backend.
    // It is a composition: the rail's toggle mounts the panel, the panel's row
    // calls back into `App`, and `App` decides the panel closes and where the
    // focus goes. Every piece of that was verified by driving the packaged app
    // and reading the DOM afterwards, which catches a wrong answer but not a
    // regression.
    const { container, transport } = await mount({
      "conversations.list": { conversations: [conversation()] },
      "conversations.switch": { conversation: conversation(), messages: [] },
    });

    await click(one(container, ".rail-toggle")!);
    assert.ok(panel(container), "the panel did not open");

    const row = one(container, ".chatrow-open");
    assert.ok(row, "the conversation did not reach the panel");
    // Focused the way a keyboard user would have it, because that is the case
    // that breaks: the press lands on an element inside a panel that is about
    // to leave the document.
    row.focus();
    assert.equal(domWindow.document.activeElement, row);

    await click(row);
    assert.ok(transport.methods().includes("conversations.switch"), "the row did not switch");

    // Still mounted, already closing: an unmounted node has no box, so the
    // close would be a cut instead of an animation.
    assert.ok(panel(container), "the panel vanished instead of animating out");
    assert.equal(panel(container)!.dataset.state, "closed");

    await wait(exitDurationMs() + 60);
    assert.equal(panel(container), null, "the panel never left the document");

    // The point of the whole change. Without this, focus falls back to <body>
    // and the next Tab restarts from the top of the window.
    assert.equal(
      domWindow.document.activeElement,
      composerField(container),
      "focus did not land in the composer",
    );

    // Let the tail of the switch finish. `App` fires it as a voided promise
    // from the click handler, and its last step re-reads the conversation list
    // -- a second round trip that lands after the assertions above. Left to run
    // outside `act` it prints a warning that belongs to whichever test happens
    // to be running next, which is exactly the kind of noise that hides a real
    // one later.
    await wait(80);
  });

  test("New chat closes it too, for the same reason", async () => {
    const { container, transport } = await mount({
      // A project is open, so "New chat" files straight into it. The
      // folder-picking branch is the tests below; this one is about the panel
      // and the caret, which are the same either way.
      state: { ...BOOT.state, project: "C:/work/api" },
      "conversations.create": { conversation: conversation() },
    });

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-new")!);

    assert.ok(transport.methods().includes("conversations.create"));
    await wait(exitDurationMs() + 60);
    assert.equal(panel(container), null);
    assert.equal(domWindow.document.activeElement, composerField(container));
    await wait(80); // same trailing list re-read; see the note above
  });

  test("Escape closes it without opening anything", async () => {
    const { container, transport } = await mount();

    await click(one(container, ".rail-toggle")!);
    assert.ok(panel(container));

    await push(() =>
      domWindow.document.dispatchEvent(
        new domWindow.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
    );
    await wait(exitDurationMs() + 60);

    assert.equal(panel(container), null);
    // Escape is a dismissal, not a navigation: it must not have switched or
    // created a conversation on the way out.
    assert.ok(!transport.methods().includes("conversations.switch"));
    assert.ok(!transport.methods().includes("conversations.create"));
  });
});

describe("what the core pushes while the window is up", () => {
  test("a core event reaches the transcript", async () => {
    // The other half of the composition that only the packaged app could show:
    // the sidecar pushes, the window listens, the reducer runs, the DOM
    // changes. The reducer itself is tested elsewhere; what is untested
    // elsewhere is that the window is subscribed at all.
    const { container, transport } = await mount();

    await push(() => {
      transport.emit(pushed("turn.started", { model: "space-bunny-alpha" }, "t1"));
      transport.emit(pushed("message.delta", { text: "Hello from the core." }, "t1"));
    });
    await wait(60);

    assert.match(
      texts(container, ".transcript").join(" "),
      /Hello from the core\./,
      "a pushed event never reached the transcript",
    );
  });

  test("a core-side failure lands in the window's own log strip", async () => {
    // stderr is the only channel a core-side crash has. If it were dropped, a
    // sidecar that died on startup would present as a window that works.
    //
    // The strip is opened first because it is not rendered when closed -- which
    // is itself deliberate, the resting cost of a log nobody is reading. Testing
    // it closed would have passed against a window that dropped every line.
    const { container, transport } = await mount();
    await click(one(container, ".logbar-toggle")!);
    await push(() =>
      transport.pushStderr("Traceback: something went wrong in the core\n"),
    );
    await wait(60);
    const logs = texts(container, ".logstrip").join(" ");
    assert.match(logs, /something went wrong/, "the core's stderr was dropped");
  });
});

// --- where a new chat is filed ---------------------------------------------
describe("New chat files the conversation under a project", () => {
  const FOLDER = "D:/work/api";

  /** The `project` argument the window sent to `conversations.create`. */
  function createdWith(transport: FakeTransport): unknown {
    const request = transport.sent.find((r) => r.method === "conversations.create");
    return request?.params?.project;
  }

  test("with no project open it asks for a folder and files the chat there", async () => {
    // The case the user actually described: no folder chosen yet, so pick one
    // and put the chat inside it. Asserted on the *order* too -- binding the
    // folder before creating is what stops the chat being filed under whatever
    // was open before.
    const { container, transport, picked } = await mountWithPicker(
      {
        "sandbox.start": { running: true, project: FOLDER },
        "conversations.create": { conversation: conversation({ project: FOLDER }) },
      },
      async () => FOLDER,
    );

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-new")!);
    await wait(80);

    assert.deepEqual(picked, [FOLDER], "the folder picker was never opened");
    assert.ok(
      transport.methods().includes("sandbox.start"),
      "the picked folder was never bound, so the chat's tools would have nothing to act on",
    );
    assert.equal(createdWith(transport), FOLDER, "the chat was not filed under the picked folder");

    const order = transport
      .methods()
      .filter((m) => m === "sandbox.start" || m === "conversations.create");
    assert.deepEqual(
      order,
      ["sandbox.start", "conversations.create"],
      "the folder must be bound before the chat is created",
    );
  });

  test("with a project already open it asks nothing", async () => {
    // The second chat in a folder is the common case. A dialog in front of it
    // every time would make the common path the slow one.
    const { container, transport, picked } = await mountWithPicker(
      {
        state: { ...BOOT.state, project: FOLDER },
        "conversations.create": { conversation: conversation({ project: FOLDER }) },
      },
      async () => "S:/somewhere/else",
    );

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-new")!);
    await wait(80);

    assert.deepEqual(picked, [], "a project was open, so nothing should have been asked");
    assert.ok(!transport.methods().includes("sandbox.start"));
    assert.equal(createdWith(transport), FOLDER);
  });

  test("a cancelled picker creates nothing", async () => {
    // Cancelling is a normal outcome. An empty untitled conversation left
    // behind would make the button look like it had worked.
    const { container, transport, picked } = await mountWithPicker(
      { "conversations.create": { conversation: conversation() } },
      async () => null,
    );

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-new")!);
    await wait(80);

    assert.deepEqual(picked, [null], "the picker was not opened at all");
    assert.ok(
      !transport.methods().includes("conversations.create"),
      "a cancelled picker still left a conversation behind",
    );
  });

  test("a folder that will not start produces no conversation", async () => {
    // A chat filed under a project that failed to open is a row the user cannot
    // work in. No row is the better failure, and it is what this returns.
    const { container, transport } = await mountWithPicker(
      {
        "sandbox.start": { running: false },
        "conversations.create": { conversation: conversation() },
      },
      async () => FOLDER,
    );

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-new")!);
    await wait(80);

    assert.ok(
      !transport.methods().includes("conversations.create"),
      "a conversation was created under a folder that never opened",
    );
  });

  test("the list groups what the core reports, active project first", async () => {
    // The window passes the list through and lets the panel group it. This is
    // the check that the *project* reaches the panel at all -- `state.project`
    // is what decides which group is pinned to the top, and it arrives on a
    // different call from the list it orders.
    const { container } = await mountWithPicker(
      {
        state: { ...BOOT.state, project: "D:/work/api" },
        "conversations.list": {
          conversations: [
            conversation({ id: "a", title: "Alpha work", project: "C:/x/tony" }),
            conversation({ id: "b", title: "Endpoint notes", project: "D:/work/api" }),
          ],
        },
      },
      async () => null,
    );

    await click(one(container, ".rail-toggle")!);
    assert.deepEqual(texts(container, ".chatproj-name"), ["api", "tony"]);
  });
});
