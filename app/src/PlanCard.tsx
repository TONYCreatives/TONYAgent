/**
 * The agent's plan, as five rows and a goal.
 *
 * The list is the core's (`plan.get`, backed by `todo_write`), not something
 * derived here: the model sees the same list in its prompt, so a second
 * rendering that disagreed with it would be a window telling the user one thing
 * and the agent acting on another.
 *
 * **Read-only, and pressable only where a press means something.** The rows are
 * not checkboxes: ticking one here would change the plan behind the agent's back
 * without the model knowing, and the next `todo_write` would silently undo it.
 * What a row *can* do is take the reader to the call that wrote it -- and only
 * when that call is in the transcript, which a restored conversation's is not.
 * Then the row is plain text rather than a button that scrolls nowhere.
 *
 * Five rows, not all of them. The panel is 288px and the plan is a glance; a
 * plan longer than five is a plan the reader scrolls back to the transcript for,
 * and `+ N more` says how much of it is down there.
 */

import type { Plan, PlanItem } from "./backend.js";

/** How each state is drawn. Text marks, not icons: they inherit the row's colour. */
const MARKS: Record<PlanItem["status"], string> = {
  completed: "✓",
  in_progress: "▸",
  pending: "·",
};

/** The heading a row is read with when the mark is all it has. */
const NAMES: Record<PlanItem["status"], string> = {
  completed: "Done",
  in_progress: "In progress",
  pending: "Not started",
};

const LIMIT = 5;

interface Props {
  plan: Plan;
  /** Take the reader to the call that wrote the list, when there is one. */
  onReveal?: () => void;
}

/** One row, as a button or as text, with the same inside either way. */
function PlanRow({ item, onReveal }: { item: PlanItem; onReveal?: () => void }) {
  const status: PlanItem["status"] =
    item.status === "completed" || item.status === "in_progress" ? item.status : "pending";
  const inside = (
    <>
      <span className="plan-mark" data-status={status} aria-hidden="true">
        {MARKS[status]}
      </span>
      <span className="plan-text" title={item.text}>
        {item.text}
      </span>
    </>
  );

  return (
    <li className={`plan-row${onReveal ? " is-revealable" : ""}`} data-status={status}>
      {onReveal ? (
        <button
          type="button"
          className="plan-row-button"
          onClick={onReveal}
          title={`${NAMES[status]} — show the call that wrote this plan`}
        >
          {inside}
        </button>
      ) : (
        <span className="plan-row-body" title={NAMES[status]}>
          {inside}
        </span>
      )}
    </li>
  );
}

export function PlanCard({ plan, onReveal }: Props) {
  const done = plan.todos.filter((item) => item.status === "completed").length;
  const visible = plan.todos.slice(0, LIMIT);
  const hidden = plan.todos.length - visible.length;
  const empty = plan.todos.length === 0 && plan.goal === "";

  // The label sits beside the goal rather than above it: a plan with a goal is
  // the ordinary case, and a heading for one line costs the row the width the
  // goal needs.
  const goalStatus =
    plan.goal_status === "complete"
      ? "done"
      : plan.goal_status === "blocked"
        ? "blocked"
        : "";

  if (empty) {
    return <p className="context-empty">No plan yet — ask for one.</p>;
  }

  return (
    <div className="plan-card">
      {plan.goal !== "" && (
        <p className="plan-goal" title={plan.goal_note || plan.goal}>
          <span className="plan-goal-label">Goal</span>
          <span className="plan-goal-text">{plan.goal}</span>
          {goalStatus !== "" && (
            <span className="plan-goal-status" data-status={goalStatus}>
              {goalStatus}
            </span>
          )}
        </p>
      )}

      {plan.todos.length > 0 && (
        <>
          <ul className="plan-rows" aria-label={`Plan, ${done} of ${plan.todos.length} done`}>
            {visible.map((item, index) => (
              <PlanRow key={`${index}:${item.text}`} item={item} onReveal={onReveal} />
            ))}
          </ul>
          {hidden > 0 && (
            <p className="plan-more">
              +{hidden} more in the transcript
            </p>
          )}
        </>
      )}
    </div>
  );
}
