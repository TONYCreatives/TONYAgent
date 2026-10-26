/**
 * What the turn has run, as a log.
 *
 * **Chronological, newest at the bottom.** A feed that prepended each new call
 * would move every row the reader was looking at, once per tool, and the live
 * row would be at the far end from the cursor. Oldest-first puts the newest
 * thing nearest the eye and the composer, which is where the turn is going.
 *
 * Six rows, with the rest one press away. Six is what fits above the files
 * section at the window's minimum height; the panel is a glance, and the
 * transcript is where a long run is read in full.
 *
 * **No live region per row.** The Run card's status line is the pane's one live
 * region: a region here would announce every completed call and every summary
 * change, which is a running commentary on a panel the reader chose to keep
 * open. There is nothing to announce anyway -- the rows are history, and the
 * card above already says the turn is working.
 */

import { useState } from "react";

import { formatDuration, type ActivityStep } from "./activity.js";

const LIMIT = 6;

const MARKS: Record<ActivityStep["status"], string> = {
  running: "●",
  ok: "✓",
  failed: "✕",
};

const STATUS_NAMES: Record<ActivityStep["status"], string> = {
  running: "Running",
  ok: "Done",
  failed: "Failed",
};

interface Props {
  /** The turn's calls, oldest first -- `turnActivity` already orders them so. */
  steps: ActivityStep[];
}

export function ActivityFeed({ steps }: Props) {
  const [all, setAll] = useState(false);
  const overflow = steps.length > LIMIT;
  const visible = all || !overflow ? steps : steps.slice(-LIMIT);

  if (steps.length === 0) {
    return <p className="context-empty">No tool calls yet.</p>;
  }

  return (
    <div className="activity-feed">
      <ol className="activity-rows" aria-label="Tool calls in this turn">
        {visible.map((step) => (
          <li
            key={step.id}
            className="activity-row"
            data-status={step.status}
            title={`${STATUS_NAMES[step.status]}: ${step.name}${
              step.summary !== step.name ? ` — ${step.summary}` : ""
            }`}
          >
            <span className="activity-mark" aria-hidden="true">
              {MARKS[step.status]}
            </span>
            <span className="activity-name">{step.name}</span>
            {/*
              The core's own summary, which is often the same word as the tool
              name on a call that reported nothing more. Repeating it beside the
              name is a row that says `read_file read_file`.
            */}
            {step.summary !== step.name && (
              <span className="activity-detail">{step.summary}</span>
            )}
            {step.durationMs !== null && (
              <span className="activity-time">{formatDuration(step.durationMs)}</span>
            )}
          </li>
        ))}
      </ol>

      {overflow && (
        <button
          type="button"
          className="activity-more linkish"
          onClick={() => setAll((was) => !was)}
          aria-expanded={all}
        >
          {all ? "Show fewer" : `View all ${steps.length}`}
        </button>
      )}
    </div>
  );
}
