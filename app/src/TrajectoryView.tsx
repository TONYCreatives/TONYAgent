/**
 * The trajectory: every event the core produced, in order, unfolded.
 *
 * The transcript (`events.ts`) *reduces* this stream -- it folds tool results
 * into one-line cards, streams deltas into finished text, thinking into a side
 * panel -- which is what a reader wants while working. What it is not is a
 * record of what actually happened. The moment something behaves oddly -- a
 * command ran unexpectedly, a diff looks wrong, a call was refused -- the
 * questions are about the raw traffic: the exact arguments, the full output,
 * the event order.
 *
 * So this view renders the same events the transcript is built from, unfolded:
 * every message and reasoning delta, every tool call with its arguments and
 * full output, every code diff, every confirmation, sandbox and log line, in
 * the order the core emitted them. It is a debugging surface, so it errs toward
 * "show it all" rather than summarising.
 *
 * Nothing here decides anything. The core owns the events; this is a reader,
 * like the transcript. The only state is a filter and whether raw JSON shows.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { CoreEvent } from "./backend.js";

/** One captured event: the whole frame, plus where and when it landed. */
export interface CapturedEvent {
  n: number;
  at: number;
  type: string;
  turnId: string | null;
  subagent: string;
  parentCallId: string;
  payload: Record<string, unknown>;
}

/**
 * Fold a pushed `CoreEvent` into the shape the view reads.
 *
 * The payload is copied aside rather than read off the raw event here: it is
 * the point, and a copy keeps a later event from mutating what is on screen.
 */
export function captureEvent(event: CoreEvent, n: number, at: number): CapturedEvent {
  return {
    n,
    at,
    type: String(event.type),
    turnId: (event.turn_id as string | null | undefined) ?? null,
    subagent: (event.subagent as string | undefined) ?? "",
    parentCallId: (event.parent_call_id as string | undefined) ?? "",
    payload: (event.payload ?? {}) as Record<string, unknown>,
  };
}

const asText = (value: unknown): string => (typeof value === "string" ? value : "");

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function clock(at: number): string {
  const d = new Date(at);
  const pad = (x: number, w = 2) => String(x).padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

/** Turn lifecycle events are dividers: a header, no body. */
const TURN_EVENTS = new Set(["turn.started", "turn.finished", "turn.failed"]);

/** A unified diff, one coloured line per row: the whole point of the view. */
function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre className="traj-diff">
      {diff.split("\n").map((line, index) => {
        const kind = line.startsWith("+")
          ? "add"
          : line.startsWith("-")
            ? "del"
            : line.startsWith("@@")
              ? "hunk"
              : "ctx";
        return (
          <div key={index} className={`traj-diff-${kind}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

/** One event's body, drawn by what kind of traffic it is. */
function EventBody({ ev }: { ev: CapturedEvent }) {
  const p = ev.payload;
  switch (ev.type) {
    case "message.delta":
    case "message.completed":
      return <div className="traj-text">{asText(p.text)}</div>;
    case "reasoning.delta":
    case "reasoning.completed":
      return <div className="traj-think">{asText(p.text)}</div>;
    case "tool.started":
      return <pre className="traj-args">{pretty(p.arguments ?? {})}</pre>;
    case "tool.completed": {
      const result = (p.result ?? {}) as Record<string, unknown>;
      const status = asText(result.status) || "done";
      const artifacts = Array.isArray(result.artifacts) ? result.artifacts : [];
      return (
        <div className="traj-tool">
          <span
            className={`traj-status ${
              status === "success" ? "ok" : status === "error" ? "err" : "run"
            }`}
          >
            {status}
          </span>
          {asText(result.output) && <pre className="traj-output">{asText(result.output)}</pre>}
          {asText(result.error) && (
            <pre className="traj-output traj-error">{asText(result.error)}</pre>
          )}
          {artifacts.map((artifact, i) => {
            const record =
              artifact && typeof artifact === "object"
                ? (artifact as Record<string, unknown>)
                : null;
            if (!record || record.type !== "file_change") return null;
            const data = (record.data ?? {}) as Record<string, unknown>;
            const diff = asText(data.diff);
            return (
              <div key={i} className="traj-change">
                <span className="traj-change-path">{asText(data.path)}</span>
                <span className="traj-change-count">
                  +{String(data.added ?? 0)} &minus;{String(data.removed ?? 0)}
                </span>
                {diff && <DiffBlock diff={diff} />}
              </div>
            );
          })}
        </div>
      );
    }
    case "confirmation.requested":
      return (
        <div className="traj-confirm">
          confirm <b>{asText(p.name)}</b>
          <pre className="traj-args">{pretty(p.arguments ?? {})}</pre>
        </div>
      );
    case "user.asked":
      return <div className="traj-ask">{asText(p.question)}</div>;
    case "sandbox.status":
      return <div className="traj-sandbox">{asText(p.status)}</div>;
    case "log":
      return <div className="traj-log">{asText(p.message) || pretty(p)}</div>;
    case "error":
      return <div className="traj-error">{asText(p.message)}</div>;
    default:
      return <pre className="traj-args">{pretty(p)}</pre>;
  }
}

interface Props {
  events: CapturedEvent[];
}

/** Cap on what is drawn at once, so a very long session does not draw thousands of rows. */
const SHOWN_CAP = 400;

export function TrajectoryView({ events }: Props) {
  const [raw, setRaw] = useState(false);
  const [filter, setFilter] = useState("");
  const [stick, setStick] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const seen = useRef(events.length);

  // Follow the tail while the user has not scrolled away -- the same rule the
  // transcript uses, because this is the same kind of stream.
  useEffect(() => {
    if (events.length !== seen.current) {
      seen.current = events.length;
      if (stick) {
        const el = scroller.current;
        if (el) el.scrollTop = el.scrollHeight;
      }
    }
  }, [events.length, stick]);

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matched = needle
      ? events.filter((e) =>
          `${e.type} ${JSON.stringify(e.payload)}`.toLowerCase().includes(needle),
        )
      : events;
    return matched.length > SHOWN_CAP ? matched.slice(matched.length - SHOWN_CAP) : matched;
  }, [events, filter]);

  return (
    <div className="traj">
      <div className="traj-head">
        <h1>Trajectory</h1>
        <span className="traj-count">{events.length} events</span>
        <input
          className="traj-filter"
          type="search"
          value={filter}
          placeholder="Filter events…"
          aria-label="Filter events"
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="traj-rawtoggle">
          <input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} />
          raw JSON
        </label>
      </div>

      <div
        className="traj-body"
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}
      >
        {events.length === 0 ? (
          <p className="traj-empty">
            No traffic yet. Send a message and every event the agent produces
            will appear here — tool calls, arguments, outputs and code diffs, in
            order.
          </p>
        ) : (
          <ol className="traj-list">
            {shown.map((ev) => (
              <li
                key={ev.n}
                className={`traj-row traj-${ev.type.replace(/\./g, "-")}${
                  TURN_EVENTS.has(ev.type) ? " traj-turn" : ""
                }`}
              >
                <div className="traj-rowhead">
                  <span className="traj-time">{clock(ev.at)}</span>
                  <span className="traj-type">{ev.type}</span>
                  {asText(ev.payload.name) && (
                    <span className="traj-name">{asText(ev.payload.name)}</span>
                  )}
                  {ev.subagent && <span className="traj-sub">subagent {ev.subagent}</span>}
                  {ev.turnId && <span className="traj-turnid">turn {ev.turnId.slice(0, 8)}</span>}
                </div>
                {!TURN_EVENTS.has(ev.type) && <EventBody ev={ev} />}
                {raw && <pre className="traj-rawjson">{pretty(ev.payload)}</pre>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}


