import { useEffect, useRef, useState } from "react";
import type { ChatMessage, SubagentChild, ReasonRun, ToolCall } from "./events.js";
import { MarkdownText } from "./MarkdownText.js";
import { formatDuration } from "./activity.js";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  /** Open a touched file in Code. The tool row's path chip calls it. */
  onOpenFile?: (path: string) => void;
  /**
   * The turn is stopped on a permission prompt.
   *
   * The core does not send a `running` call's id with the confirmation, so the
   * one running row in the spine is the row that is waiting: it takes the amber
   * node instead of the live one. Two parallel calls both turning amber is the
   * honest reading -- the turn *is* blocked, whatever either call is doing.
   */
  awaitingApproval?: boolean;
}

const STATUS_MARK: Record<"running" | "ok" | "failed", string> = {
  running: "*",
  ok: "+",
  failed: "!",
};

/**
 * Is this the last call the turn can afford?
 *
 * Parsed out of the label rather than carried as a field, because the label
 * is what the core sends and the two could otherwise disagree. The threshold
 * is the last two calls, not one: a model that gets refused on the call it
 * was told it could make has already wasted that call, and the warning that
 * would have helped arrived one step too late.
 */
function isNearLimit(budget: string): boolean {
  const match = /^Tool call (\d+)\/(\d+)$/.exec(budget);
  if (!match) return false;
  const index = Number(match[1]);
  const limit = Number(match[2]);
  if (limit <= 0) return false;
  return index >= limit - 1;
}

/**
 * A subagent's own work, nested under the call that spawned it.
 *
 * The child is not a second assistant: its frames arrive tagged with this
 * call's id (`parent_call_id`) and land here, so a reader sees what the
 * subagent actually did -- the tools it ran, the answer it returned -- as the
 * work of *that call*, not as something the assistant said. While the child is
 * still running the header says so; the card itself finishes when the parent's
 * call returns, which is what its own status and detail report.
 */
function SubagentWork({ child }: { child: SubagentChild }) {
  return (
    <div className={`subagent${child.running ? " is-running" : ""}`}>
      <div className="subagent-head">
        <span className="subagent-name">{child.name || "subagent"}</span>
        <span className="subagent-state">{child.running ? "working\u2026" : "answered"}</span>
      </div>
      {child.tools.length > 0 && (
        <div className="subagent-tools">
          {child.tools.map((call) => (
            <div key={call.id} className={`subagent-tool subagent-tool-${call.status}`}>
              <span className="tool-mark" aria-hidden="true">
                {STATUS_MARK[call.status]}
              </span>
              <span className="tool-name">{call.name}</span>
              {call.detail && <span className="tool-detail">{call.detail}</span>}
            </div>
          ))}
        </div>
      )}
      {child.text && (
        <div className="subagent-answer">
          <MarkdownText text={child.text} />
        </div>
      )}
    </div>
  );
}

/**
 * One thing the turn did, in the order it did it.
 *
 * A transcript line is either a piece of the model's prose, a run of tool calls
 * with nothing said in between, or a single thinking pass. Consecutive calls are
 * one run, because a model that asks for five tools in one message asked for
 * them together, and five rows in one tight block is what that looked like.
 * Thinking is never grouped: each pass is its own block, because two passes are
 * two separate trains of thought with work between them.
 */
type Run =
  | { kind: "text"; text: string }
  | { kind: "tools"; tools: ChatMessage["tools"] }
  | { kind: "thinking"; run: ReasonRun };

/**
 * Split one assistant message into the runs it is made of.
 *
 * A turn writes into a single message across several passes -- think, write,
 * call tools, think again, write more -- and *both* `ToolCall.after` and
 * `ReasonRun.after` record how much of the prose existed when that item began.
 * Merging the two by their mark and walking them together is what puts each
 * thought and each call under the words that preceded it, in the order they
 * happened, instead of stacking the turn's rows under its last paragraph (the
 * order it was *reported* in) or its thoughts into one block at the top.
 *
 * The merge is stable, so a set of tool calls sharing one mark -- every call the
 * model requested in a single message -- keeps its order and stays grouped.
 * Marks are clamped so a mark past the end of the prose cannot lose an item: a
 * dropped card is a worse lie than one in the wrong place.
 *
 * Whitespace-only prose pieces are dropped rather than rendered: they are the
 * newlines between paragraphs, and an empty block would show as a gap.
 *
 * A message with no `reasonRuns` -- hand-built, or restored from before they
 * existed -- emits no thinking run here; its flat `reasoning` is drawn once at
 * the top by `Bubble`, which is where every thought used to go.
 */
function runsOf(message: ChatMessage): Run[] {
  // Every item that has a mark, tagged so the walk below can tell them apart.
  type Marked = { at: number; seq: number; tool?: ToolCall; run?: ReasonRun };
  const marked: Marked[] = [];
  message.tools.forEach((tool, i) =>
    marked.push({ at: tool.after ?? message.text.length, seq: i, tool }),
  );
  (message.reasonRuns ?? []).forEach((run, i) =>
    // Placed after the tools, but the sort below reorders by `at` anyway; `seq`
    // only breaks ties within one kind.
    marked.push({ at: run.after, seq: message.tools.length + i, run }),
  );
  marked.sort((a, b) => a.at - b.at || a.seq - b.seq);

  const runs: Run[] = [];
  let pending: ChatMessage["tools"] = [];
  let cursor = 0;
  const flush = () => {
    if (pending.length > 0) runs.push({ kind: "tools", tools: pending });
    pending = [];
  };

  for (const item of marked) {
    const at = Math.max(cursor, item.at);
    if (at > cursor) {
      // The calls already collected happened *before* this prose, so they are
      // closed off here rather than after it.
      flush();
      const prose = message.text.slice(cursor, at);
      if (prose.trim() !== "") runs.push({ kind: "text", text: prose });
      cursor = at;
    }
    if (item.run) {
      // A thought breaks any pending run of calls: what came before it is
      // finished, and the thought stands on its own between them.
      flush();
      runs.push({ kind: "thinking", run: item.run });
    } else {
      pending.push(item.tool!);
    }
  }
  flush();

  const rest = message.text.slice(cursor);
  if (rest.trim() !== "") runs.push({ kind: "text", text: rest });
  return runs;
}

/**
 * One tool invocation: a status node in the gutter, a row, and what it did
 * underneath when the reader asks.
 *
 * **The row is one line and the body is opt-in.** A turn that reads four files,
 * greps twice and edits one produces seven rows, and a card per row with its
 * output in it is a page of logs rather than a transcript -- which is exactly
 * what this replaces. Collapsed, a row says what ran, what came back and how
 * long it took; pressing it opens the arguments, the result and the diff.
 *
 * **The node is in the gutter, not in the row.** It is positioned against the
 * column's left edge and lives in the 22px of air outside `--measure`, which is
 * what keeps the first character of every row on the same pixel as the first
 * character of the composer below it. A node inside the row would have indented
 * the row and broken the one alignment this window has protected throughout.
 *
 * **A running row says so and nothing else.** There is no live duration here:
 * the turn's clock is the Run card's, one timer for one number, and a per-row
 * ticker would be seven timers to draw seven numbers nobody is reading.
 */
function ToolRow({
  tool,
  onOpenFile,
  awaitingApproval = false,
}: {
  tool: ToolCall;
  onOpenFile?: (path: string) => void;
  awaitingApproval?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const running = tool.status === "running";
  const node = running && awaitingApproval ? "approval" : tool.status;
  const duration =
    tool.startedAt !== undefined && tool.endedAt !== undefined
      ? formatDuration(Math.max(0, tool.endedAt - tool.startedAt))
      : null;
  const summary = tool.detail ?? (running ? "running\u2026" : "");
  const hasBody = Boolean(tool.args || tool.output || tool.error || tool.diff);

  return (
    // `data-call-id` is the pane's anchor: a plan row scrolls here, so the
    // reader lands on the call that wrote the list rather than at the top of a
    // transcript that may be hundreds of rows long. It is an attribute rather
    // than an `id` because it is a lookup key, not a fragment target.
    <div className="tool-unit" data-call-id={tool.id}>
      <div className={`tool tool-${tool.status}`} data-open={open ? "true" : "false"}>
        {/* The spine's node. Decoration on the row's own state, which the row
            also says in words -- so it is hidden from the accessibility tree
            rather than being the only carrier of "this failed". */}
        <span className="tool-node" data-status={node} aria-hidden="true" />
        <button
          type="button"
          className="tool-toggle"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          disabled={!hasBody}
          title={hasBody ? (open ? "Hide the details" : "Show the arguments and result") : undefined}
        >
          <span className="tool-name">{tool.name}</span>
          {summary && <span className="tool-summary">{summary}</span>}
          {tool.budget && (
            // The number the model also read, so the reader can see the turn
            // approaching its limit rather than discovering it from an error.
            <span
              className={`tool-budget${isNearLimit(tool.budget) ? " is-near-limit" : ""}`}
              title="Tool calls used in this turn"
            >
              {tool.budget}
            </span>
          )}
          {duration && <span className="tool-duration">{duration}</span>}
          {hasBody && (
            <span className="tool-caret" aria-hidden="true">
              {open ? "\u25be" : "\u25b8"}
            </span>
          )}
        </button>
        {tool.path && (
          // A chip rather than a link: it opens Code at the file, which is a
          // different act from expanding the row it sits in. Kept out of the
          // toggle so the two presses cannot be confused, and out of the row's
          // own hit area so a press meant for the file does not fold the row.
          <button
            type="button"
            className="tool-path"
            onClick={() => onOpenFile?.(tool.path!)}
            disabled={!onOpenFile}
            title={onOpenFile ? `Open ${tool.path} in Code` : tool.path}
          >
            {fileName(tool.path)}
            {tool.added !== undefined && (
              <span className="tool-path-delta">
                <span className="add">+{tool.added}</span>
                <span className="del">{"\u2212"}{tool.removed ?? 0}</span>
              </span>
            )}
          </button>
        )}
      </div>

      {open && (
        <div className="tool-body">
          {tool.args && (
            <ToolBlock label="Arguments" text={tool.args} />
          )}
          {tool.error && <ToolBlock label="Error" text={tool.error} tone="bad" />}
          {tool.diff && <ToolBlock label="Diff" text={tool.diff} diff />}
          {!tool.diff && tool.output && <ToolBlock label="Result" text={tool.output} />}
        </div>
      )}

      {tool.child && <SubagentWork child={tool.child} />}
    </div>
  );
}

/** One labelled block of a tool row's body. */
function ToolBlock({
  label,
  text,
  tone,
  diff = false,
}: {
  label: string;
  text: string;
  tone?: "bad";
  diff?: boolean;
}) {
  return (
    <div className="tool-block" data-tone={tone}>
      <span className="tool-block-label">{label}</span>
      {diff ? (
        <pre className="tool-pre tool-diff">
          {text.split("\n").map((line, index) => (
            <span
              key={index}
              className={
                line.startsWith("+") ? "is-add" : line.startsWith("-") ? "is-del" : undefined
              }
            >
              {line}
              {"\n"}
            </span>
          ))}
        </pre>
      ) : (
        <pre className="tool-pre">{text}</pre>
      )}
    </div>
  );
}

/** The file's own name, for the path chip. The full path is on its title. */
function fileName(path: string): string {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut >= 0 ? path.slice(cut + 1) : path;
}

/**
 * What the model thought, drawn where it thought it.
 *
 * Open while the thinking is still arriving and folded once it is done: the
 * trace is often longer than the answer, and a transcript of a session where
 * every reply is twice its own length is one nobody reads. Folding it is not
 * discarding it -- the text stays on the message and reopens with a click, and
 * it is still in the saved conversation, so a reopened chat shows the same
 * thing this one did.
 *
 * Takes one pass's worth of thinking rather than the whole message, because a
 * turn can think several times -- before a tool call, then again before the
 * answer -- and each pass belongs at its own place in the transcript (see
 * `runsOf`). A message that only has flat `reasoning` (hand-built, or restored
 * from before passes existed) passes that whole string as one pass, which is
 * the old single-block behaviour.
 *
 * Rendered only when there is something to show. A model that does not
 * reason gets no panel, not an empty one, because a permanently collapsed
 * "Thinking" header on every answer is furniture the user has to learn to
 * ignore.
 */
function ThinkingPanel({ pass }: { pass: ReasonRun }) {
  const hasReasoning = pass.text.trim() !== "";
  // Born folded if this pass arrived with its thinking already complete, open
  // if it is still arriving.
  const [open, setOpen] = useState(!pass.complete);
  // Set once the reader has made their own choice, so finishing the stream
  // does not fold a panel they opened on purpose.
  const touched = useRef(false);

  useEffect(() => {
    if (pass.complete && !touched.current) setOpen(false);
  }, [pass.complete]);

  if (!hasReasoning && !pass.truncated) return null;

  const toggle = () => {
    touched.current = true;
    setOpen((was) => !was);
  };

  return (
    <div className={`thinking${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="thinking-head"
        onClick={toggle}
        aria-expanded={open}
      >
        <span className="thinking-caret">{open ? "▾" : "▸"}</span>
        <span>Thinking</span>
        {pass.truncated && (
          // The turn produced no answer at all; the notice below says why, and
          // the badge says it without having to open anything.
          <span className="thinking-warn" title={pass.notice}>
            ran out of budget
          </span>
        )}
        {!pass.complete && <span className="thinking-live">…</span>}
      </button>
      {pass.notice && <p className="thinking-notice">{pass.notice}</p>}
      {open && hasReasoning && <div className="thinking-body">{pass.text}</div>}
    </div>
  );
}

function Bubble({
  message,
  streaming,
  onOpenFile,
  awaitingApproval,
}: {
  message: ChatMessage;
  /** The model is still writing into this message. */
  streaming: boolean;
  onOpenFile?: (path: string) => void;
  awaitingApproval?: boolean;
}) {
  const isUser = message.role === "user";
  // A message that carries thinking as placed runs draws each pass inline, in
  // order, between the prose and calls it belongs with. One that only has the
  // flat field -- hand-built, or restored from before passes existed -- draws
  // that whole string once at the top, which is where every thought used to go.
  // A truncated turn qualifies even with no text: it has something to explain.
  const placed = message.reasonRuns?.length ? message.reasonRuns : null;
  const legacyPass: ReasonRun | null =
    !placed && (message.reasoning.trim() !== "" || message.reasoningTruncated)
      ? {
          text: message.reasoning,
          after: 0,
          complete: message.reasoningComplete,
          truncated: message.reasoningTruncated,
          notice: message.reasoningNotice,
        }
      : null;
  return (
    <div className={`row ${isUser ? "row-user" : "row-assistant"}`}>
      <div className={`bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
        {!isUser && legacyPass && <ThinkingPanel pass={legacyPass} />}
        {/*
          Only assistant text is Markdown. A user's message is shown exactly as
          typed -- someone pasting `**not bold**` meant the asterisks.

          An assistant turn is drawn as its runs, in order: the prose, the tool
          rows, and each thinking pass alternate exactly as the model produced
          them. A user's message has no runs to draw and one piece of text.
        */}
        {isUser
          ? message.text && <div className="bubble-text">{message.text}</div>
          : (() => {
              const runs = runsOf(message);
              return runs.map((run, index) =>
                run.kind === "text" ? (
                  <MarkdownText
                    key={index}
                    text={run.text}
                    // The caret follows the *last* run, and only while that run
                    // is prose: a turn that is mid-tool-call is not writing,
                    // and a caret parked under a paragraph while a tool runs
                    // says the opposite.
                    caret={streaming && index === runs.length - 1}
                  />
                ) : run.kind === "thinking" ? (
                  <ThinkingPanel key={index} pass={run.run} />
                ) : (
                  <div className="tools" data-spine="true" key={index}>
                    {run.tools.map((tool) => (
                      <ToolRow
                        key={tool.id}
                        tool={tool}
                        onOpenFile={onOpenFile}
                        awaitingApproval={awaitingApproval}
                      />
                    ))}
                  </div>
                ),
              );
            })()}
      </div>
    </div>
  );
}

export function MessageList({ messages, busy, onOpenFile, awaitingApproval }: Props) {
  // Pin to the bottom as tokens stream in.
  //
  // Keyed on the *tail* of the transcript rather than on the whole list, so a
  // long conversation does not re-run this for every delta of its last message
  // -- but keyed on more than the message count, because a turn's own message
  // grows under an unchanged count: its prose, then a row, then more prose, then
  // another row. Keyed on the count alone the rows added after the turn's first
  // token never pulled the view down, so a turn ended with its last call -- the
  // one thing the reader stayed to watch -- below the fold. Detail text is in
  // the key because a row that goes from "running" to finished grows one line
  // deeper without changing any count.
  const endRef = useRef<HTMLDivElement>(null);
  const tail = messages[messages.length - 1];
  const growth = tail
    ? [
        messages.length,
        tail.text.length,
        tail.reasoning.length,
        tail.tools.length,
        tail.tools.reduce((n, tool) => n + (tool.detail?.length ?? 0), 0),
      ].join(":")
    : "empty";
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [growth, busy]);

  return (
    <div className="transcript">
      <div className="transcript-inner">
        {messages.map((message, index) => (
          <Bubble
            key={message.id}
            message={message}
            // Only the turn's own message streams, and only while the turn is
            // running: a restored conversation is never "still arriving". A turn
            // stopped on a permission prompt is not writing either -- the caret
            // blinks under prose that is already finished, and the status pill is
            // where "waiting" is said.
            streaming={
              busy &&
              !awaitingApproval &&
              message.role === "assistant" &&
              index === messages.length - 1 &&
              message.text.trim() !== ""
            }
            onOpenFile={onOpenFile}
            awaitingApproval={awaitingApproval}
          />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
