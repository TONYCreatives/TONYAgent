/**
 * A static preview of the Agent/Code mode switch, for looking at it.
 *
 * Not part of the app -- `vite.config.ts` builds `index.html` and `pet.html`,
 * and this page is deliberately not one of them. Run `npm run dev` in `app/`
 * and open `/code-preview.html` (Vite's dev server serves any page in the
 * root); what it mounts is the
 * real `App` with the real stylesheets, and the only thing it fakes is the
 * core, because a page open in a browser has no window host to talk to
 * (`makeHostTransport` throws there, which is the honest answer in a browser).
 *
 * It exists because "the whole screen changes" is a question about columns,
 * widths and chrome that no DOM assertion answers: `App.test.tsx` can prove the
 * rail and the tab strip are unmounted, and it cannot prove the window *looks*
 * like an editor when they are.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.js";
import { CoreBackend, type LineTransport, type CoreRequest } from "./backend.js";
import "./styles.css";

const PROJECT = "C:/work/tonyagent";
const OPEN = "a".repeat(32);

const ENTRIES = [
  { path: ".tonyagent", kind: "dir" },
  { path: ".tonyagent/skills", kind: "dir" },
  { path: ".tonyagent/skills/review.md", kind: "file" },
  { path: "app", kind: "dir" },
  { path: "app/src", kind: "dir" },
  { path: "app/src/App.tsx", kind: "file" },
  { path: "app/src/CodeViewer.tsx", kind: "file" },
  { path: "app/src/FileSidebar.tsx", kind: "file" },
  { path: "app/src/TopBar.tsx", kind: "file" },
  { path: "app/src/styles", kind: "dir" },
  { path: "app/src/styles/code-viewer.css", kind: "file" },
  { path: "app/index.html", kind: "file" },
  { path: "src", kind: "dir" },
  { path: "src/tonyagent", kind: "dir" },
  { path: "src/tonyagent/tools", kind: "dir" },
  { path: "src/tonyagent/tools/browser_tools.py", kind: "file" },
  { path: "src/tonyagent/tools/file_tools.py", kind: "file" },
  { path: "README.md", kind: "file" },
  { path: "pyproject.toml", kind: "file" },
];

/**
 * Files the tree can open, by path.
 *
 * More than one, because a viewer is judged on the languages it draws: a
 * stylesheet and a page with a `<style>` block in it are the two cases a
 * palette is either right or wrong about, and a preview that could only show
 * TypeScript could not answer "is the CSS coloured now".
 */
const FILES: Record<string, { content: string; language: string }> = {
  "app/src/styles/code-viewer.css": {
    language: "css",
    content: [
      "/* The code viewer's chrome, and the one number two rules share. */",
      ".code-viewer {",
      "  display: flex;",
      "  flex: 1;",
      "  flex-direction: column;",
      "  min-height: 0;",
      "  --code-gutter: 58px;",
      "}",
      "",
      ".code-header,",
      "body > .app[data-mode='code'] .code-header {",
      "  display: flex;",
      "  align-items: center;",
      "  gap: 8px;",
      "  height: 38px;",
      "  padding: 0 10px;",
      "  border-bottom: 1px solid var(--border-soft);",
      "  background: var(--chrome);",
      "}",
      "",
      "@media (min-width: 40rem) {",
      "  .code-input:focus-visible {",
      "    outline-offset: -2px;",
      "  }",
      "}",
      "",
    ].join("\n"),
  },
  "app/index.html": {
    language: "html",
    content: [
      "<!doctype html>",
      '<html lang="en">',
      "  <head>",
      "    <meta charset=\"UTF-8\" />",
      "    <title>TONYAgent</title>",
      "    <style>",
      "      /* The page's own chrome, highlighted as CSS and not as markup. */",
      "      html, body, #root {",
      "        height: 100%;",
      "        margin: 0;",
      "      }",
      "      .app[data-mode='code'] {",
      "        grid-template-columns: var(--code-side-w) minmax(0, 1fr) !important;",
      "      }",
      "    </style>",
      "  </head>",
      "  <body>",
      "    <div id=\"root\"></div>",
      "    <script type=\"module\">",
      "      const container = document.getElementById('root');",
      "      if (!container) throw new Error('#root is missing');",
      "    </script>",
      "  </body>",
      "</html>",
      "",
    ].join("\n"),
  },
};

const SOURCE = [
  "# FileSidebar",
  "",
  "The Files pane of the left sidebar: the project tree.",
  "",
  "It used to list only the files the agent had *touched*, built from tool",
  "artifacts -- which meant a file nobody had opened yet could not be reached",
  "at all, and the pane was a session log wearing a tree's clothes.",
  "",
  "const rows = useMemo(",
  "  () => buildTree(entries, changes, collapsed, filter),",
  "  [entries, changes, collapsed, filter],",
  ");",
  "",
].join("\n");

/** The answers a core would give, for the handful of calls the window makes. */
const ANSWERS: Record<string, unknown> = {
  state: {
    provider: "openrouter",
    model: "stealth/space-bunny-alpha",
    base_url: "",
    bound: true,
    project: PROJECT,
    mode: "build",
    permission: "medium",
    conversation: OPEN,
    sandbox: "stopped",
  },
  "providers.list": {
    providers: [{ id: "openrouter", name: "OpenRouter", has_key: true }],
  },
  "conversations.list": {
    conversations: [
      {
        id: OPEN,
        title: "Make the mode switch take over the window",
        project: PROJECT,
        created_at: 1_700_000_000,
        updated_at: 1_700_000_000,
        message_count: 4,
      },
      {
        id: "b".repeat(32),
        title: "Why does the deploy poller retry twice",
        project: PROJECT,
        created_at: 1_700_000_000,
        updated_at: 1_700_000_000,
        message_count: 2,
      },
    ],
  },
  "mode.list": {
    modes: [
      { name: "build", label: "Build", description: "Full access.", writes: true },
      { name: "plan", label: "Plan", description: "Read only.", writes: false },
    ],
    mode: "build",
  },
  "tools.get": { max_tool_calls: 10 },
  "reasoning.list": null,
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
        runs_on_host: true,
      },
    ],
  },
  "usage.summary": {},
  "files.tree": { entries: ENTRIES, truncated: false },
};

/**
 * One turn, as the core would stream it.
 *
 * The fake core answered RPCs but never streamed anything, so this window could
 * only be looked at in the states reachable without a turn -- and a turn is
 * what the transcript exists for. This is deliberately the *shape* the ordering
 * work is about rather than a pretty answer: prose, two calls, more prose,
 * another call, a closing sentence. Every one of those has to be drawn where it
 * happened, and `after` frames the pauses between them.
 *
 * Payload keys are the core's, not invented here: `session.py` writes
 * `message.delta`/`message.completed` with `text`, `tool.started` with `id` and
 * `name`, and `tool.completed` with the result and the turn's budget label.
 */
const SCRIPT: Array<{ after: number; type: string; payload?: Record<string, unknown> }> = [
  { after: 0, type: "turn.started" },
  { after: 120, type: "message.started" },
  { after: 80, type: "reasoning.delta", payload: { text: "They want to know what the note says. " } },
  {
    after: 260,
    type: "reasoning.completed",
    payload: { text: "They want to know what the note says. Read it, then say." },
  },
  { after: 80, type: "message.delta", payload: { text: "Let me look at the note. " } },
  { after: 140, type: "message.completed", payload: { text: "Let me look at the note. " } },
  { after: 120, type: "tool.started", payload: { id: "c1", name: "read_file" } },
  {
    after: 380,
    type: "tool.completed",
    payload: {
      id: "c1",
      result: { status: "success", output: "Read 12 lines from notes.md" },
      tool_call_budget: { label: "Tool call 1/10" },
    },
  },
  { after: 120, type: "tool.started", payload: { id: "c2", name: "search_text" } },
  {
    after: 320,
    type: "tool.completed",
    payload: {
      id: "c2",
      result: { status: "success", output: "2 matches in notes.md" },
      tool_call_budget: { label: "Tool call 2/10" },
    },
  },
  { after: 120, type: "message.started" },
  { after: 80, type: "message.delta", payload: { text: "It is a one-line note. " } },
  { after: 140, type: "message.completed", payload: { text: "It is a one-line note. " } },
  { after: 120, type: "tool.started", payload: { id: "c3", name: "edit_file" } },
  {
    after: 360,
    type: "tool.completed",
    payload: {
      id: "c3",
      result: {
        status: "success",
        output: "Written 1 line to notes.md",
        artifacts: [{ type: "file_change", data: { path: "notes.md", added: 1, removed: 0 } }],
      },
      tool_call_budget: { label: "Tool call 3/10" },
    },
  },
  { after: 120, type: "message.started" },
  { after: 80, type: "message.delta", payload: { text: "Done: " } },
  { after: 90, type: "message.delta", payload: { text: "the deploy poller retries twice." } },
  {
    after: 160,
    type: "message.completed",
    payload: { text: "Done: the deploy poller retries twice." },
  },
  { after: 80, type: "turn.finished" },
];

/**
 * `files.read` answers per path, so the tree can open anything it lists.
 *
 * The fake core is the only thing this page fakes, and "which file" is exactly
 * the question a viewer is judged on -- so it answers the real one.
 */
function readFile(path: string): unknown {
  const known = FILES[path];
  const content = known ? known.content : SOURCE;
  return {
    kind: "text",
    path,
    content,
    total_lines: content.split("\n").length - 1,
    language: known ? known.language : "typescript",
    size: content.length,
  };
}

/** A core that answers from a table, so the window boots without one. */
class FakeTransport implements LineTransport {
  private stdout: ((text: string) => void) | null = null;
  /** Frame numbering, so the window sees the bus's order. */
  private seq = 0;
  /** How many turns this page has run; only used to name them. */
  private turn = 0;

  async start(): Promise<void> {}

  async write(line: string): Promise<void> {
    const request = JSON.parse(line) as CoreRequest;

    // A message sent from the composer plays the scripted turn. The reply goes
    // out first, because a real core answers `send` and then streams: a turn
    // that began before the caller knew its id would be a turn nothing owns.
    if (request.method === "send") {
      this.turn += 1;
      const turnId = `preview-${this.turn}`;
      void this.playTurn(turnId);
      this.reply(request.id, { turn_id: turnId });
      return;
    }
    // Stop, as far as a page with no model can honour it.
    if (request.method === "cancel") {
      this.reply(request.id, {});
      return;
    }

    const result =
      request.method === "files.read"
        ? readFile(String((request.params as { path?: string })?.path ?? ""))
        : request.method in ANSWERS
          ? ANSWERS[request.method]
          : {};
    this.reply(request.id, result);
  }

  /** One line of protocol, as the core would write it. */
  private reply(id: unknown, result: unknown): void {
    setTimeout(() => {
      this.stdout?.(`${JSON.stringify({ id, result })}\n`);
    }, 0);
  }

  /**
   * Stream the scripted turn, one frame at a time.
   *
   * On timers rather than all at once, so the turn can actually be watched: the
   * stop button is only on screen while a turn is running, and the order the
   * rows arrive in is the thing being looked at.
   */
  private async playTurn(turnId: string): Promise<void> {
    for (const step of SCRIPT) {
      await new Promise((resolve) => setTimeout(resolve, step.after));
      this.seq += 1;
      this.stdout?.(
        `${JSON.stringify({
          event: true,
          type: step.type,
          seq: this.seq,
          turn_id: turnId,
          payload: step.payload ?? {},
        })}\n`,
      );
    }
  }

  onStdout(fn: (text: string) => void): void {
    this.stdout = fn;
  }

  onStderr(): void {}
  onExit(): void {}
  async kill(): Promise<void> {}
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App
      backend={new CoreBackend(() => new FakeTransport())}
      pickProject={async () => PROJECT}
    />
  </StrictMode>,
);
