/**
 * A fake core, for looking at the window without one.
 *
 * `app/dist` renders hostless by design, but "hostless" means the shell and the
 * launchpad: a transcript needs events, and events need a core. This file is the
 * smallest thing that can play one -- it installs `window.pywebview.api`, answers
 * the handful of requests the window makes at boot, and replays a scripted turn
 * on `send`.
 *
 * **It is a fixture, not a second implementation.** It answers with the shapes
 * `CoreBackend` already parses, and every payload here is copied from what the
 * core actually emits -- `tool.completed`'s `result` is a `ToolResult.to_dict()`,
 * a child's frames carry `parent_call_id`, and `turn.usage` arrives before
 * `turn.finished`. Nothing in it is a claim about the protocol; it is a tape.
 *
 * Injected by `scripts/capture_window.py --preview` before the page loads, so
 * `bridge.ts` finds a host on its first read rather than waiting out its
 * three-second timeout.
 *
 * The turn it plays is the one Phase 4 has to keep looking right: prose, a
 * parallel batch of two calls, a failure, a nested subagent, an edit with a
 * diff, and a plan that is half done.
 */
(() => {
  const TURN = "preview-turn";
  const CHILD = "preview-child";
  const START = Date.UTC(2026, 9, 26, 12, 0, 0) / 1000;

  let seq = 0;
  let push = null;

  const conversation = (id, title, updated, project) => ({
    id,
    title,
    project,
    created_at: START - 86400,
    updated_at: updated,
    message_count: 6,
    track: "build",
  });

  const PROJECT = "C:/Users/tony/work/tonyagent";

  const REPLIES = {
    ping: { ok: true },
    state: {
      provider: "openrouter",
      model: "anthropic/claude-sonnet-4",
      base_url: "",
      bound: true,
      project: PROJECT,
      mode: "build",
      permission: "medium",
      conversation: "preview-chat",
      sandbox: "stopped",
    },
    "providers.list": {
      providers: [{ id: "openrouter", name: "OpenRouter", has_key: true }],
    },
    "conversations.list": {
      conversations: [
        conversation("preview-chat", "Provider registry refactor", START + 120, PROJECT),
        conversation("preview-chat-2", "Sandbox timeouts", START - 3600, PROJECT),
        conversation("preview-chat-3", "Token accounting", START - 7200, PROJECT),
      ],
    },
    "mode.list": {
      modes: [
        { name: "build", label: "Build", writes: true },
        { name: "plan", label: "Plan", writes: false },
      ],
      mode: "build",
    },
    "tools.get": { max_tool_calls: 10 },
    "reasoning.list": {
      supported: true,
      efforts: ["low", "medium", "high"],
      default_effort: "medium",
      mandatory: false,
      effort: "medium",
    },
    "permission.list": {
      permission: "medium",
      permissions: [
        { name: "low", label: "Low", description: "Read, search and browse.", runs_commands: false, skips_confirmation: false, runs_any_command: false },
        { name: "medium", label: "Medium", description: "Edit files. Shell commands are refused.", runs_commands: false, skips_confirmation: false, runs_any_command: false },
        { name: "high", label: "High", description: "Everything, including running any command.", runs_commands: true, skips_confirmation: false, runs_any_command: true },
        { name: "full", label: "Full", description: "Everything, without asking, and any command.", runs_commands: true, skips_confirmation: true, runs_any_command: true, runs_on_host: true },
      ],
    },
    "skills.list": {
      skills: [
        { name: "review", description: "Read a diff the way a reviewer does.", source: "project", path: PROJECT + "/.tonyagent/skills/review.md" },
        { name: "release", description: "Cut a version and write the notes.", source: "project", path: PROJECT + "/.tonyagent/skills/release.md" },
        { name: "explain", description: "Explain a file to someone new to it.", source: "user", path: "C:/Users/tony/.tonyagent/skills/explain.md" },
        { name: "triage", description: "Turn a bug report into a failing test.", source: "user", path: "C:/Users/tony/.tonyagent/skills/triage.md" },
      ],
    },
    "plan.get": {
      plan: {
        goal: "Make the provider registry treat chat-only providers as a kind, not a flag",
        goal_status: "active",
        goal_note: "",
        todos: [
          { text: "Read the registry and the provider base", status: "completed" },
          { text: "Find every chat_only check", status: "completed" },
          { text: "Move the gate into the registry", status: "in_progress" },
          { text: "Update the factory's filters", status: "pending" },
          { text: "Run the provider suites", status: "pending" },
          { text: "Write the handoff", status: "pending" },
          { text: "Sweep the docs for the old flag", status: "pending" },
        ],
      },
      summary: "2/7 done",
      rendered: "2/7 done",
    },
    "context.get": {
      model: "anthropic/claude-sonnet-4",
      used: 62400,
      known: true,
      window: 124000,
    },
    "usage.summary": {
      window: "7d",
      since: START - 604800,
      totals: { requests: 42, failed: 1, input_tokens: 812000, output_tokens: 96000, reasoning_tokens: 12000, total_tokens: 908000, duration_ms: 512000 },
      buckets: [],
      by_key: [],
      by_provider: [],
      by_model: [],
      tracking_since: START - 604800,
    },
    "files.tree": {
      entries: [
        { path: "src", name: "src", kind: "dir", depth: 0 },
        { path: "src/providers", name: "providers", kind: "dir", depth: 1 },
        { path: "src/providers/base.py", name: "base.py", kind: "file", depth: 2 },
        { path: "src/providers/registry.py", name: "registry.py", kind: "file", depth: 2 },
        { path: "README.md", name: "README.md", kind: "file", depth: 0 },
      ],
    },
    "conversations.switch": { conversation: conversation("preview-chat", "Provider registry refactor", START + 120, PROJECT) },
  };

  const frame = (type, payload, turnId, extra) =>
    JSON.stringify({ event: true, type, seq: (seq += 1), turn_id: turnId || null, payload, ...(extra || {}) });

  const say = (...frames) => push && push(frames);

  const result = (status, output, summary, extra) => ({
    status,
    output,
    summary,
    error: status === "error" ? output : null,
    artifacts: [],
    duration_ms: 120,
    ...(extra || {}),
  });

  const budget = (n) => ({ label: `Tool call ${n}/10`, used: n, limit: 10 });

  /** The scripted turn, in the order the core would emit it. */
  function playTurn() {
    const at = (ms, fn) => window.setTimeout(fn, ms);

    say(frame("turn.started", { model: "anthropic/claude-sonnet-4" }, TURN));
    at(60, () => {
      say(frame("message.started", {}, TURN));
      say(frame("message.delta", { text: "I'll start by reading the registry and the provider base, then find every place that checks " }, TURN));
      say(frame("message.delta", { text: "`chat_only`." }, TURN));
      say(frame("message.completed", { text: "I'll start by reading the registry and the provider base, then find every place that checks `chat_only`." }, TURN));
    });

    at(160, () => {
      say(frame("tool.started", { id: "c1", name: "read_file", arguments: { path: "src/providers/base.py" } }, TURN));
      say(frame("tool.completed", { id: "c1", name: "read_file", result: result("success", "…", "Read 412 lines"), tool_call_budget: budget(1) }, TURN));
    });

    // A parallel batch: two calls start together and finish out of order, which
    // is the shape a sequential renderer gets wrong.
    at(280, () => {
      say(frame("tool.started", { id: "c2", name: "grep", arguments: { pattern: "chat_only" } }, TURN));
      say(frame("tool.started", { id: "c3", name: "read_file", arguments: { path: "src/providers/registry.py" } }, TURN));
    });
    at(420, () => {
      say(frame("tool.completed", { id: "c3", name: "read_file", result: result("success", "…", "Read 190 lines"), tool_call_budget: budget(3) }, TURN));
      say(frame("tool.completed", { id: "c2", name: "grep", result: result("success", "…", "6 matches in 4 files"), tool_call_budget: budget(2) }, TURN));
    });

    // A failure, because a row that only ever says "ok" is not a row.
    at(500, () => {
      say(frame("tool.started", { id: "c4", name: "run_command", arguments: { command: "pytest -q tests/unit/test_providers.py" } }, TURN));
      say(frame("tool.completed", { id: "c4", name: "run_command", result: result("error", "No such file: tests/unit/test_providers.py", "No such file"), tool_call_budget: budget(4) }, TURN));
    });

    // A child session: its own turn id, and the parent call it belongs to.
    at(580, () => {
      say(frame("tool.started", { id: "c5", name: "subagent", arguments: { task: "Find the factory's chat-only filters" } }, TURN));
      say(frame("turn.started", { model: "anthropic/claude-sonnet-4" }, CHILD, { subagent: "scout", parent_call_id: "c5" }));
      say(frame("message.delta", { text: "Checking the factory for the same flag." }, CHILD, { subagent: "scout", parent_call_id: "c5" }));
      say(frame("tool.started", { id: "k1", name: "grep", arguments: { pattern: "chat_only" } }, CHILD, { subagent: "scout", parent_call_id: "c5" }));
      say(frame("tool.completed", { id: "k1", name: "grep", result: result("success", "…", "2 matches in factory.py"), tool_call_budget: budget(1) }, CHILD, { subagent: "scout", parent_call_id: "c5" }));
      say(frame("message.completed", { text: "Checking the factory for the same flag. It filters in `available_providers`." }, CHILD, { subagent: "scout", parent_call_id: "c5" }));
      say(frame("turn.finished", {}, CHILD, { subagent: "scout", parent_call_id: "c5" }));
    });
    at(760, () => {
      say(frame("tool.completed", { id: "c5", name: "subagent", result: result("success", "…", "It filters in available_providers"), tool_call_budget: budget(5) }, TURN));
    });

    // An edit, with the file_change artifact the Files pane reads.
    at(840, () => {
      say(frame("tool.started", { id: "c6", name: "edit_file", arguments: { path: "src/providers/registry.py" } }, TURN));
      say(frame("tool.completed", {
        id: "c6",
        name: "edit_file",
        result: result("success", "…", "Edited registry.py", {
          artifacts: [
            {
              type: "file_change",
              data: {
                path: "src/providers/registry.py",
                added: 12,
                removed: 3,
                // The core computes a real unified diff for an edit; the tape
                // carries a short one so the expanded row's Diff block is
                // exercised rather than only its Arguments block.
                diff: "@@ -18,7 +18,9 @@ def available_providers(\n-    return [p for p in _ALL if not p.chat_only]\n+    return [p for p in _ALL if p.kind != \"chat-only\"]\n",
              },
            },
          ],
        }),
        tool_call_budget: budget(6),
      }, TURN));
    });

    at(920, () => {
      say(frame("message.started", {}, TURN));
      say(frame("message.completed", { text: "The registry now owns the gate. `chat_only` is a property of the provider kind, so `available_providers` no longer needs its own filter." }, TURN));
      /*
       * `window.__tonyAskPermission` stops the tape on a pending confirmation
       * instead of finishing the turn.
       *
       * The blocked state is the one a capture cannot otherwise reach: it needs
       * the core to stop mid-turn and wait, which nothing in a page can fake.
       * Set by `capture_window.py --ask` before Send.
       */
      if (window.__tonyAskPermission) {
        say(frame("tool.started", { id: "c7", name: "write_file", arguments: { path: "src/providers/registry.py" } }, TURN));
        say(
          frame(
            "confirmation.requested",
            {
              id: "c7",
              name: "write_file",
              arguments: { path: "src/providers/registry.py", content: "…" },
              description: "Write src/providers/registry.py",
              destructive: false,
            },
            TURN,
          ),
        );
        return;
      }
      say(frame("turn.usage", { input_tokens: 12400, output_tokens: 1240, reasoning_tokens: 400, cost: 0.0042 }, TURN));
      say(frame("turn.finished", {}, TURN));
    });
  }

  function answer(line) {
    let request;
    try {
      request = JSON.parse(line);
    } catch {
      return;
    }
    if (request.method === "send") {
      window.setTimeout(() => push && push([JSON.stringify({ id: request.id, result: { turn_id: TURN } })]), 10);
      playTurn();
      return;
    }
    if (request.method === "cancel") {
      window.setTimeout(() => push && push([JSON.stringify({ id: request.id, result: { cancelled: true } })]), 10);
      return;
    }
    const reply = REPLIES[request.method];
    window.setTimeout(() => {
      if (reply === undefined) {
        push && push([JSON.stringify({ id: request.id, error: { message: `no preview for ${request.method}` } })]);
        return;
      }
      push && push([JSON.stringify({ id: request.id, result: reply })]);
    }, 5);
  }

  const noop = async () => ({});
  window.pywebview = {
    api: {
      ready: async () => {
        // The handlers are installed by the time `ready()` is called; that is
        // the order `CoreBackend.start` uses, and this is the earliest moment
        // the page can receive a frame.
        push = (lines) => window.__tonyAgent && window.__tonyAgent.onFrames(lines);
        return {};
      },
      send: async (line) => {
        answer(line);
        return {};
      },
      core_alive: async () => ({ alive: true }),
      window_control: async () => ({ maximized: false }),
      window_state: async () => ({ maximized: false }),
      system_menu: async () => ({ maximized: false }),
      pick_folder: async () => ({ path: null }),
      pick_files: async () => ({ paths: [] }),
      open_account_view: async (view) => ({ view, url: "", opened: false }),
      read_account_view: async (view) => ({ view, url: "", ok: false, signed_out: false, figures: [], read_at: 0 }),
      pet: async () => ({ open: false, wanted: false }),
      update_install: async () => ({ started: false, reason: "", path: "" }),
      open_releases: async () => ({ url: "", opened: false }),
      open_logs: async () => ({ path: "", opened: false }),
      open_path: async (path) => ({ path, opened: false }),
    },
  };
  void noop;
})();
