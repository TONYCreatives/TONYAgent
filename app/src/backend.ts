/**
 * Tauri sidecar client for the TONYAgent headless core.
 *
 * This is the ONLY place that knows the wire format. The React UI talks to
 * `TauriBackend`, which is deliberately shaped like the Tkinter app's use of
 * AgentSession, so a component cannot tell which one is driving it.
 *
 * Wire protocol: newline-delimited JSON on the sidecar's stdout.
 *   request  {"id":1,"method":"send","params":{...}}
 *   reply    {"id":1,"result":{...}}            | {"id":1,"error":{...}}
 *   event    {"event":true,"type":"...","seq":1,"turn_id":null,"payload":{}}
 *
 * Ordering guarantee relied upon below: the reply to a request is written
 * before any events that request causes, so a turn id is always known before
 * its first delta arrives.
 *
 * NOTE: `@tauri-apps/plugin-shell` is imported lazily inside
 * makeSidecarTransport. A top-level import would make every consumer of this
 * file - including the protocol tests - require a Tauri install, which is
 * exactly the coupling this layout is meant to avoid.
 */

/** Wire names must stay in sync with tonyagent/core/events.py EventType. */
export type EventType =
  | "turn.started"
  | "turn.finished"
  | "turn.failed"
  | "message.started"
  | "message.delta"
  | "message.completed"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "confirmation.requested"
  | "confirmation.resolved"
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
}

export interface CoreRequest {
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

/** Methods the core accepts. Kept narrow so typos fail at compile time. */
export interface CoreMethods {
  ping: Record<string, never>;
  state: Record<string, never>;
  clear: Record<string, never>;
  cancel: Record<string, never>;
  send: { text: string };
  bind_provider: { name: string; model?: string; base_url?: string };
  /** Provider names come from the core's registry, never from a local copy. */
  "providers.list": Record<string, never>;
  /**
   * Store an API key in the OS keyring.
   *
   * The key goes out on stdin and the reply carries only the provider name.
   * There is deliberately no `key.get`: a method that returns a secret is a
   * method whose secret can reach a screenshot.
   */
  "key.save": { provider: string; api_key: string };
  "key.delete": { provider: string };
  /** Available composer modes and which one is in force. */
  "mode.list": Record<string, never>;
  "mode.set": { mode: string };
  search: {
    pattern: string;
    path?: string;
    include?: string;
    case_sensitive?: boolean;
    max_results?: number;
    context_lines?: number;
  };
  "sandbox.start": { path?: string };
  "sandbox.stop": Record<string, never>;
  "sandbox.stats": Record<string, never>;
  "confirm.respond": { id: string; confirmed: boolean };
  "trust.set": { project: string; trusted: boolean };
}

/**
 * Methods whose params carry a secret.
 *
 * The request is written to the sidecar verbatim, because the core has to
 * receive the real key. The list exists so the one place that could leak it --
 * a debug log of the outgoing frame -- is impossible to add by accident, and
 * so `backend.test.ts` can assert no diagnostic ever contains the value.
 */
const SECRET_METHODS: ReadonlySet<string> = new Set(["key.save"]);

/** True when this request carries a value that must never be displayed. */
export function carriesSecret(method: string): boolean {
  return SECRET_METHODS.has(method);
}

/**
 * Talks to the Python sidecar over stdio.
 *
 * stdout is a byte stream with no framing beyond newlines, so chunks are
 * buffered until a complete line is available. A partial read is normal and
 * must never be treated as a message.
 */
export class TauriBackend {
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
   * @param makeTransport builds the transport. Defaults to a real Tauri
   *   sidecar; tests pass a fake, which is what lets the protocol be verified
   *   without Rust or Python.
   *
   * Declared as an explicit field rather than a constructor parameter property
   * so the file runs under Node's strip-only type stripping, which does not
   * support parameter properties.
   */
  constructor(makeTransport: () => LineTransport = () => makeSidecarTransport()) {
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
      // A sidecar's exit event is delivered asynchronously, so the one we just
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

  /** Convenience wrapper for the common send case. */
  async send(text: string): Promise<string> {
    const result = (await this.call("send", { text })) as { turn_id: string };
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
 * The subset of the sidecar API TauriBackend uses.
 *
 * Extracted so the protocol logic (line framing, request/reply pairing, event
 * dispatch) can be tested in plain Node with no Tauri, no Rust toolchain and no
 * Python process. That is deliberate: the protocol is the contract, and it
 * should be verifiable before anyone can run `cargo build`.
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
 * The real Tauri sidecar transport.
 *
 * Isolated in its own factory so the protocol logic above stays testable in
 * plain Node: importing backend.ts must not require Tauri to be installed.
 */
function makeSidecarTransport(): LineTransport {
  // Resolved lazily, and via a dynamic import() rather than a top-level one.
  //
  // A top-level `import` would be hoisted and evaluated when this module loads,
  // which would make the protocol tests need Tauri installed -- the exact
  // coupling this layout exists to avoid.
  //
  // A bare `require()` is not an option: it does not exist in an ES module, and
  // Vite does not define one. `typeof require === "function"` is therefore
  // false in the bundled app, and the previous fallback to
  // `globalThis.__tauriRequire` was never defined either, so the spawn threw
  // and the window silently showed "disconnected" forever.
  //
  // `import()` works in both worlds: Node resolves it for the tests, and Vite
  // turns it into a real chunked import for the app.
  // Tauri decodes the child's bytes for us (the default, non-raw encoding), so
  // no TextDecoder belongs here.
  let shellModule: typeof import("@tauri-apps/plugin-shell") | null = null;
  const loadShell = async () => {
    if (!shellModule) {
      shellModule = await import("@tauri-apps/plugin-shell");
    }
    return shellModule;
  };

  // `Command` is generic over its output encoding; `string` is the variant the
  // sidecar speaks, since stdout is JSONL text.
  let cmd: import("@tauri-apps/plugin-shell").Command<string> | null = null;
  // `spawn()` returns the Child handle that owns stdin and kill(). The Command
  // itself only emits output and lifecycle events. Keeping these separate
  // matters: writing to `cmd` was a type error that the previous `any` hid.
  let child: import("@tauri-apps/plugin-shell").Child | null = null;
  let stdout: ((text: string) => void) | null = null;
  let stderr: ((text: string) => void) | null = null;
  let exit: (() => void) | null = null;

  return {
    async start() {
      // Bare sidecar name, no `binaries/` prefix and no target-triple suffix.
      // Tauri resolves those itself: it matches the name against the
      // `externalBin` entries in tauri.conf.json and appends
      // `-<target-triple>`. Naming it "binaries/tonyagent-core" fails to
      // resolve and the spawn is rejected with no obvious error.
      const { Command } = await loadShell();
      // Must match a `bundle.externalBin` entry in tauri.conf.json, which is
      // "binaries/tonyagent-core". Tauri compares this string against those
      // entries directly (also accepting the same name minus a trailing ".exe"),
      // and rejects anything else with:
      //   sidecar not configured under `tauri.conf.json > bundle > externalBin`
      // The target triple is appended by Tauri when it resolves the file, so
      // it must not appear here.
      cmd = Command.sidecar("binaries/tonyagent-core");

      // With the default (non-raw) encoding, `data` carries one line per
      // event, newline already stripped. TauriBackend's ingest() buffers
      // partial lines, so passing a line straight through is correct and
      // avoids re-splitting text that is already framed.
      cmd.stdout.on("data", (line: string) => stdout?.(line));
      cmd.stderr.on("data", (line: string) => stderr?.(line));

      // The Child handle is what owns stdin and kill(); `Command` does not.
      child = await cmd.spawn();

      // Process exit is reported on the Command's own `close` event, not on
      // the Child. Without this the UI would sit on "connected" after the core
      // died, and every later request would hang instead of failing.
      cmd.on("close", () => exit?.());
      cmd.on("error", (message: string) => {
        // Surface a spawn failure rather than leaving the window blank.
        stderr?.(`[sidecar] ${message}`);
        exit?.();
      });
    },
    async write(line: string) {
      if (!child) throw new Error("sidecar not started");
      await child.write(line);
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
      await child?.kill();
      child = null;
      cmd = null;
    },
  };
}
