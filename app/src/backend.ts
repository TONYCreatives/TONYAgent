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
  bind_provider: { name: string; model?: string };
  "sandbox.start": { path?: string };
  "sandbox.stop": Record<string, never>;
  "sandbox.stats": Record<string, never>;
  "confirm.respond": { id: string; confirmed: boolean };
  "trust.set": { project: string; trusted: boolean };
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
  async start(): Promise<void> {
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
      this.failAll(new Error("The TONYAgent backend exited."));
      this.transport = null;
      this.onExit?.();
    });
    await transport.start();
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
  async stop(): Promise<void> {
    this.failAll(new Error("The TONYAgent backend was stopped."));
    if (this.transport) {
      try {
        await this.transport.kill();
      } catch {
        // Already gone.
      }
      this.transport = null;
    }
  }

  /** Send a request and await its reply. */
  async call<M extends keyof CoreMethods>(
    method: M,
    params?: CoreMethods[M],
  ): Promise<unknown> {
    if (!this.transport) {
      throw new Error("Backend is not running. Start it before sending messages.");
    }
    const id = this.nextId++;
    const request: CoreRequest = { id, method: String(method), params };
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
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
  // Lazily resolved, and via an injected require so the protocol tests can
  // exercise this file without Tauri installed.
  const requireFn: (id: string) => any =
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    typeof require === "function" ? require : (globalThis as any).__tauriRequire;
  const { Command } = requireFn("@tauri-apps/plugin-shell");
  const decoder = new TextDecoder();
  let cmd: InstanceType<typeof Command> | null = null;
  let stdout: ((text: string) => void) | null = null;
  let stderr: ((text: string) => void) | null = null;
  let exit: (() => void) | null = null;

  return {
    async start() {
      cmd = Command.sidecar("binaries/tonyagent-core");
      cmd.stdout.on("data", (chunk: Uint8Array) => stdout?.(decoder.decode(chunk)));
      cmd.stderr.on("data", (chunk: Uint8Array) => stderr?.(decoder.decode(chunk)));
      const child = await cmd.spawn();
      await child.onExit(() => exit?.());
    },
    async write(line: string) {
      if (!cmd) throw new Error("sidecar not started");
      await cmd.write(line);
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
      await cmd?.kill();
      cmd = null;
    },
  };
}
