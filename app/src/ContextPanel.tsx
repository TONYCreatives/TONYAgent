/**
 * The agent's work, in the window's right-hand pane.
 *
 * Four sections, one column: the run (sticky, the pane's own state), the plan,
 * the activity feed and the files it touched. Three of them are collapsible and
 * only one is open at a time, because 288px showing all four at once is a wall
 * of text rather than a glance -- see `Section` below.
 *
 * **The Run card does not scroll away.** It is the one thing the pane exists to
 * answer while a turn runs, and a card that scrolled under the plan would make
 * the reader hunt for "is it still working". Everything else passes beneath it.
 *
 * Three forms, one component:
 *
 * - **closed, in flow** -- a 48px strip holding the status orb and a vertical
 *   RUN label. Clicking it opens the panel. It is the context pane's compact
 *   state, the mirror of the nav's rail.
 * - **open, docked** (>= 1400) -- a 288px column managed by the shell's grid.
 * - **open, overlay** (< 1400) -- the same 288px surface floating over the
 *   centre, because opening it must not take the reading column below 760px
 *   just because someone asked to see the run.
 *
 * **The pane reports; it does not own the data.** The plan, the context meter
 * and the files are the window's (read from the core, derived from the
 * transcript), and every press here calls back into `App`. That is what keeps
 * this component from becoming a second place that decides what the run is.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import { ActivityFeed } from "./ActivityFeed.js";
import { FilesTouched } from "./FilesTouched.js";
import { PlanCard } from "./PlanCard.js";
import { RunCard } from "./RunCard.js";
import type { ActivityStep, RunState, TouchedFile } from "./activity.js";
import type { ContextReply, Plan } from "./backend.js";

type SectionKey = "plan" | "activity" | "files";

interface Props {
  /** The expanded panel is showing. */
  open: boolean;
  /** The expanded panel is a grid column rather than an overlay. */
  docked: boolean;
  run: RunState;
  /** The running turn's start, or null when nothing is running. */
  startedAt: number | null;
  /** What the agent is doing, for the one line under the state. */
  detail: string;
  /** The core's plan for this conversation. */
  plan: Plan;
  /** The call that wrote the plan, when it is in the transcript. */
  planCallId: string | null;
  /** This turn's tool calls, oldest first. */
  steps: ActivityStep[];
  /** This turn's files, first touch first. */
  files: TouchedFile[];
  /** How full the conversation is, as the core measured it. */
  context: ContextReply;
  onToggle: () => void;
  onStop: () => void;
  onOpenTrajectory: () => void;
  /** Take the reader to the tool call that wrote the plan. */
  onRevealPlan: () => void;
  /** Open a touched file in Code. */
  onOpenFile: (path: string) => void;
}

/**
 * One collapsible section of the pane.
 *
 * A button that owns its body, not a `details` element: the caret, the count and
 * the accent are the app's own, and `details` cannot be styled to match the
 * sidebar's groups without working around its marker. `aria-expanded` and
 * `aria-controls` are what make it a disclosure rather than a styled div.
 */
function Section({
  id,
  title,
  meta,
  open,
  onToggle,
  children,
}: {
  id: SectionKey;
  title: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="context-section" data-open={open ? "true" : "false"}>
      <button
        type="button"
        className="context-section-head"
        aria-expanded={open}
        aria-controls={`context-${id}`}
        onClick={onToggle}
      >
        <span className="context-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        <span className="context-section-title">{title}</span>
        {meta && <span className="context-section-meta">{meta}</span>}
      </button>
      {open && (
        <div className="context-section-body" id={`context-${id}`}>
          {children}
        </div>
      )}
    </section>
  );
}

export function ContextPanel({
  open,
  docked,
  run,
  startedAt,
  detail,
  plan,
  planCallId,
  steps,
  files,
  context,
  onToggle,
  onStop,
  onOpenTrajectory,
  onRevealPlan,
  onOpenFile,
}: Props) {
  /**
   * Which section is open, and why it has a default rather than a state per
   * section.
   *
   * The pane is 288px. Two open sections are already a scroll; four are a
   * document. So this is an accordion -- pressing one closes the other -- and
   * the default is the one that answers the question of the moment: the live
   * feed while a turn runs, the plan when it does not.
   *
   * A reader's choice survives the turn. Opening the files during a run must not
   * be undone by the next tool call, so the "switch to activity" effect fires on
   * a *run* change, not on every render -- and does not fire at all if the
   * section is already the activity feed.
   */
  const [section, setSection] = useState<SectionKey | null>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open && !wasOpen.current) setSection(run === "working" ? "activity" : "plan");
    wasOpen.current = open;
  }, [open, run]);

  useEffect(() => {
    if (open && run === "working") setSection("activity");
  }, [open, run]);

  const toggle = (key: SectionKey) =>
    setSection((current) => (current === key ? null : key));

  const done = plan.todos.filter((item) => item.status === "completed").length;

  return (
    <aside
      className="contextdock"
      data-state={open ? "open" : "closed"}
      data-docked={docked ? "true" : "false"}
      aria-label="Run"
    >
      <button
        type="button"
        className="context-strip"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={open ? "Hide the run panel" : "Show the run panel"}
        title={open ? "Hide the run panel" : "Show the run panel"}
      >
        <span className="run-orb" data-run={run} aria-hidden="true" />
        <span className="context-strip-label">Run</span>
      </button>

      <div className="context-panel">
        <div className="context-head">
          <span className="context-title">Run</span>
          <button
            type="button"
            className="context-toggle"
            onClick={onToggle}
            aria-label="Hide the run panel"
            title="Hide the run panel"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="context-scroll">
          <div className="run-sticky">
            <RunCard
              run={run}
              startedAt={startedAt}
              detail={detail}
              context={context}
              onStop={onStop}
              onOpenTrajectory={onOpenTrajectory}
            />
          </div>

          <Section
            id="plan"
            title="Plan"
            meta={plan.todos.length > 0 ? `${done}/${plan.todos.length}` : undefined}
            open={section === "plan"}
            onToggle={() => toggle("plan")}
          >
            <PlanCard
              plan={plan}
              onReveal={planCallId !== null ? onRevealPlan : undefined}
            />
          </Section>

          <Section
            id="activity"
            title="Activity"
            meta={steps.length > 0 ? String(steps.length) : undefined}
            open={section === "activity"}
            onToggle={() => toggle("activity")}
          >
            <ActivityFeed steps={steps} />
          </Section>

          <Section
            id="files"
            title="Files"
            meta={files.length > 0 ? String(files.length) : undefined}
            open={section === "files"}
            onToggle={() => toggle("files")}
          >
            <FilesTouched files={files} onOpen={onOpenFile} />
          </Section>
        </div>
      </div>
    </aside>
  );
}
