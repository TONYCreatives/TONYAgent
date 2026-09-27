/**
 * Protocol tests for the sidecar client.
 *
 * These run in plain Node with no Tauri, no Rust toolchain and no Python. That
 * is the point: the wire contract must be verifiable before anyone installs a
 * build toolchain, otherwise a protocol mistake is only discovered at the most
 * expensive moment.
 *
 * The fake transport replays the exact frames the Python core emits, mirroring
 * ``tests/unit/test_headless_core.py``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// ".js" (not ".ts") is the spec-correct specifier under NodeNext/ESM: the
// runtime resolves the compiled file. tsc rewrites nothing here because this is
// a plain relative import, so it must already name the emitted file.
import { TauriBackend, type LineTransport, type CoreEvent } from "./backend.js";
/** A transport that records writes and lets a test push stdout frames. */
class FakeTransport implements LineTransport {
  written: string[] = [];
  private stdout?: (text: string) => void;
  private stderr?: (text: string) => void;
  private exit?: () => void;
  killed = false;

  async start(): Promise<void> {}
  async write(line: string): Promise<void> {
    this.written.push(line);
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
  }

  /** Push raw stdout, exactly as the OS would deliver it. */
  push(text: string): void {
    this.stdout?.(text);
  }
  pushStderr(text: string): void {
    this.stderr?.(text);
  }
  simulateExit(): void {
    this.exit?.();
  }
}

/** Build a backend over a fresh fake transport, both returned. */
function makeBackend() {
  const transport = new FakeTransport();
  const backend = new TauriBackend(() => transport);
  return { transport, backend };
}

test("a reply resolves the matching request", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();

  const call = backend.call("ping");
  transport.push('{"id":1,"result":{"pong":true,"protocol":1}}\n');
  assert.deepEqual(await call, { pong: true, protocol: 1 });
});

test("requests carry an incrementing id", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();

  const a = backend.call("ping");
  const b = backend.call("state");
  const ids = transport.written.map((l) => JSON.parse(l).id);
  assert.deepEqual(ids, [1, 2]);

  transport.push('{"id":1,"result":{}}\n{"id":2,"result":{"busy":false}}\n');
  await a;
  assert.deepEqual(await b, { busy: false });
});

test("an error reply rejects with the backend's code", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();

  const call = backend.call("send", { text: "Hi" });
  transport.push(
    '{"id":1,"error":{"code":"rejected","message":"no provider configured"}}\n',
  );
  await assert.rejects(call, (err: Error) => {
    assert.equal(err.name, "rejected");
    assert.equal(err.message, "no provider configured");
    return true;
  });
});

test("a message split across chunks is buffered until complete", async () => {
  // A real pipe delivers arbitrary boundaries. Parsing a partial line would
  // drop the message and hang the caller forever.
  const { transport, backend } = makeBackend();
  await backend.start();

  const call = backend.call("ping");
  transport.push('{"id":1,"res');
  transport.push('ult":{"pong":');
  transport.push("true}}\n");
  assert.deepEqual(await call, { pong: true });
});

test("events are dispatched to listeners, not treated as replies", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();

  const events: CoreEvent[] = [];
  backend.onEvent((e) => events.push(e));

  transport.push(
    '{"event":true,"type":"turn.started","seq":1,"turn_id":"t1","payload":{}}\n',
  );
  transport.push(
    '{"event":true,"type":"message.delta","seq":2,"turn_id":"t1","payload":{"text":"Hi"}}\n',
  );

  assert.equal(events.length, 2);
  assert.equal(events[0].type, "turn.started");
  assert.equal(events[1].payload.text, "Hi");
});

test("several events in one chunk are all delivered", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  const events: CoreEvent[] = [];
  backend.onEvent((e) => events.push(e));

  transport.push(
    '{"event":true,"type":"message.delta","seq":1,"turn_id":"t","payload":{}}\n' +
      '{"event":true,"type":"message.delta","seq":2,"turn_id":"t","payload":{}}\n' +
      '{"event":true,"type":"turn.finished","seq":3,"turn_id":"t","payload":{}}\n',
  );
  assert.equal(events.length, 3);
  assert.equal(events[2].type, "turn.finished");
});

test("the reply to send arrives before that turn's events", async () => {
  // The ordering guarantee the UI depends on: the reply frame is *written*
  // before the event frames, so a turn id is known before the first delta.
  //
  // This asserts the order frames leave the transport, not the order promises
  // settle - promise callbacks are microtasks and run after the synchronous
  // push that delivered the event.
  const { transport, backend } = makeBackend();
  await backend.start();
  const wire: string[] = [];
  const realPush = transport.push.bind(transport);
  transport.push = (text: string) => {
    for (const line of text.split("\n")) {
      if (line.trim()) wire.push(line);
    }
    realPush(text);
  };

  const turnId = backend.send("Hi");
  transport.push('{"id":1,"result":{"turn_id":"abc"}}\n');
  transport.push(
    '{"event":true,"type":"message.delta","seq":1,"turn_id":"abc","payload":{"text":"Hi"}}\n',
  );

  assert.equal(await turnId, "abc");
  // Frame 0 is the reply, frame 1 the event it precedes.
  assert.equal(JSON.parse(wire[0]).id, 1);
  assert.equal(JSON.parse(wire[0]).result.turn_id, "abc");
  assert.equal(JSON.parse(wire[1]).event, true);
  assert.equal(JSON.parse(wire[1]).turn_id, "abc");
});

test("unsubscribing stops delivery", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  const events: CoreEvent[] = [];
  const off = backend.onEvent((e) => events.push(e));

  transport.push('{"event":true,"type":"log","seq":1,"turn_id":null,"payload":{}}\n');
  off();
  transport.push('{"event":true,"type":"log","seq":2,"turn_id":null,"payload":{}}\n');
  assert.equal(events.length, 1);
});

test("non-JSON output is surfaced as a log line, not a crash", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  const logs: string[] = [];
  backend.onLog((line) => logs.push(line));

  transport.push("this is not json\n");
  assert.equal(logs.length, 1);
  assert.match(logs[0], /non-json/);

  // The client must still work afterwards. Echo back the id it actually
  // allocated rather than assuming one: hardcoding an id here silently
  // tested nothing once a previous call in the same backend consumed it.
  const call = backend.call("ping");
  const id = JSON.parse(transport.written[transport.written.length - 1]).id;
  transport.push(JSON.stringify({ id, result: { pong: true } }) + "\n");
  assert.deepEqual(await call, { pong: true });
});

test("stderr is routed to logs and never parsed as protocol", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  const logs: string[] = [];
  const events: CoreEvent[] = [];
  backend.onLog((line) => logs.push(line));
  backend.onEvent((e) => events.push(e));

  transport.pushStderr("DEBUG something happened\n");
  assert.deepEqual(logs, ["DEBUG something happened"]);
  assert.equal(events.length, 0);
});

test("a dead backend rejects in-flight calls instead of hanging", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  const call = backend.call("ping");
  transport.simulateExit();
  await assert.rejects(call, /exited/);
});

test("calling before start fails fast with an actionable message", async () => {
  const { backend } = makeBackend();
  await assert.rejects(backend.call("ping"), /not running/);
});

test("stop kills the transport", async () => {
  const { transport, backend } = makeBackend();
  await backend.start();
  await backend.stop();
  assert.equal(transport.killed, true);
});

test("start/stop/start leaves a working transport, not a stale one", async () => {
  /**
   * Regression: React 19 StrictMode mounts, unmounts and remounts every
   * effect in development, so start -> stop -> start really does happen.
   *
   * `stop()` used to null `this.transport` only after awaiting `kill()`, so
   * the second `start()` saw a non-null transport and returned early without
   * spawning. Every later request then failed with "sidecar not started" while
   * a real, unowned sidecar kept running. The window showed "disconnected"
   * forever and the only symptom in the console was a rejected promise.
   */
  const made: FakeTransport[] = [];
  const backend = new TauriBackend(() => {
    const transport = new FakeTransport();
    made.push(transport);
    return transport;
  });

  await backend.start();
  await backend.stop();
  await backend.start();

  assert.equal(made.length, 2, "the second start must spawn its own sidecar");
  assert.equal(made[0].killed, true, "the first sidecar must be reaped");

  // The real proof: a request must reach the live transport, not a dead one.
  const call = backend.call("ping");
  assert.equal(made[1].written.length, 1);
  made[1].push(`${JSON.stringify({ id: 1, result: { pong: true } })}
`);
  assert.deepEqual(await call, { pong: true });
});

test("a replaced sidecar's late exit does not kill its replacement", async () => {
  /**
   * Regression: the actual cause of "Backend is not running" under
   * StrictMode, found by tracing the live window.
   *
   * A sidecar's exit event arrives asynchronously, so the transport killed by
   * `stop()` reports "exited" *after* its replacement is already assigned.
   * `onExit` used to null `this.transport` unconditionally, so the stale event
   * disposed of the healthy new backend. The window sat on "disconnected"
   * while a working sidecar ran unowned, and the only trace was a rejected
   * promise in the console.
   */
  const made: FakeTransport[] = [];
  const backend = new TauriBackend(() => {
    const transport = new FakeTransport();
    made.push(transport);
    return transport;
  });

  await backend.start();
  await backend.stop();
  await backend.start();

  // The stale sidecar finally reports in, late, after its replacement is up.
  made[0].simulateExit();

  const call = backend.call("ping");
  assert.equal(made[1].written.length, 1, "the live transport must still be usable");
  made[1].push(`${JSON.stringify({ id: 1, result: { pong: true } })}
`);
  assert.deepEqual(await call, { pong: true });
});

test("the live sidecar's exit still tears the backend down", async () => {
  /**
   * The staleness guard must not become a way to survive a real crash: when
   * the *current* transport dies, in-flight calls have to reject rather than
   * hang forever.
   */
  const transport = new FakeTransport();
  const backend = new TauriBackend(() => transport);
  await backend.start();

  const call = backend.call("ping");
  transport.simulateExit();
  await assert.rejects(call, /exited/);
  await assert.rejects(backend.call("ping"), /not running/);
});

test("a failed start does not wedge later starts", async () => {
  /**
   * The lifecycle is a promise chain, so a rejection must not poison it --
   * otherwise one failed spawn would make every later start a silent no-op.
   */
  let attempt = 0;
  const good = new FakeTransport();
  const backend = new TauriBackend(() => {
    attempt += 1;
    if (attempt === 1) {
      return {
        start: async () => {
          throw new Error("spawn refused");
        },
        write: async () => {},
        onStdout: () => {},
        onStderr: () => {},
        onExit: () => {},
        kill: async () => {},
      } satisfies LineTransport;
    }
    return good;
  });

  await assert.rejects(backend.start(), /spawn refused/);
  await backend.start();
  const call = backend.call("ping");
  assert.equal(good.written.length, 1);
  good.push(`${JSON.stringify({ id: 1, result: { pong: true } })}
`);
  assert.deepEqual(await call, { pong: true });
});
