/**
 * The window itself, rendered in jsdom over a fake core.
 *
 * Every other test in this directory tests a piece. This one tests the wiring
 * between them -- and that wiring is exactly what had no coverage at all until
 * `App` grew a `backend` prop, because `App.tsx` constructed `CoreBackend`
 * directly and therefore always spawned a real Python sidecar. So the untested
 * part was not a detail; it was all of the composition, and it was verified only
 * by driving the packaged app over CDP and reading the DOM afterwards.
 *
 * **The fake is a transport, not a backend.** `App` takes the concrete
 * `CoreBackend` and this test builds one over a `FakeTransport`, so the real
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
  CoreBackend,
  type CoreEvent,
  type CoreRequest,
  type EventType,
  type LineTransport,
} from "./backend.js";
import {
  all,
  click,
  contextMenu,
  one,
  render,
  setValue,
  texts,
  wait,
} from "./test-render.js";
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
  // No dial: the Thinking menu is absent for a model that reports none, which is
  // the default every other test here runs against. The one test that wants it
  // passes its own `reasoning.list`.
  "reasoning.list": null,
  // The ladder the menu draws. Answered from boot so the control exists: one
  // that depends on a boot call nobody answers renders blank for a frame on
  // every launch, and is untestable besides.
  "permission.list": {
    permission: "medium",
    permissions: [
      {
        name: "low",
        label: "Low",
        description: "Read, search and browse.",
        runs_commands: false,
        skips_confirmation: false,
        runs_any_command: false,
      },
      {
        name: "medium",
        label: "Medium",
        description: "Edit files. Shell commands are refused.",
        runs_commands: false,
        skips_confirmation: false,
        runs_any_command: false,
      },
      {
        name: "high",
        label: "High",
        description: "Everything, including running commands.",
        runs_commands: true,
        skips_confirmation: false,
        runs_any_command: false,
      },
      {
        name: "full",
        label: "Full",
        description: "Everything, without asking, and any command.",
        runs_commands: true,
        skips_confirmation: true,
        runs_any_command: true,
        // The one level the core runs on the host. Present here so a test that
        // reads the menu sees the same ladder the core sends, not one where
        // the flag happens to be missing everywhere.
        runs_on_host: true,
      },
    ],
  },
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
  backend: CoreBackend;
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
  const backend = new CoreBackend(() => transport);
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
  const backend = new CoreBackend(() => transport);
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
    await click(one(container, ".statusbar-logs")!);
    await push(() =>
      transport.pushStderr("Traceback: something went wrong in the core\n"),
    );
    await wait(60);
    const logs = texts(container, ".logstrip").join(" ");
    assert.match(logs, /something went wrong/, "the core's stderr was dropped");
  });
});

// --- where a new chat is filed ---------------------------------------------
describe("the folder button in the middle of a new chat", () => {
  const FOLDER = "D:/work/api";

  test("it is on the panel and it says which folder is in force", async () => {
    // The whole point of putting it there: a new chat is about a folder, and
    // the panel used to say nothing about which one. Read off the live DOM
    // rather than the component, so what is checked is what was rendered.
    const { container } = await mountWithPicker({ state: { ...BOOT.state, project: FOLDER } }, null);

    const name = one(container, ".empty-folder-name");
    assert.ok(name, "the empty chat has no folder line");
    assert.equal(name?.textContent, "api");
    assert.equal(name?.getAttribute("title"), FOLDER);
    assert.equal(one(container, ".empty-folder button")?.textContent, "Change...");
  });

  test("pressing it opens the picker and binds what comes back", async () => {
    // The wiring `MessageList`'s own test cannot see: that the callback on the
    // panel is the one App hands it, and that App's one reaches the native
    // dialog. The stub stands in for the dialog, exactly as it does for "New
    // chat" -- and `sandbox.start` is what makes the pick real rather than
    // cosmetic, so it is asserted rather than assumed.
    const { container, transport, picked } = await mountWithPicker(
      { "sandbox.start": { running: true, project: FOLDER } },
      async () => FOLDER,
    );

    await click(one(container, ".empty-folder button")!);
    await wait(80);

    assert.deepEqual(picked, [FOLDER], "the centred button never reached the folder picker");
    assert.ok(
      transport.methods().includes("sandbox.start"),
      "the folder was picked but never bound to the sandbox",
    );
  });

  test("cancelling the picker changes nothing", async () => {
    // A cancel is a normal outcome and must not be reported as an error, and it
    // must not clear the folder that was already in force -- which is the whole
    // of "leave it alone and keep the one you had".
    const { container, transport, picked } = await mountWithPicker(
      { state: { ...BOOT.state, project: FOLDER } },
      async () => null,
    );

    await click(one(container, ".empty-folder button")!);
    await wait(80);

    assert.deepEqual(picked, [null], "the picker was not opened, or opened twice");
    assert.ok(
      !transport.methods().includes("sandbox.start"),
      "a cancelled pick bound a folder anyway",
    );
    assert.equal(
      one(container, ".empty-folder-name")?.textContent,
      "api",
      "a cancelled pick cleared the folder that was already chosen",
    );
  });
});

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

  test("the list shows the folder the window is working in, and no other", async () => {
    // The window passes the list through and lets the panel scope it. This is
    // the check that the *project* reaches the panel at all -- `state.project`
    // is what decides which rows are drawn, and it arrives on a different call
    // from the list it filters.
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
    assert.deepEqual(texts(container, ".chatrow-title"), ["Endpoint notes"]);
    assert.deepEqual(texts(container, ".chatlist-folder-name"), ["api"]);
  });

  test("changing the folder takes the open chat with it", async () => {
    // The whole feature in one flow: the folder is bound, and the chat you were
    // looking at is filed under it. The order matters -- a move sent before the
    // folder is bound would file the chat under the folder the pick never
    // reached, which is the disagreement `_bind_project` exists to prevent.
    const OPEN = "open-chat";
    const { container, transport } = await mountWithPicker(
      {
        state: { ...BOOT.state, project: "C:/x/tony", conversation: OPEN },
        "conversations.list": {
          conversations: [
            conversation({ id: OPEN, title: "Alpha work", project: "C:/x/tony" }),
          ],
        },
        "sandbox.start": { running: true, project: "D:/work/api" },
        "conversations.move": { conversation: conversation({ id: OPEN }) },
      },
      async () => "D:/work/api",
    );

    await click(one(container, ".rail-toggle")!);
    await click(one(container, ".chatlist-folder")!);
    await wait(80);

    const move = transport.sent.find((r) => r.method === "conversations.move");
    assert.ok(move, "the folder changed and the chat was left behind");
    assert.equal(move?.params?.id, OPEN);
    assert.equal(move?.params?.project, "D:/work/api");

    const order = transport
      .methods()
      .filter((m) => m === "sandbox.start" || m === "conversations.move");
    assert.deepEqual(order, ["sandbox.start", "conversations.move"]);
  });
});

// --- the tab names the conversation you are reading ------------------------
describe("the tab in the title bar", () => {
  const OPEN = "open-chat";

  test("deleting the open chat moves the window on to a fresh one", async () => {
    // Reported from the running app: delete the open chat, land on the empty
    // state, and the bar goes on naming a conversation that no longer exists.
    //
    // The cause was not the title. The window was left on *no* conversation --
    // `conversation` = "" -- and the tab reads its title out of the list by that
    // id, so it had nothing to name. The core's own delete handler says the
    // window "is moved on to a fresh one"; this is that, and it is why the tab
    // ends up naming the new chat rather than the deleted one.
    const FRESH = "fresh-chat";
    const { container, transport } = await mount({
      state: { ...BOOT.state, conversation: OPEN },
      "conversations.list": {
        conversations: [
          conversation({ id: OPEN, title: "Doomed chat" }),
          conversation({ id: FRESH, title: "New chat" }),
        ],
      },
      "conversations.delete": { id: OPEN, deleted: true },
      "conversations.create": {
        conversation: conversation({ id: FRESH, title: "New chat" }),
      },
    });

    assert.equal(one(container, ".tab-title")!.textContent, "Doomed chat");

    await click(one(container, ".rail-toggle")!);
    await contextMenu(one(container, ".chatrow")!);
    const item = all(document.body, ".rowmenu [role='menuitem']").find(
      (n) => n.textContent === "Delete",
    );
    assert.ok(item, "the row menu has no Delete in it");
    await click(item);
    await wait(80);

    assert.ok(
      transport.methods().includes("conversations.create"),
      "the deleted chat left the window with no conversation at all",
    );
    assert.equal(
      one(container, ".tab-title")!.textContent,
      "New chat",
      "the bar is still naming the conversation that was deleted",
    );
  });

  test("and a chat that is only being browsed does not move anything", async () => {
    // The other half, and the reason this cannot be "start a chat on any
    // delete": deleting a row you are not looking at must leave you where you
    // are, and must not add a conversation nobody asked for.
    const OTHER = "other-chat";
    const { container, transport } = await mount({
      state: { ...BOOT.state, conversation: OPEN },
      "conversations.list": {
        conversations: [
          conversation({ id: OPEN, title: "What I am reading" }),
          conversation({ id: OTHER, title: "Something else" }),
        ],
      },
      "conversations.delete": { id: OTHER, deleted: true },
    });

    await click(one(container, ".rail-toggle")!);
    await contextMenu(all(container, ".chatrow")[1]!);
    const item = all(document.body, ".rowmenu [role='menuitem']").find(
      (n) => n.textContent === "Delete",
    )!;
    await click(item);
    await wait(80);

    assert.ok(
      !transport.methods().includes("conversations.create"),
      "deleting somebody else's row started a chat",
    );
    assert.equal(one(container, ".tab-title")!.textContent, "What I am reading");
  });
});

// --- the permission menu, driven through the window ------------------------
describe("the permission menu reflects the core", () => {
  const steps = (c: HTMLElement) =>
    all(c, ".permchoice-step").map((e) => e.classList.contains("is-on"));

  /**
   * Open Settings, and wait for the panel to be on screen.
   *
   * The panel is behind an `Overlay`, which only mounts its children while it
   * is animating in, so a click on the rail button and an immediate lookup race
   * the mount. Polling for the modal rather than a fixed sleep keeps the test
   * honest about what it is waiting for.
   */
  const openSettings = async (c: HTMLElement) => {
    await click(one(c, '.rail-btn[aria-label="Settings"]')!);
    for (let i = 0; i < 50 && !one(c, ".modal"); i++) await wait(20);
  };

  test("Escape closes the sidebar, which is where settings now lives", async () => {
    // Settings is a pane of the sidebar rather than a page over the window, so
    // Escape has one thing to put away and one place to go: the sidebar closes
    // and returns to the chats pane on the way out.
    //
    // The press also has to be *claimed* by a menu first: the permission ladder
    // is a menu inside this pane, it answers Escape itself, and if the sidebar
    // answered it too then closing a menu would take the whole sidebar down
    // behind it. `useDismiss` claims the key in the capture phase, which is what
    // makes that order possible.
    const { container } = await mount();
    await openSettings(container);
    assert.ok(one(container, ".modal"), "the settings pane did not open");
    assert.ok(
      one(container, '.chatlist[data-pane="settings"]'),
      "the sidebar did not switch to the settings pane",
    );

    await push(() =>
      domWindow.document.dispatchEvent(
        new domWindow.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
    );
    await wait(exitDurationMs() + 60);
    assert.equal(
      one(container, ".modal"),
      null,
      "Escape left the settings pane on screen",
    );
  });

  test("it draws the level the core reported, not a local default", async () => {
    // `state` is what a reloaded window reads, so it is the level that has to
    // be right. A menu seeded with its own default would agree with the core
    // today and disagree the first time anything changed it elsewhere.
    const { container, transport } = await mount({
      state: { ...BOOT.state, permission: "high" },
      "permission.list": {
        permission: "high",
        permissions: BOOT["permission.list"].permissions,
      },
    });

    assert.ok(
      transport.methods().includes("permission.list"),
      "the ladder was never read from the core",
    );
    // Nothing about the menu may exist before Settings is opened. That is the
    // point of the move: a control in the composer was on screen at all times,
    // and this asserts the panel is the only place it lives.
    assert.equal(
      one(container, ".permchoice"),
      null,
      "the permission menu is on screen without the settings panel open",
    );

    await openSettings(container);
    assert.deepEqual(texts(container, ".permchoice-value"), ["High"]);
    assert.deepEqual(steps(container), [true, true, true, false]);
  });

  test("choosing a level asks the core, which decides what is really in force", async () => {
    const { container, transport } = await mount({
      "permission.set": { permission: "full" },
    });

    await openSettings(container);
    await click(one(container, ".permchoice-trigger")!);
    await click(all(container, ".permchoice-item")[3]);
    await wait(80);

    const request = transport.sent.find((r) => r.method === "permission.set");
    assert.equal(request?.params?.permission, "full");
    assert.deepEqual(texts(container, ".permchoice-value"), ["Full"]);
    assert.deepEqual(steps(container), [true, true, true, true]);
  });

  test("a level the core resolved differently is corrected", async () => {
    // An unrecognised name falls back to the core's default. A menu that echoed
    // the request back would be labelling a level the orchestrator is not
    // enforcing, which is the one thing this control must never do.
    const { container } = await mount({
      "permission.set": { permission: "low" },
    });

    await openSettings(container);
    await click(one(container, ".permchoice-trigger")!);
    await click(all(container, ".permchoice-item")[3]);
    await wait(80);

    assert.deepEqual(
      texts(container, ".permchoice-value"),
      ["Low"],
      "the menu kept showing a level the core had resolved away",
    );
    assert.deepEqual(steps(container), [true, false, false, false]);
  });

  test("it is disabled while a turn is in flight", async () => {
    // Changing the ceiling under a half-built answer is how a turn comes back
    // obeying a rule that moved after it started.
    //
    // Driven by the core's own `turn.started` rather than by pressing send: the
    // fake's `send` answer carries no `turn_id`, so a click would leave the
    // window in `busy` only by accident, and a test that asserted on that would
    // be asserting on the fake's shape.
    const { container, transport } = await mount();
    await openSettings(container);
    const trigger = one(container, ".permchoice-trigger") as HTMLButtonElement;
    assert.equal(trigger.disabled, false, "the menu starts enabled");

    await push(() => {
      transport.emit(pushed("turn.started", { model: "m" }, "t9"));
    });
    await wait(60);

    assert.equal(
      (one(container, ".permchoice-trigger") as HTMLButtonElement).disabled,
      true,
      "the permission could be changed while a turn was running",
    );
  });

  test("the thinking effort is in the same panel, and nowhere else", async () => {
    // Both controls answer "how much may this window do without asking", and
    // they used to be a bar above the composer and a native select in its
    // control row. Asserted together because the thing being protected is that
    // they are side by side in one place: a Thinking menu that stayed in the
    // composer would pass a test that only looked for it in Settings.
    //
    // Its own `reasoning.list`, because the boot fixture reports no dial --
    // which is the case where the menu must be absent, so a test asserting the
    // menu is there has to hand it a model that has one.
    const { container } = await mount({
      "reasoning.list": {
        supported: true,
        efforts: ["low", "high"],
        default_effort: "high",
        mandatory: false,
        effort: "high",
      },
    });
    assert.equal(
      one(container, ".composer-row select"),
      null,
      "the composer still has a platform control in it",
    );

    await openSettings(container);
    assert.deepEqual(texts(container, ".permchoice-label"), [
      "Permission",
      "Thinking",
    ]);
  });

  test("and a model with no dial gets no thinking menu beside the permission one", async () => {
    // The two negatives, because showing a dial that cannot change anything
    // teaches the reader that the row is decoration.
    const { container } = await mount();
    await openSettings(container);
    assert.deepEqual(
      texts(container, ".permchoice-label"),
      ["Permission"],
      "a menu appeared for a model that reports no efforts",
    );
  });
});


// --- starting the sandbox from the panel ------------------------------------
describe("the sandbox has a Start button", () => {
  const FOLDER = "D:/work/api";

  /**
   * Open Settings, and wait for the panel to be on screen.
   * is a helper that has to keep working for both of them.
   *
   * The folder controls live behind the panel's Project tab now, so opening
   * Settings is not enough to see them: choosing the tab is part of opening
   * this group, and doing it here keeps the four tests about the sandbox.
   */
  const openSettings = async (c: HTMLElement) => {
    await click(one(c, '.rail-btn[aria-label="Settings"]')!);
    for (let i = 0; i < 50 && !one(c, ".modal"); i++) await wait(20);
    await click(
      all(c, ".settings-tab").find((b) => (b.textContent ?? "").trim() === "Project")!,
    );
  };
  /**
   * The buttons of the Project folder group, as labels.
   *
   * Found by the group's own heading rather than by `.settings-row`, which is
   * not unique: the Model and API key groups use the same class, and a selector
   * loose enough to match all three would report Apply and Save key as if they
   * were sandbox controls.
   */
  const projectButtons = (c: HTMLElement): string[] => {
    const group = all(c, ".settings-group").find(
      (g) => one(g, "h3")?.textContent?.trim() === "Project folder",
    );
    assert.ok(group, "the Project folder group is missing from the panel");
    return all(group!, ".settings-row button.btn").map((b) =>
      (b.textContent ?? "").trim(),
    );
  };

  test("a folder with no sandbox offers Start, and Start sends no path", async () => {
    // The defect this fixes: the only thing that ever started a sandbox was the
    // folder picker, so a project restored at launch was unusable and the
    // panel said "stopped" with nothing to do about it.
    const { container, transport } = await mount({
      state: { ...BOOT.state, project: FOLDER, sandbox: "stopped" },
      "sandbox.start": { running: true, isolated: true, project: FOLDER },
    });
    await openSettings(container);

    assert.deepEqual(projectButtons(container), ["Change...", "Start"], "the panel offers no way to start the sandbox");
    const start = all(container, ".settings-row button.btn").find(
      (b) => (b.textContent ?? "").trim() === "Start",
    );
    assert.equal(
      (start as HTMLButtonElement).disabled,
      false,
      "the only start control is disabled on a connected window",
    );

    await click(start!);
    await wait(80);

    const request = transport.sent.find((r) => r.method === "sandbox.start");
    assert.ok(request, "Start did not reach the core");
    // Empty, not the path. The core falls back to the folder it has registered,
    // which is the same folder; sending it would let the two disagree about
    // which project the window is on.
    assert.equal(
      request?.params?.path,
      "",
      "Start restated the folder, so a window and a core could name different projects",
    );
  });

  test("a sandbox the core already has shows Stop and no Start", async () => {
    // Read off `state`, not off anything this window did. The sandbox is
    // shared and outlives the window, so a reload is the ordinary case where
    // the button has to be right without the window having clicked anything.
    const { container } = await mount({
      state: { ...BOOT.state, project: FOLDER, sandbox: "running" },
    });
    await openSettings(container);

    const labels = projectButtons(container);
    assert.deepEqual(labels, ["Change...", "Stop"]);
    assert.ok(
      !labels.includes("Start"),
      "the panel offered to start a sandbox that is already running",
    );
  });

  test("no folder means no Start, because there is nothing to start", async () => {
    const { container } = await mount({
      state: { ...BOOT.state, project: "", sandbox: "stopped" },
    });
    await openSettings(container);

    assert.deepEqual(projectButtons(container), ["Choose folder..."]);
  });

  test("while it is starting the button says so instead of inviting a second start", async () => {
    // A container takes seconds to come up. A button that still reads Start
    // for that window is a button the user clicks again, and the second start
    // is a second container on the same folder.
    const { container, transport } = await mount({
      state: { ...BOOT.state, project: FOLDER, sandbox: "stopped" },
    });
    await openSettings(container);

    await push(() =>
      transport.emit(pushed("sandbox.status", { status: "starting" })),
    );
    await wait(40);

    assert.deepEqual(projectButtons(container), ["Change...", "Starting..."]);
    const starting = all(container, ".settings-row button.btn")[1] as HTMLButtonElement;
    assert.equal(starting.disabled, true, "an in-flight start must not be clickable");
  });

  test("the folder note admits that Full does not run in the sandbox", async () => {
    // The sentence was unconditional: "tools are refused outside it", stated
    // one screen below a permission menu whose top rung runs commands on the
    // user's machine. The note is the only prose on this screen that says
    // where anything runs, so it has to carry the exception too.
    //
    // Asserted on the rendered text, so editing the note to be shorter or
    // vaguer without dropping the exception fails here.
    const { container } = await mount();
    await openSettings(container);

    const group = all(container, ".settings-group").find(
      (g) => one(g, "h3")?.textContent?.trim() === "Project folder",
    );
    assert.ok(group, "the Project folder group is missing from the panel");
    const note = one(group!, ".settings-note")?.textContent ?? "";
    assert.match(note, /Full/, "the note no longer says when this does not apply");
    assert.match(
      note,
      /on this computer/,
      "the note does not say what Full does instead",
    );
  });

  test("a sandbox that will not start says so instead of failing silently", async () => {
    // The outcome that used to be unreachable: `sandbox.start` returning
    // `running: false` on a folder that could not be mounted. A Start that
    // vanished with no word would leave the user pressing it again.
    const { container } = await mount({
      state: { ...BOOT.state, project: FOLDER, sandbox: "stopped" },
      "sandbox.start": { running: false, project: FOLDER },
    });
    await openSettings(container);

    await click(
      all(container, ".settings-row button.btn").find(
        (b) => (b.textContent ?? "").trim() === "Start",
      )!,
    );
    await wait(80);

    assert.match(
      texts(container, ".warn").join(" "),
      /did not start/i,
      "a sandbox that refused to start left no message",
    );
  });
});


// --- the usage tab -----------------------------------------------------------
describe("the usage tab", () => {
  const railUsage = (c: HTMLElement) =>
    one(c, '.rail-btn[aria-label="Usage dashboard"]')!;
  const tabTitles = (c: HTMLElement) =>
    all(c, ".tab-title").map((t) => (t.textContent ?? "").trim());

  test("the rail opens it as a tab of its own", async () => {
    // Not a pane and no longer only a view: it is a tab beside the chats, which
    // is what makes it something you can leave open and come back to.
    const { container } = await mount();
    assert.deepEqual(tabTitles(container), [], "the strip started with a tab in it");

    await click(railUsage(container));

    assert.deepEqual(tabTitles(container), ["Usage"]);
    assert.ok(one(container, ".usage"), "the dashboard is not showing");
    // The composer goes with the transcript: a text field under a chart would
    // offer a message for a conversation that is not on screen.
    assert.equal(one(container, ".composer"), null, "the composer is under the chart");
  });

  test("its own close button takes the tab away and brings the chat back", async () => {
    const { container } = await mount();
    await click(railUsage(container));

    const tab = all(container, ".tab").find((t) =>
      (t.textContent ?? "").includes("Usage"),
    )!;
    await click(one(tab, ".tab-close")!);

    assert.deepEqual(tabTitles(container), [], "the tab outlived its close button");
    assert.equal(one(container, ".usage"), null);
    assert.ok(one(container, ".composer"), "the composer did not come back");
  });

  test("pressing the rail again leaves the tab open behind the chat", async () => {
    // The same transition selecting a conversation makes: the view changes, the
    // tab does not close. That is what every other tab in this strip does.
    const { container } = await mount();
    await click(railUsage(container));
    await click(railUsage(container));

    assert.deepEqual(tabTitles(container), ["Usage"], "the tab was closed, not left open");
    assert.equal(one(container, ".usage"), null);
    assert.ok(one(container, ".composer"));
  });

  test("it is a tab, so it is not renameable", async () => {
    // A rename would be a name with nowhere to be stored: this tab is not a
    // conversation and has no id in the store.
    const { container } = await mount();
    await click(railUsage(container));
    const tab = all(container, ".tab").find((t) =>
      (t.textContent ?? "").includes("Usage"),
    )!;
    assert.equal(
      one(tab, ".tab-input"),
      null,
      "a name typed here would have nowhere to go",
    );
    assert.ok(one(tab, ".tab-open"), "the Usage tab is not selectable like the others");
  });
});


// --- named keys over the real protocol ---------------------------------------
describe("the keys pane over the real protocol", () => {
  /**
   * Open Settings and choose the Keys tab.
   *
   * The same two presses a person makes, because the wiring under test is what
   * turns a press into an RPC -- a component test can only prove the callback
   * was called, not that the window sent the name it was given.
   */
  const openKeys = async (c: HTMLElement) => {
    await click(one(c, '.rail-btn[aria-label="Settings"]')!);
    for (let i = 0; i < 50 && !one(c, ".modal"); i++) await wait(20);
    await click(
      all(c, ".settings-tab").find((b) => (b.textContent ?? "").trim() === "Keys")!,
    );
    await wait(60);
  };

  const keyGroup = (c: HTMLElement) =>
    all(c, ".settings-group").find(
      (g) => (one(g, "h3")?.textContent ?? "").trim() === "openrouter",
    )!;

  // The boot table's own provider entry is stale (a display name and has_key),
  // so these tests answer providers.list with the registry shape the core
  // actually sends -- otherwise the section is titled "OpenRouter" and every
  // label the panel writes from the provider name is wrong.
  const PROVIDERS = {
    providers: [{ name: "openrouter", models: [], has_credentials: true }],
  };

  test("saving a named key sends the name, the key and the provider", async () => {
    const { container, transport } = await mount({
      "providers.list": PROVIDERS,
      "key.list": [],
      "key.save": { provider: "openrouter", name: "work", saved: true, listed: true },
    });
    await openKeys(container);
    const group = keyGroup(container);

    await setValue(
      one(group, '[aria-label="Name for a new openrouter key"]') as HTMLInputElement,
      "work",
    );
    await setValue(
      one(group, '[aria-label="New API key for openrouter"]') as HTMLInputElement,
      "sk-typed",
    );
    await click(one(group, ".settings-key-new .settings-key-actions .btn")!);
    await wait(80);

    const sent = transport.sent.find((r) => r.method === "key.save");
    assert.ok(sent, "Save never reached the core");
    assert.deepEqual(sent?.params, {
      provider: "openrouter",
      api_key: "sk-typed",
      name: "work",
    });
  });

  test("Use sends key.activate with that row's name", async () => {
    const { container, transport } = await mount({
      "providers.list": PROVIDERS,
      "key.list": [
        { provider: "openrouter", name: "default", active: true },
        { provider: "openrouter", name: "work", active: false },
      ],
      "key.activate": { provider: "openrouter", name: "work", active: true },
    });
    await openKeys(container);
    const group = keyGroup(container);

    await click(one(group, ".settings-key-use")!);
    await wait(80);

    const sent = transport.sent.find((r) => r.method === "key.activate");
    assert.ok(sent, "Use never reached the core");
    assert.deepEqual(sent?.params, { provider: "openrouter", name: "work" });
  });
});


// --- nothing but what the user is meant to read ------------------------------
test("no stylesheet comment is rendered as text", async () => {
  // A bare `/* ... */` at the JSX level is not a comment -- React renders it as
  // a text node. One shipped inside the sidebar and sat above the Settings
  // heading, and a full run of this suite passed with it there, because every
  // helper queries a selector and nothing looks at what sits *between* the
  // elements. This looks at the whole window at once, which is the only way to
  // see a stray text node.
  const { container } = await mount();
  assert.doesNotMatch(
    container.textContent ?? "",
    /\/\*|\*\//,
    "a comment is being rendered as text",
  );
});
