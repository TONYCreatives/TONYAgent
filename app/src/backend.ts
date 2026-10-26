/**
 * The core client for the TONYAgent headless backend.
 *
 * This is the ONLY place that knows the wire format. The React UI talks to
 * `CoreBackend`, which is deliberately shaped like the Tkinter app's use of
 * AgentSession, so a component cannot tell which one is driving it.
 *
 * Wire protocol: newline-delimited JSON on the core's stdout.
 *   request  {"id":1,"method":"send","params":{...}}
 *   reply    {"id":1,"result":{...}}            | {"id":1,"error":{...}}
 *   event    {"event":true,"type":"...","seq":1,"turn_id":null,"payload":{}}
 *
 * Ordering guarantee relied upon below: the reply to a request is written
 * before any events that request causes, so a turn id is always known before
 * its first delta arrives.
 *
 * NOTE: the host is reached through `bridge.ts`, which imports nothing at all --
 * it reads one global that the host installs. So every consumer of this file,
 * including the protocol tests, stays runnable in plain Node with no window, no
 * Python and no Rust toolchain. That is the same coupling this layout was built
 * to avoid, and it survives the shell changing underneath it.
 */

import { installPushHandlers, whenHostReady, type HostApi } from "./bridge.js";


/** Wire names must stay in sync with tonyagent/core/events.py EventType. */
export type EventType =
  | "turn.started"
  | "turn.finished"
  | "turn.failed"
  | "turn.usage"
  | "message.started"
  | "message.delta"
  | "message.completed"
  | "reasoning.delta"
  | "reasoning.completed"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "confirmation.requested"
  | "confirmation.resolved"
  | "user.asked"
  | "user.resolved"
  | "sandbox.status"
  | "sandbox.stats"
  | "log"
  | "error";

export interface CoreEvent {
  event: true;
  type: EventType;
  seq: number;
  turn_id: string | null;
  payload: Record<string, unknown>;
  /**
   * Present only on a subagent's frames: its name, and the id of the parent
   * tool call that spawned it. See `Event.subagent` in `core/events.py`.
   *
   * The turn id alone cannot attribute a child's work: it is the *child's*
   * turn, and this transcript has never seen it. The call id is the link the
   * reducer draws the child's work under -- see `applySubagentEvent`.
   */
  subagent?: string;
  parent_call_id?: string;
}

export interface CoreRequest {
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

/**
 * One item of the core's task list, as `plan.get` returns it.
 *
 * The statuses are the core's three (`core/task_state.py`), not a boolean:
 * "not done yet" and "being worked on right now" are different things to a
 * reader deciding whether the agent is stuck.
 */
export interface PlanItem {
  text: string;
  status: "pending" | "in_progress" | "completed";
}

/** The plan for the open conversation -- a task list plus the goal. */
export interface Plan {
  todos: PlanItem[];
  goal: string;
  /** `active` / `complete` / `blocked`, or "" when there is no goal. */
  goal_status: string;
  goal_note: string;
}

/**
 * `plan.get`'s reply.
 *
 * `rendered` is the block the model is actually shown, returned so a reader can
 * display that rather than a second rendering of the same data that could
 * disagree with it. The window draws the structured form; the rendered text is
 * what a future "what the model sees" view would show.
 */
export interface PlanReply {
  plan: Plan;
  summary: string;
  rendered: string;
}

/**
 * `context.get`'s reply: how full the conversation is.
 *
 * Both numbers are the core's measurements and both may be absent, which is why
 * `known` is a field of its own rather than being inferred from `used > 0`:
 * `used` is the input side of the most recent request *as the provider reported
 * it*, and a provider that reports no usage leaves it at 0. Drawing that as 0%
 * of the window is worse than drawing nothing -- it is confidently wrong -- so
 * the window tells "zero" and "unknown" apart.
 *
 * `window` is the model's own `context_length`. 0 means the provider publishes
 * none, not that the context is empty.
 */
export interface ContextReply {
  model: string;
  used: number;
  known: boolean;
  window: number;
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

/** One file on its way to the core, in the shape `attachments.validate` reads. */
export interface WireAttachment {
  name: string;
  /** The browser's type, or "" when it has none -- the core falls back to the extension. */
  mime: string;
  /** base64, no data-URL prefix. */
  data: string;
}

/** Methods the core accepts. Kept narrow so typos fail at compile time. */
export interface CoreMethods {
  ping: Record<string, never>;
  state: Record<string, never>;
  clear: Record<string, never>;
  cancel: Record<string, never>;
  send: {
    text: string;
    attachments?: WireAttachment[];
    /**
     * What the user changed by hand in the viewer since the last message.
     *
     * `added`/`removed` are the core's own counts from the save; `lines` are
     * 1-based ranges in the file *as it now stands*, computed by the window
     * because only it knows what the keystrokes did. The core turns them into
     * a block appended to the message the model receives.
     */
    user_edits?: Array<{ path: string; added: number; removed: number; lines: unknown[] }>;
  };
  bind_provider: { name: string; model?: string; base_url?: string };
  /** Provider names come from the core's registry, never from a local copy. */
  "providers.list": Record<string, never>;
  /**
   * Every model the bound provider offers.
   *
   * From the provider's own `/models`, not from the registry's seed list: that
   * seed is five illustrative ids with a comment saying OpenRouter proxies
   * hundreds more, so a picker built from it would show a user five of the
   * models they have. `current` is what the menu ticks, so the component never
   * has to guess which entry is bound.
   *
   * An empty list comes back as an error rather than as an empty array. A
   * provider that will not list its models will not serve them either, and an
   * empty dropdown says nothing about which of the two happened.
   */
  "models.list": Record<string, never>;
  /**
   * Every model with its catalog facts: display name, context window, max
   * output tokens, input modalities and wire protocol.
   *
   * Read from the same cached `/models` entries as `models.list`, so it costs
   * no extra request. Rows for models the curator knows nothing about carry
   * zeros and empty lists -- the picker draws no label for those, which is
   * not the same as drawing a wrong one.
   */
  "models.catalog": Record<string, never>;
  /**
   * Whether a newer TONYAgent has been released.
   *
   * **The answer carries its own failure.** `reason` is "" when the question
   * was answered, and otherwise says why it was not (`offline`, `rate_limited`,
   * `not_found`, `server`, `malformed`). "Up to date" and "could not ask" are
   * different facts, and a check that cannot reach GitHub has not learned that
   * you are current.
   */
  "update.check": { force?: boolean };
  /**
   * Fetch the installer for the release the check found, and verify it.
   *
   * No address and no digest cross this boundary: both come from GitHub's reply
   * inside the core, so the page cannot ask for a download from elsewhere. A
   * file that fails verification is deleted rather than left where the window
   * could run it.
   */
  "update.download": Record<string, never>;
  /**
   * Store an API key in the OS keyring under a name.
   *
   * The key goes out on stdin and the reply carries only the provider and the
   * name. `name` is optional and means "default", which is the field every
   * key saved before names existed lives in.
   */
  "key.save": { provider: string; api_key: string; name?: string };
  /**
   * Every stored key as a row: provider, name, and whether it is the active one.
   *
   * No secret crosses here -- the core answers names, never values -- which is
   * what lets the panel draw its list on mount without pulling a credential out
   * of the keyring.
   */
  "key.list": { provider?: string };
  /** `name` is required: deleting "the active one" is a destructive default. */
  "key.delete": { provider: string; name: string };
  /**
   * Read one stored key back, on request.
   *
   * **The one method whose *reply* carries a secret** -- the mirror of
   * `key.save`, where the value travels the other way. It exists because a user
   * who cannot check which key is stored cannot tell a stale key from a wrong
   * one, and the cost is the one this file used to refuse outright: a live
   * credential in the DOM.
   *
   * So the bounding is at the call site rather than here -- one named row, one
   * press, cleared on hide and on unmount. Nothing on a timer calls it:
   * `key.list` answers names only, so a key never leaves the keyring unless
   * somebody asks. `name` absent means the key in force.
   */
  "key.reveal": { provider: string; name?: string };
  /**
   * Choose which stored key this provider's turns spend.
   *
   * Separate from a save on purpose: adding a second key must not silently take
   * over the credential the next message uses. The core refuses a name nothing
   * is stored under, so a press cannot succeed into a broken provider.
   */
  "key.activate": { provider: string; name: string };
  /**
   * What this window has spent on API calls, aggregated for one window.
   *
   * `window` is one of `today`, `3d`, `7d`, `30d`, `all`; the core refuses an
   * unknown name rather than defaulting, so a typo shows up as an error instead
   * of a chart of the wrong period.
   *
   * One method rather than five, because the totals, the day series and the
   * per-key breakdowns come from one pass over one set of records and are drawn
   * together -- five calls would be five chances to disagree with each other.
   */
  "usage.summary": { window?: string };
  /**
   * Conversations.
   *
   * Summaries only in `list`: a list row renders a title and a timestamp, so
   * shipping every transcript to draw a sidebar would move the whole history
   * across the pipe on every launch.
   */
  "conversations.list": Record<string, never>;
  "conversations.create": { project?: string; track?: string };
  "conversations.switch": { id: string };
  "conversations.delete": { id: string };
  "conversations.rename": { id: string; title: string };
  "conversations.duplicate": { id: string };
  /**
   * File a conversation under a folder.
   *
   * The window works in one folder at a time and the sidebar lists that folder's
   * chats, so this is what carries the chat you are looking at across when you
   * change folders. `project` is named rather than read from the core's own
   * folder: the caller has just bound it, and a pick that did not take must not
   * move anything.
   */
  "conversations.move": { id: string; project: string };
  /**
   * The task list and goal for the open conversation.
   *
   * Read on demand rather than folded into `state`: that reply is about the
   * session's mode, permission and sandbox, and adding a key to it would oblige
   * every existing reader to know about a field it does not use. The workspace's
   * Run panel refreshes this at the start and end of a turn, and on first paint,
   * so a restored conversation shows the plan it was saved with.
   */
  "plan.get": Record<string, never>;
  /**
   * How full the conversation is, for the Run card's meter.
   *
   * Read on demand for the same reason `plan.get` is, and refreshed when the
   * panel opens, when a turn starts and when it finishes: `used` moves with the
   * requests a turn makes, so a value read once at boot would describe the
   * conversation as it was an hour ago.
   */
  "context.get": Record<string, never>;
  /**
   * The skills a message may open with `/name`.
   *
   * Read from the core's own store, which is the same one `list_skills` and
   * `run_skill` read, so the menu can never offer a name the agent cannot
   * load. It is re-read whenever the menu opens rather than fetched once at
   * mount: the user adds and edits these files in their own editor while the
   * window is up, and a cached list would be stale exactly when it is being
   * looked at.
   */
  "skills.list": Record<string, never>;
  /** Available composer modes and which one is in force. */
  "mode.list": Record<string, never>;
  "mode.set": { mode: string };
  /**
   * How much the agent is allowed to do, and which level is in force.
   *
   * A separate axis from `mode` on purpose. A mode decides what the agent is
   * *for* (plan a change, make one); this decides how far it may go (read only,
   * edit, run commands, run them unasked). They intersect, so either can only
   * ever narrow what the other allows.
   */
  "permission.list": Record<string, never>;
  "permission.set": { permission: string };
  /**
   * How hard the bound model can be asked to think.
   *
   * `supported: false` means the model does not reason at all, and the core
   * will not send a `reasoning` field for it. `efforts` is empty for a model
   * that reasons with no dial, which is a different thing: it thinks, and
   * there is nothing to choose.
   */
  "reasoning.list": Record<string, never>;
  /** `effort: ""` hands the decision back to the model. */
  "reasoning.set": { effort: string };
  /**
   * The per-turn tool call budget.
   *
   * Counted per individual call, not per assistant pass, so a model asking
   * for five tools in one message has spent five. `get` reads the value the
   * next turn is actually held to, which is the session's -- not the setting
   * file's, and the two differ the moment it is changed here.
   */
  "tools.get": Record<string, never>;
  /** One is the floor: zero would refuse every tool, not make a small budget. */
  "tools.set": { max_tool_calls: number };
  /**
   * The settings page's read.
   *
   * Both command lists, as the shell gate will read them: the allow-list the
   * file holds, and the deny list the core unions with it. Read from the tool
   * layer rather than the file, so what the page draws is the list a turn is
   * held to rather than the half of it the file happens to carry.
   */
  "settings.get": Record<string, never>;
  /**
   * The settings page's write.
   *
   * `key` is dotted -- `section.name` -- and has to be one the core will
   * accept; anything else is refused rather than written. A `value` of null
   * means *unset*: remove the key and go back to the default, which is what
   * "Restore defaults" sends. The reply carries the value now in force, read
   * back the way the next turn reads it.
   */
  "settings.set": { key: string; value: unknown };
  /**
   * The facts a bug report needs, as the core knows them.
   *
   * Version, author, the Python it runs on, whether this is the frozen bundle
   * or a source checkout, and the config and log paths. Read rather than
   * assembled here: the config path depends on the platform and on which
   * APPDATA the core sees, and a path the window guessed at is how a user ends
   * up looking for logs in a folder that was never written to.
   */
  "diagnostics.get": Record<string, never>;
  search: {
    pattern: string;
    path?: string;
    include?: string;
    case_sensitive?: boolean;
    max_results?: number;
    context_lines?: number;
  };
  /**
   * `running` means a sandbox runtime is available, which without Docker is
   * the local one. `isolated` says whether code the agent generates is
   * actually contained. They are separate because with no Docker daemon the
   * first is true and the second is false, and collapsing them into one boolean
   * is what made the app look broken on a machine without Docker.
   */
  "sandbox.start": { path?: string };
  "sandbox.stop": Record<string, never>;
  "sandbox.stats": Record<string, never>;
  "confirm.respond": { id: string; confirmed: boolean };
  /** Answer a question, or add a note to a presentation. Empty is an answer. */
  "user.respond": { id: string; answer: string };
  "trust.set": { project: string; trusted: boolean };
  /**
   * The project tree, for the file explorer.
   *
   * Walked by the *core*, not by the window, and for the same reason `search`
   * delegates to the agent's grep: the skip rules (`.git`, `node_modules`,
   * the caches) and the project boundary are the agent's, and a second walk
   * here would be a second set of rules to disagree with the first. What the
   * core would not read, the tree does not list.
   *
   * Bounded on both axes and honest about it: `truncated` comes back true
   * when the walk hit its entry or depth limit, so the pane can say where it
   * stopped instead of presenting a partial tree as the whole project.
   */
  "files.tree": { path?: string; max_entries?: number; max_depth?: number };
  /**
   * One project file's text, for the viewer.
   *
   * The reply carries `language`, resolved by the core from the file's name
   * rather than guessed here: `Dockerfile` and `dockerfile.something` are
   * different questions, and one owner of the answer keeps the highlighting
   * honest. A file the viewer cannot show -- binary, too large, outside the
   * project -- comes back as an *error* with a sentence, because an empty
   * editor claiming the file is empty would be a lie.
   */
  "files.read": { path: string };
  /**
   * Save the viewer's buffer.
   *
   * The user's own write, which is why it is not confirmation-gated: the gate
   * on the agent's `write` tool asks the user before the *agent* touches their
   * files, and a person typing in the editor in front of them is the act that
   * gate exists to protect. The core still confines the path, caps the size,
   * replaces the file atomically and reports what changed -- and what changed
   * is what the next message tells the model.
   */
  "files.write": { path: string; content: string };
}

/**
 * Methods whose params carry a secret.
 *
 * The request is written to the core verbatim, because the core has to
 * receive the real key. The list exists so the one place that could leak it --
 * a debug log of the outgoing frame -- is impossible to add by accident, and
 * so `backend.test.ts` can assert no diagnostic ever contains the value.
 *
 * `key.reveal` is deliberately *not* in here: its request is a provider name.
 * Its secret comes back on the reply, and that path has no diagnostic at all --
 * `handleLine` resolves the promise and writes nothing, which is why the only
 * line it can echo is the non-JSON fallback, and a reply containing a key is
 * JSON.
 */
const SECRET_METHODS: ReadonlySet<string> = new Set(["key.save"]);

/** True when this request carries a value that must never be displayed. */
export function carriesSecret(method: string): boolean {
  return SECRET_METHODS.has(method);
}

/**
 * Talks to the Python core over stdio.
 *
 * stdout is a byte stream with no framing beyond newlines, so chunks are
 * buffered until a complete line is available. A partial read is normal and
 * must never be treated as a message.
 */
export class CoreBackend {
  private transport: LineTransport | null = null;
  private buffer = "";
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private listeners = new Set<(event: CoreEvent) => void>();
  private logListeners = new Set<(line: string) => void>();
  private onExit: (() => void) | null = null;
  private readonly makeTransport: () => LineTransport;
  /**
   * Serialises start/stop.
   *
   * React 19's StrictMode mounts, unmounts and remounts every effect in
   * development, so `start()` and `stop()` genuinely race: cleanup runs
   * before the second mount's start. `stop()` used to null `this.transport`
   * only after awaiting `kill()`, so the second `start()` saw a non-null
   * transport, returned early having spawned nothing, and every later request
   * died with "sidecar not started" while a real sidecar ran on, unowned.
   *
   * Chaining the whole lifecycle through one promise makes the order
   * start -> stop -> start an actual sequence instead of a race. Both
   * branches of `then` are needed: one rejected lifecycle must not wedge
   * every later call.
   */
  private lifecycle: Promise<void> = Promise.resolve();

  /**
   * @param makeTransport builds the transport. Defaults to the real window host
   *   host; tests pass a fake, which is what lets the protocol be verified
   *   without Rust or Python.
   *
   * Declared as an explicit field rather than a constructor parameter property
   * so the file runs under Node's strip-only type stripping, which does not
   * support parameter properties.
   */
  constructor(makeTransport: () => LineTransport = () => makeHostTransport()) {
    this.makeTransport = makeTransport;
  }

  /** Start the backend. Safe to call once per window. */
  start(): Promise<void> {
    return this.enqueue(() => this.doStart());
  }

  private async doStart(): Promise<void> {
    if (this.transport) return;
    const transport = this.makeTransport();
    this.transport = transport;

    transport.onStdout((text) => this.ingest(text));
    transport.onStderr((text) => {
      // stdout is the protocol; stderr is for humans.
      for (const line of text.split("\n")) {
        if (line.trim()) this.logListeners.forEach((fn) => fn(line));
      }
    });
    transport.onExit(() => {
      // Only tear down if this is still the *current* transport.
      //
      // The core's exit event is delivered asynchronously, so the one we just
      // killed reports "exited" after the replacement has already been
      // assigned. An unconditional `this.transport = null` here therefore
      // killed the brand-new backend a moment after it started: the window
      // showed "disconnected" while a working sidecar ran, unowned, and every
      // request failed with "Backend is not running".
      if (this.transport !== transport) return;
      this.failAll(new Error("The TONYAgent backend exited."));
      this.transport = null;
      this.onExit?.();
    });
    try {
      await transport.start();
    } catch (error) {
      // Clear the half-built transport before rethrowing. Leaving it set makes
      // every later start() a silent no-op that returns "successfully" while
      // writes go to a process that does not exist, so the failure surfaces as
      // a hang instead of an error.
      this.transport = null;
      throw error;
    }
  }

  /** Queue work so start and stop can never interleave. */
  private enqueue(work: () => Promise<void>): Promise<void> {
    const next = this.lifecycle.then(work, work);
    // Keep the chain alive after a failure; the caller still sees the
    // rejection through its own reference.
    this.lifecycle = next.catch(() => {});
    return next;
  }

  /** Register a listener for pushed core events. Returns an unsubscribe fn. */
  onEvent(fn: (event: CoreEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Register a listener for backend stderr output. */
  onLog(fn: (line: string) => void): () => void {
    this.logListeners.add(fn);
    return () => this.logListeners.delete(fn);
  }

  onBackendExit(fn: () => void): void {
    this.onExit = fn;
  }

  /** Stop the backend. */
  stop(): Promise<void> {
    return this.enqueue(() => this.doStop());
  }

  private async doStop(): Promise<void> {
    this.failAll(new Error("The TONYAgent backend was stopped."));
    // Detach before awaiting: a start() queued behind this one must not find
    // a transport that is on its way out.
    const transport = this.transport;
    this.transport = null;
    if (!transport) return;
    try {
      await transport.kill();
    } catch {
      // Already gone.
    }
  }

  /** Send a request and await its reply. */
  async call<M extends keyof CoreMethods>(
    method: M,
    params?: CoreMethods[M],
  ): Promise<unknown> {
    const id = this.nextId++;
    const request: CoreRequest = { id, method: String(method), params };
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });

    // Write synchronously whenever a transport is already up. Awaiting first
    // would push the write a microtask into the future, which is observable:
    // a caller that starts a request and immediately inspects what was sent
    // would see nothing. Only the no-transport case waits, and that wait is
    // what lets a request issued mid-teardown find the transport the *next*
    // start() creates instead of failing against a disposed one.
    if (!this.transport) {
      await this.lifecycle;
      if (!this.transport) {
        this.pending.delete(id);
        throw new Error("Backend is not running. Start it before sending messages.");
      }
    }
    await this.transport.write(JSON.stringify(request) + "\n");
    return promise;
  }

  /**
   * Send a message, with whatever files go with it.
   *
   * The attachments go in the message rather than beside it. A path would make
   * the agent go and read a file with a tool, which is a second round trip and
   * a second place to fail; the bytes are already in the window, and the
   * endpoint accepts them as content parts.
   *
   * `userEdits` is what the user changed by hand in the viewer since the last
   * message. It rides with the message because that is the one moment the
   * agent is guaranteed to look: its picture of those files is stale until it
   * is told, and an answer about a file the user has already fixed is
   * confident nonsense.
   */
  async send(
    text: string,
    attachments: WireAttachment[] = [],
    userEdits: Array<{ path: string; added: number; removed: number; lines: unknown[] }> = [],
  ): Promise<string> {
    const result = (await this.call("send", {
      text,
      attachments,
      ...(userEdits.length ? { user_edits: userEdits } : {}),
    })) as {
      turn_id: string;
    };
    return result.turn_id;
  }

  /** Split a stdout chunk into complete lines and dispatch them. */
  private ingest(text: string): void {
    this.buffer += text;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) this.handleLine(line);
    }
  }

  private handleLine(line: string): void {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line);
    } catch {
      // Not protocol output. Surface it rather than dropping it silently.
      this.logListeners.forEach((fn) => fn(`[non-json] ${line}`));
      return;
    }

    if (message.event === true) {
      const evt = message as unknown as CoreEvent;
      this.listeners.forEach((fn) => fn(evt));
      return;
    }

    const id = message.id as number;
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    if (message.error) {
      const err = message.error as { code?: string; message?: string };
      const error = new Error(err.message ?? "Backend error");
      error.name = err.code ?? "backend_error";
      pending.reject(error);
    } else {
      pending.resolve(message.result);
    }
  }

  /** Reject everything in flight; used when the backend dies. */
  private failAll(error: Error): void {
    for (const [, pending] of this.pending) pending.reject(error);
    this.pending.clear();
  }
}

// ---------------------------------------------------------------------------
// Transport interface
// ---------------------------------------------------------------------------

/**
 * The subset of the core API that CoreBackend uses.
 *
 * Extracted so the protocol logic (line framing, request/reply pairing, event
 * dispatch) can be tested in plain Node with no window, no Python and no
 * Python process. That is deliberate: the protocol is the contract, and it
 * should be verifiable before anyone can open a window.
 */
export interface LineTransport {
  start(): Promise<void>;
  write(line: string): Promise<void>;
  onStdout(fn: (text: string) => void): void;

  onStderr(fn: (text: string) => void): void;
  onExit(fn: () => void): void;
  kill(): Promise<void>;
}

/**
 * The real transport: the window host.
 *
 * The core is a child process of the *host*, not of this page, so there is
 * nothing here to spawn and nothing here to kill. What this does is install the
 * push handlers, wait for the bridge to announce itself, and then carry lines
 * in one direction and out the other.
 *
 * The order of the first two steps is load-bearing. `installPushHandlers` must
 * run *before* `ready()`, because `ready()` is what makes the host flush the
 * frames it buffered while the page was loading -- and the first of those
 * frames is the reply to the first request this backend sends. Reversed, that
 * batch would be pushed into a global that did not exist yet, and the window
 * would sit on "disconnected" with nothing in any log to say why.
 *
 * `whenHostReady` resolves to null when there is no host, and this throws
 * rather than handing back a transport that quietly swallows writes. A page
 * open in a browser has no core to talk to, and failing `start()` is how the
 * window gets to say so.
 */
function makeHostTransport(): LineTransport {
  let stdout: ((text: string) => void) | null = null;
  let stderr: ((text: string) => void) | null = null;
  let exit: (() => void) | null = null;
  let api: HostApi | null = null;

  return {
    async start() {
      api = await whenHostReady();
      if (!api) {
        throw new Error(
          "No window host answered, so this page has no backend to talk to.",
        );
      }
      // The host sends one *batch* per call, so splitting it back into lines is
      // this side's job. `CoreBackend.ingest` buffers partial lines itself,
      // which is what makes passing whole lines straight through correct.
      // The host hands over *lines*, and this side speaks in chunks of the
      // stream -- so the terminator has to be put back.
      //
      // **Without it, not one reply ever resolves.** `ingest` frames on
      // newlines, so a batch of bare lines is appended to the buffer and never
      // split, and every request stays pending forever: the window draws, says
      // "connected", and then sits there with an empty model picker, no
      // provider and no conversations. Measured, not reasoned about -- the core
      // answered `state` with `project: ...\WebAIAgent` and the window went on
      // showing "No project folder", and the only requests it ever sent were the
      // three whose effects do not await a reply.
      installPushHandlers({
        frames: (lines) => {
          for (const line of lines) stdout?.(`${line}\n`);
        },
        log: (line) => stderr?.(line),
        exit: () => exit?.(),
      });
      await api.ready();
    },

    async write(line: string) {
      if (!api) throw new Error("the window host is not ready");
      await api.send(line);
    },

    onStdout(fn) {
      stdout = fn;
    },
    onStderr(fn) {
      stderr = fn;
    },
    onExit(fn) {
      exit = fn;
    },

    async kill() {
      // Deliberately empty, and not an oversight. The core belongs to the host
      // and the host reaps it when the window closes; killing it from here
      // would mean a page that unmounts -- a remount, a hot reload -- takes the
      // backend down with it while the window is still open.
      api = null;
    },
  };
}
