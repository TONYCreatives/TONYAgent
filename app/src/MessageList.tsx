import { useEffect, useRef, useState } from "react";
import type { ChatMessage, SubagentChild, ReasonRun, ToolCall } from "./events.js";
import { MarkdownText } from "./MarkdownText.js";
import { AppMark } from "./AppMark.js";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  project: string;
  onChooseFolder?: () => void;
  canChooseFolder?: boolean;
}

/**
 * What the empty panel needs, which is not what the transcript needs.
 *
 * Its own interface rather than a slice of `Props`: `FirstRun` renders no
 * messages and is never busy, and writing it as `Props` would mean the empty
 * state had to be handed two arguments it cannot use -- which is the shape a
 * test ends up asserting against instead of the component.
 */
interface FirstRunProps {
  /**
   * The project folder the core is working on, or "" when there is none.
   *
   * Passed in rather than read here: the panel has no backend of its own, and a
   * second source for "what folder is this" is a second thing to be wrong.
   */
  project: string;
  /** Open the folder picker. Omitted when the caller has no picker to open. */
  onChooseFolder?: () => void;
  /** Whether that button can be pressed right now. */
  canChooseFolder?: boolean;
}

/**
 * The folder's own name, out of a path.
 *
 * The last segment, on either separator, because the paths here arrive from
 * Windows (`C:\Users\me\project`) and from the picker, which on some machines
 * hands back a forward-slash form. The full path is the button's `title`, so
 * the two are both available and neither is the only one.
 */
function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/**
 * A folder, for the one line that names the project folder.
 *
 * An outline, stroked on `currentColor`, so it takes the `--fg-dim` the name
 * beside it is drawn in and moves with the palette rather than carrying a second
 * grey. Decorative -- the name is right there, so it is hidden from assistive
 * tech and the SVG 1.1 `focusable=false` keeps a Tab off it.
 */
function FolderIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
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

/** One tool invocation inside an assistant message. */
function ToolRow({ tool }: { tool: ChatMessage["tools"][number] }) {
  return (
    <div className="tool-unit">
      <div className={`tool tool-${tool.status}`}>
        <span className="tool-mark" aria-hidden="true">
          {STATUS_MARK[tool.status]}
        </span>
        <span className="tool-name">{tool.name}</span>
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
        {tool.detail && <span className="tool-detail">{tool.detail}</span>}
      </div>
      {tool.child && <SubagentWork child={tool.child} />}
    </div>
  );
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

function Bubble({ message }: { message: ChatMessage }) {
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
          : runsOf(message).map((run, index) =>
              run.kind === "text" ? (
                <MarkdownText key={index} text={run.text} />
              ) : run.kind === "thinking" ? (
                <ThinkingPanel key={index} pass={run.run} />
              ) : (
                <div className="tools" key={index}>
                  {run.tools.map((tool) => (
                    <ToolRow key={tool.id} tool={tool} />
                  ))}
                </div>
              ),
            )}
      </div>
    </div>
  );
}

/**
 * What the conversation area says before there is a conversation.
 *
 * It was a wordmark and one line, and it was correct as far as it went --
 * except that the two things a new user most needs to know were in the
 * composer's *placeholder*, which they have to notice and click into before
 * they can read. So the hints are promoted here, and the mark is drawn at a
 * size that says what this window is before anyone types.
 *
 * The project folder is here for the same reason, and it is the one control on
 * the panel. Before this, the only place to change the folder was a row inside
 * the settings panel -- a panel that opens on top of the very window the user
 * is looking at, behind a menu they have to find. A new chat is *about* a
 * folder: the agent's tools resolve every path against it, and with none
 * chosen every file read answers "no project folder selected". So the thing
 * the chat depends on is said in the middle of the chat.
 *
 * **Leaving it alone keeps the folder.** The button is "Change...", not
 * "Choose...", whenever there is already a folder, and the name beside it is
 * the one in force. Nothing is asked and nothing is reset by starting a chat,
 * which is what `App.startNewChat` already promised -- this shows the promise
 * instead of hiding it in the settings panel.
 *
 * The panel used to hold nothing focusable at all, and that rule is narrowed
 * rather than dropped: one `<button>`, and the test names it. An empty state is
 * still where an app is most tempted to offer a demo conversation or a "what
 * can I do?" link, and each of those would still add a tab stop to the surface
 * a user is trying to leave by pressing Tab once and typing.
 *
 * The hints are `<kbd>` and text because they describe keys rather than offer
 * them: pressing `/` here would type a slash into the composer, which is
 * exactly what it does everywhere else.
 */
function FirstRun({ project, onChooseFolder, canChooseFolder }: FirstRunProps) {
  return (
    <div className="empty">
      <AppMark className="empty-mark" size={104} />
      <h1>TONYAgent</h1>
      <p>Ask for something. The agent will use its tools to do it.</p>
      {/*
        The folder, named, with the one control. `title` on the name rather
        than on the button: the button's own text is "Change...", which says
        nothing about what it would change to, and a truncated name with the
        full path on hover is the compromise that keeps one line.
      */}
      <div className="empty-folder">
        <FolderIcon className="empty-folder-icon" />
        <p className="empty-folder-name" title={project || undefined}>
          {project ? folderName(project) : "No project folder"}
        </p>
        {onChooseFolder && (
          <button
            type="button"
            className="btn"
            onClick={onChooseFolder}
            disabled={!canChooseFolder}
          >
            {project ? "Change..." : "Choose folder..."}
          </button>
        )}
      </div>
      <ul className="empty-hints">
        <li>
          <kbd>/</kbd> for skills
        </li>
        <li>
          <kbd>@</kbd> for threads or files
        </li>
      </ul>
    </div>
  );
}

export function MessageList({
  messages,
  busy,
  project,
  onChooseFolder,
  canChooseFolder,
}: Props) {
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

  if (messages.length === 0) {
    return (
      <FirstRun
        project={project}
        onChooseFolder={onChooseFolder}
        canChooseFolder={canChooseFolder}
      />
    );
  }

  return (
    <div className="transcript">
      <div className="transcript-inner">
        {messages.map((message) => (
          <Bubble key={message.id} message={message} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
