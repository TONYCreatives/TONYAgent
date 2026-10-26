/**
 * The run pane: four sections and one sticky card.
 *
 * This file tests the pane as a *pane* -- what opens, what a press does, and
 * where the live region is -- rather than re-testing `activity.ts`, whose
 * derivations have their own suite. The two claims worth the most here are the
 * accordion (one open section, always, because two is a scroll in 288px) and the
 * live-region budget (one, the card's sentence, because a region per row would
 * read the whole feed aloud at every tool call).
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import type { ComponentProps } from "react";

import { ContextPanel } from "./ContextPanel.js";
import type { ActivityStep, TouchedFile } from "./activity.js";
import type { ContextReply, Plan, PlanItem } from "./backend.js";
import { all, click, one, render, texts } from "./test-render.js";

type PanelProps = ComponentProps<typeof ContextPanel>;

const emptyPlan = (over: Partial<Plan> = {}): Plan => ({
  todos: [],
  goal: "",
  goal_status: "",
  goal_note: "",
  ...over,
});

const todo = (text: string, status: PlanItem["status"] = "pending"): PlanItem => ({
  text,
  status,
});

const context = (over: Partial<ContextReply> = {}): ContextReply => ({
  model: "stealth/space-bunny-alpha",
  used: 0,
  known: false,
  window: 0,
  ...over,
});

const step = (
  id: string,
  name: string,
  over: Partial<ActivityStep> = {},
): ActivityStep => ({
  id,
  name,
  status: "ok",
  summary: name,
  durationMs: null,
  ...over,
});

/**
 * A panel wired to counting handlers.
 *
 * The counters are what make "pressing this calls back" a fact rather than a
 * selector that happens to exist. `props` is exposed so a test can change one
 * thing and keep every other argument the same, which is how the differences
 * below stay attributable.
 */
function make(over: Partial<PanelProps> = {}) {
  const seen = {
    toggle: 0,
    stop: 0,
    trajectory: 0,
    reveal: 0,
    opened: [] as string[],
  };
  const props: PanelProps = {
    open: true,
    docked: true,
    run: "idle",
    startedAt: null,
    detail: "",
    plan: emptyPlan(),
    planCallId: null,
    steps: [],
    files: [],
    context: context(),
    onToggle: () => {
      seen.toggle += 1;
    },
    onStop: () => {
      seen.stop += 1;
    },
    onOpenTrajectory: () => {
      seen.trajectory += 1;
    },
    onRevealPlan: () => {
      seen.reveal += 1;
    },
    onOpenFile: (path) => {
      seen.opened.push(path);
    },
    ...over,
  };
  return {
    props,
    seen,
    draw: () => render(<ContextPanel {...props} />),
  };
}

/** The section heads, by their visible names, as pairs of name -> element. */
const heads = (container: HTMLElement) =>
  all(container, ".context-section-head").map((head) => ({
    head,
    title: one(head, ".context-section-title")?.textContent ?? "",
    open: head.getAttribute("aria-expanded") === "true",
  }));

const openSection = (container: HTMLElement) =>
  all(container, ".context-section")
    .find((section) => section.getAttribute("data-open") === "true")
    ?.querySelector(".context-section-title")?.textContent ?? null;

/**
 * Open a section by name, if it is not already the open one.
 *
 * The pane deliberately opens on one section only, so every test that reads
 * the feed or the files has to press its head first. That press is the
 * accordion working, not setup noise -- it is the same path a reader takes.
 */
async function show(container: HTMLElement, title: string): Promise<void> {
  const row = heads(container).find((head) => head.title === title);
  assert.ok(row, `there is no ${title} section`);
  if (!row.open) await click(row.head);
  assert.equal(openSection(container), title);
}

describe("the pane's forms", () => {
  test("closed, the strip is the way in and the panel is not mounted on screen", async () => {
    const { seen, draw } = make({ open: false, docked: false });
    const container = await draw();
    const dock = one(container, ".contextdock")!;

    assert.equal(dock.getAttribute("data-state"), "closed");
    assert.equal(dock.getAttribute("data-docked"), "false");
    // The panel is still in the tree so its sticky card keeps its scroll
    // position; `display: none` is what keeps it out of the tab order and out
    // of the accessibility tree. Written as a class check because jsdom's
    // cascade is not a browser's.
    const strip = one(container, ".context-strip") as HTMLButtonElement;
    assert.ok(strip, "the closed pane has no way to open");
    assert.equal(strip.getAttribute("aria-expanded"), "false");
    assert.equal(strip.getAttribute("aria-label"), "Show the run panel");
    assert.equal(
      one(container, ".context-strip .run-orb")?.getAttribute("data-run"),
      "idle",
      "the strip does not report the run it stands for",
    );

    await click(strip);
    assert.equal(seen.toggle, 1);
  });

  test("open, the head says what the pane is and carries the way shut", async () => {
    const { seen, draw } = make({ open: true });
    const container = await draw();

    assert.equal(one(container, ".context-head .context-title")?.textContent, "Run");
    const close = one(container, ".context-toggle") as HTMLButtonElement;
    assert.equal(close.getAttribute("aria-label"), "Hide the run panel");
    await click(close);
    assert.equal(seen.toggle, 1);
    // The strip is not drawn while the panel is: two toggles for one state is
    // one too many. It is hidden by CSS, so the rule is asserted in layout.test.
    assert.equal(
      one(container, ".contextdock")?.getAttribute("data-state"),
      "open",
    );
  });

  test("all three sections are heads with a count, whether open or not", async () => {
    const { draw } = make({
      plan: emptyPlan({ todos: [todo("one", "completed"), todo("two")] }),
      steps: [step("c1", "grep")],
      files: [{ path: "a.ts", added: 1, removed: 0 }],
    });
    const container = await draw();
    const rows = heads(container);

    assert.deepEqual(
      rows.map((row) => row.title),
      ["Plan", "Activity", "Files"],
    );
    assert.deepEqual(
      texts(container, ".context-section-meta"),
      ["1/2", "1", "1"],
    );
  });

  test("with nothing to report a section has no count rather than a zero", async () => {
    const { draw } = make();
    const container = await draw();
    assert.deepEqual(texts(container, ".context-section-meta"), []);
  });
});

describe("the accordion", () => {
  test("an idle pane opens on the plan", async () => {
    const { draw } = make({ plan: emptyPlan({ todos: [todo("one")] }) });
    const container = await draw();
    assert.equal(openSection(container), "Plan");
  });

  test("a running pane opens on the feed, because that is what is moving", async () => {
    const { draw } = make({
      run: "working",
      startedAt: Date.now(),
      detail: "Running grep",
      plan: emptyPlan({ todos: [todo("one")] }),
      steps: [step("c1", "grep", { status: "running" })],
    });
    const container = await draw();
    assert.equal(openSection(container), "Activity");
  });

  test("one section at a time, and pressing the open one closes it", async () => {
    const { draw } = make({
      plan: emptyPlan({ todos: [todo("one")] }),
      steps: [step("c1", "grep")],
      files: [{ path: "a.ts", added: 2, removed: 1 }],
    });
    const container = await draw();

    const press = async (title: string) => {
      const row = heads(container).find((head) => head.title === title)!;
      await click(row.head);
    };

    await press("Files");
    assert.equal(openSection(container), "Files");
    assert.equal(all(container, ".context-section-body").length, 1);

    await press("Activity");
    assert.equal(openSection(container), "Activity");
    assert.equal(all(container, ".context-section-body").length, 1);

    await press("Activity");
    assert.equal(openSection(container), null);
    assert.equal(all(container, ".context-section-body").length, 0);
  });

  test("each head names the body it owns, and the body exists only while it is open", async () => {
    const { draw } = make();
    const container = await draw();
    for (const row of heads(container)) {
      const controls = row.head.getAttribute("aria-controls");
      assert.ok(controls, `${row.title} controls nothing`);
      // A closed section's body is unmounted, not hidden: `aria-controls` names
      // an id that arrives with the open state and leaves with it.
      if (row.open) {
        assert.ok(one(container, `#${controls}`), `${row.title} names no body`);
      } else {
        assert.equal(one(container, `#${controls}`), null);
      }
    }
  });
});

describe("the plan card", () => {
  test("a goal, its state, and five rows with a remainder", async () => {
    const todos = Array.from({ length: 7 }, (_, i) => todo(`task ${i + 1}`));
    todos[0] = todo("task 1", "completed");
    todos[1] = todo("task 2", "in_progress");
    const { draw } = make({
      plan: emptyPlan({ todos, goal: "Ship the pane", goal_status: "active" }),
    });
    const container = await draw();

    assert.equal(one(container, ".plan-goal-text")?.textContent, "Ship the pane");
    assert.equal(all(container, ".plan-row").length, 5);
    assert.deepEqual(texts(container, ".plan-text"), [
      "task 1",
      "task 2",
      "task 3",
      "task 4",
      "task 5",
    ]);
    assert.equal(one(container, ".plan-more")?.textContent, "+2 more in the transcript");
    assert.equal(
      one(container, ".plan-rows")?.getAttribute("aria-label"),
      "Plan, 1 of 7 done",
    );

    // The marks are the state: a tick, a pointer, a dot. Read from the row's
    // own `data-status` so the colour rule and the glyph cannot disagree.
    assert.deepEqual(
      all(container, ".plan-mark").map((mark) => mark.getAttribute("data-status")),
      ["completed", "in_progress", "pending", "pending", "pending"],
    );
  });

  test("a goal that is done or blocked says so in the goal line", async () => {
    for (const [status, shown] of [
      ["complete", "done"],
      ["blocked", "blocked"],
    ] as const) {
      const { draw } = make({
        plan: emptyPlan({ todos: [todo("one")], goal: "g", goal_status: status }),
      });
      const container = await draw();
      assert.equal(one(container, ".plan-goal-status")?.textContent, shown);
      assert.equal(
        one(container, ".plan-goal-status")?.getAttribute("data-status"),
        shown,
      );
    }
  });

  test("with no writer in the transcript the rows are text, not dead buttons", async () => {
    const { seen, draw } = make({
      plan: emptyPlan({ todos: [todo("one")] }),
      planCallId: null,
    });
    const container = await draw();

    assert.equal(all(container, ".plan-row-button").length, 0);
    assert.equal(all(container, ".plan-row-body").length, 1);
    assert.equal(seen.reveal, 0);
  });

  test("with a writer, every row takes the reader to the call that wrote it", async () => {
    const { seen, draw } = make({
      plan: emptyPlan({ todos: [todo("one"), todo("two")] }),
      planCallId: "c7",
    });
    const container = await draw();

    const rows = all(container, ".plan-row-button");
    assert.equal(rows.length, 2);
    await click(rows[1]!);
    assert.equal(seen.reveal, 1);
  });

  test("an empty plan says how to get one", async () => {
    const { draw } = make();
    const container = await draw();
    assert.equal(
      one(container, ".context-section-body .context-empty")?.textContent,
      "No plan yet — ask for one.",
    );
  });
});

describe("the activity feed", () => {
  test("it is chronological, and six rows keep the newest", async () => {
    const steps = Array.from({ length: 8 }, (_, i) =>
      step(`c${i}`, `tool_${i}`),
    );
    const { draw } = make({ run: "working", steps });
    const container = await draw();
    await show(container, "Activity");

    assert.deepEqual(texts(container, ".activity-name"), [
      "tool_2",
      "tool_3",
      "tool_4",
      "tool_5",
      "tool_6",
      "tool_7",
    ]);

    const more = one(container, ".activity-more") as HTMLButtonElement;
    assert.equal(more.textContent, "View all 8");
    assert.equal(more.getAttribute("aria-expanded"), "false");

    await click(more);
    assert.equal(all(container, ".activity-row").length, 8);
    assert.equal(
      one(container, ".activity-more")?.textContent,
      "Show fewer",
    );

    await click(one(container, ".activity-more")!);
    assert.equal(all(container, ".activity-row").length, 6);
  });

  test("a row shows the core's summary, its duration, and not its name twice", async () => {
    const { draw } = make({
      run: "working",
      steps: [
        step("c1", "read_file", {
          summary: "Read src/app.ts",
          durationMs: 420,
        }),
        // A call whose summary is its own name must not read `grep grep`.
        step("c2", "grep", { summary: "grep", durationMs: 2_400 }),
        step("c3", "edit_file", { status: "failed", summary: "No such file" }),
      ],
    });
    const container = await draw();
    await show(container, "Activity");

    assert.deepEqual(texts(container, ".activity-detail"), [
      "Read src/app.ts",
      "No such file",
    ]);
    // One precision for sub-second work, one for seconds; a call with no
    // measurement (a restored conversation) draws no number at all.
    assert.deepEqual(texts(container, ".activity-time"), ["420ms", "2.4s"]);
    assert.deepEqual(
      all(container, ".activity-row").map((row) => row.getAttribute("data-status")),
      ["ok", "ok", "failed"],
    );
  });

  test("with nothing run yet, it says so rather than drawing an empty list", async () => {
    const { draw } = make();
    const container = await draw();
    await show(container, "Activity");
    assert.equal(
      one(container, ".context-section-body .context-empty")?.textContent,
      "No tool calls yet.",
    );
  });

  test("the status word is the title, because the mark is only a glyph", async () => {
    const { draw } = make({
      run: "working",
      steps: [
        step("c1", "grep", { status: "running" }),
        step("c2", "read_file", { status: "failed", summary: "gone" }),
      ],
    });
    const container = await draw();
    await show(container, "Activity");
    const titles = all(container, ".activity-row").map((row) => row.title);
    assert.match(titles[0]!, /^Running: grep/);
    assert.match(titles[1]!, /^Failed: read_file — gone/);
  });
});

describe("the files list", () => {
  const files: TouchedFile[] = [
    { path: "/repo/app/src/App.tsx", added: 12, removed: 3 },
    { path: "/repo/README.md", added: 4, removed: 0 },
    { path: "/repo/app/src/styles/context.css", added: 40, removed: 0 },
  ];

  test("the name leads and the folder is context beside it", async () => {
    const { draw } = make({ files });
    const container = await draw();
    await show(container, "Files");

    assert.deepEqual(texts(container, ".file-name"), [
      "App.tsx",
      "README.md",
      "context.css",
    ]);
    assert.deepEqual(texts(container, ".file-dir"), [
      "/repo/app/src/",
      "/repo/",
      "/repo/app/src/styles/",
    ]);
    assert.deepEqual(texts(container, ".file-added"), ["+12", "+4", "+40"]);
    assert.deepEqual(texts(container, ".file-removed"), ["−3"]);
  });

  test("a row opens the whole path, not the part it draws", async () => {
    const { seen, draw } = make({ files });
    const container = await draw();
    await show(container, "Files");

    const rows = all(container, ".file-row");
    assert.equal(rows.length, 3);
    await click(rows[2]!);
    assert.deepEqual(seen.opened, ["/repo/app/src/styles/context.css"]);
  });

  test("five rows and a remainder, and no counts at zero", async () => {
    const many = Array.from({ length: 7 }, (_, i) => ({
      path: `f${i}.ts`,
      added: 0,
      removed: 0,
    }));
    const { draw } = make({ files: many });
    const container = await draw();
    await show(container, "Files");

    assert.equal(all(container, ".file-row").length, 5);
    assert.equal(one(container, ".files-touched .plan-more")?.textContent, "+2 more");
    assert.equal(all(container, ".file-added").length, 0);
    assert.equal(all(container, ".file-removed").length, 0);
  });

  test("with nothing touched, it says so", async () => {
    const { draw } = make();
    const container = await draw();
    await show(container, "Files");
    assert.equal(
      one(container, ".context-section-body .context-empty")?.textContent,
      "No files touched yet.",
    );
  });
});

describe("the run card", () => {
  test("working draws a clock and a way to stop", async () => {
    // One panel per test on purpose: a second `render` in the same test replaces
    // the root without unmounting the first, so a running clock's interval would
    // outlive the test and keep the runner alive. See `test-render`'s root.
    const { seen, draw } = make({
      run: "working",
      startedAt: Date.now() - 65_000,
      detail: "Running grep",
    });
    const container = await draw();

    assert.equal(one(container, ".run-state")?.textContent, "Working");
    assert.match(one(container, ".run-clock")?.textContent ?? "", /^1:0\d$/);
    assert.equal(one(container, ".run-detail")?.textContent, "Running grep");

    const stop = one(container, ".run-stop") as HTMLButtonElement;
    assert.ok(stop, "a running turn has no Stop");
    await click(stop);
    assert.equal(seen.stop, 1);
  });

  test("idle draws no clock and nothing to stop", async () => {
    const { draw } = make({ run: "idle" });
    const container = await draw();

    assert.equal(one(container, ".run-state")?.textContent, "Idle");
    assert.equal(one(container, ".run-clock"), null);
    assert.equal(one(container, ".run-stop"), null);
    assert.equal(one(container, ".run-detail")?.textContent, "No turn is running.");
  });

  test("waiting and error say what they mean rather than 'working'", async () => {
    for (const [run, hint] of [
      ["waiting", "The agent needs an answer before it can continue."],
      ["error", "The last turn failed. The transcript says why."],
    ] as const) {
      const { draw } = make({ run, detail: "Running grep" });
      const container = await draw();
      // The detail belongs to working; a blocked turn must not claim a tool it
      // is not running.
      assert.equal(one(container, ".run-detail")?.textContent, hint);
    }
  });

  test("the meter is a fraction when both numbers are real", async () => {
    const { draw } = make({
      context: context({ used: 62_000, window: 124_000, known: true }),
    });
    const container = await draw();

    assert.equal(
      one(container, ".run-context-value")?.textContent,
      "62k / 124k · 50%",
    );
    assert.equal(one(container, ".run-context")?.getAttribute("data-known"), "true");
    assert.equal(
      (one(container, ".run-context-fill") as HTMLElement).style.width,
      "50%",
    );
  });

  test("usage without a window is a number and no bar", async () => {
    const { draw } = make({ context: context({ used: 12_400, known: true }) });
    const container = await draw();

    assert.equal(one(container, ".run-context-value")?.textContent, "12.4k used");
    // The bar's fraction would be invented, so it is drawn empty rather than
    // filled from a denominator nobody reported.
    assert.equal(one(container, ".run-context-fill"), null);
  });

  test("no measurement at all reads as unknown, not zero", async () => {
    const { draw } = make({ context: context() });
    const container = await draw();

    assert.equal(one(container, ".run-context-value")?.textContent, "unknown");
    assert.equal(one(container, ".run-context")?.getAttribute("data-known"), "false");
  });

  test("the meter cannot draw more than full even if the core says so", async () => {
    const { draw } = make({
      context: context({ used: 300, window: 100, known: true }),
    });
    const container = await draw();
    assert.equal(
      (one(container, ".run-context-fill") as HTMLElement).style.width,
      "100%",
    );
    assert.equal(
      one(container, ".run-context-value")?.textContent,
      "300 / 100 · 100%",
    );
  });

  test("Open Trajectory is a way out of the pane, and it calls back", async () => {
    const { seen, draw } = make();
    const container = await draw();
    const link = one(container, ".run-link") as HTMLButtonElement;
    assert.equal(link.textContent, "Open Trajectory");
    await click(link);
    assert.equal(seen.trajectory, 1);
  });

  test("the card's sentence is the pane's only live region", async () => {
    const { draw } = make({
      run: "working",
      steps: [
        step("c1", "grep", { status: "running" }),
        step("c2", "read_file"),
      ],
      files: [{ path: "a.ts", added: 1, removed: 0 }],
      plan: emptyPlan({ todos: [todo("one")] }),
    });
    const container = await draw();

    const regions = all(container, "[aria-live]");
    assert.equal(regions.length, 1, "the pane announces more than one thing");
    assert.equal(regions[0]!.className, "run-detail");
    assert.equal(regions[0]!.getAttribute("aria-live"), "polite");
    // And the clock is outside it: a region that changed every second would be
    // a region that never stops talking.
    assert.equal(
      regions[0]!.querySelector(".run-clock"),
      null,
    );
  });
});
