/**
 * The dashboard, which is mostly a set of claims about numbers.
 *
 * Each test here pins an answer the user would otherwise have to trust the
 * chart for: which window was asked for, what the tiles add up to, and what the
 * screen says when there is nothing to draw.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Dashboard, type UsageBucket, type UsageGroup, type UsageSummary } from "./Dashboard.js";
import { all, click, one, render, wait } from "./test-render.js";

const EMPTY_TOTALS = {
  requests: 0,
  failed: 0,
  input_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
  total_tokens: 0,
  duration_ms: 0,
};

function summary(
  over: {
    totals?: Partial<typeof EMPTY_TOTALS>;
    buckets?: UsageBucket[];
    by_key?: UsageGroup[];
    tracking_since?: number | null;
  } = {},
): UsageSummary {
  return {
    window: "7d",
    since: null,
    totals: { ...EMPTY_TOTALS, ...over.totals },
    buckets: over.buckets ?? [],
    by_key: over.by_key ?? [],
    by_provider: [],
    by_model: [],
    tracking_since: over.tracking_since ?? null,
  };
}

function bucket(day: string, requests: number): UsageBucket {
  return {
    day,
    requests,
    input_tokens: requests * 10,
    output_tokens: requests * 20,
    total_tokens: requests * 30,
  };
}

function group(provider: string, requests: number): UsageGroup {
  return {
    provider,
    detail: "ab12cd34",
    requests,
    failed: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: requests * 5,
    last_ts: 0,
  };
}

const period = (c: HTMLElement, label: string) =>
  all(c, ".usage-period").find((b) => (b.textContent ?? "").trim() === label)!;

async function open(reply: UsageSummary | null, periods: string[] = []) {
  const container = await render(
    <Dashboard
      connected
      onClose={() => {}}
      load={async (asked) => {
        periods.push(asked);
        return reply;
      }}
    />,
  );
  await wait(0);
  return container;
}

describe("the usage dashboard", () => {
  test("it opens on a week without being asked", async () => {
    const asked: string[] = [];
    await open(summary(), asked);
    assert.deepEqual(asked, ["7d"]);
  });

  test("each period button asks the core for its own window", async () => {
    const asked: string[] = [];
    const container = await open(summary(), asked);

    await click(period(container, "30 days"));
    await wait(0);
    assert.deepEqual(asked, ["7d", "30d"]);

    await click(period(container, "All"));
    await wait(0);
    assert.deepEqual(asked, ["7d", "30d", "all"]);
  });

  test("the period you are looking at is the one marked chosen", async () => {
    const container = await open(summary());
    const selected = all(container, ".usage-period")
      .filter((b) => b.getAttribute("aria-selected") === "true")
      .map((b) => (b.textContent ?? "").trim());
    assert.deepEqual(selected, ["7 days"]);
  });

  test("the tiles read the totals back, separated", async () => {
    const container = await open(
      summary({
        totals: { requests: 1234, failed: 2, input_tokens: 1000, output_tokens: 2000, total_tokens: 3000 },
      }),
    );
    const text = container.textContent ?? "";
    assert.match(text, /1,234/, "the request count is not separated");
    assert.match(text, /3,000/, "the token count is not the total");
    assert.match(text, /2 failed/);
  });

  test("a day with nothing still gets a bar, so the week is not reshaped", async () => {
    const container = await open(
      summary({
        totals: { requests: 2 },
        buckets: [bucket("2026-10-05", 0), bucket("2026-10-06", 2), bucket("2026-10-07", 0)],
      }),
    );
    assert.equal(all(container, ".usage-bar").length, 3);
    assert.equal(all(container, ".usage-bar-fill.is-empty").length, 2);
  });

  test("the tallest day fills the chart and the others are scaled to it", async () => {
    const container = await open(
      summary({
        totals: { requests: 3 },
        buckets: [bucket("2026-10-05", 1), bucket("2026-10-06", 4)],
      }),
    );
    const heights = all(container, ".usage-bar-fill").map(
      (f) => (f as HTMLElement).style.height,
    );
    assert.deepEqual(heights, ["25%", "100%"]);
  });

  test("nothing recorded says so rather than drawing an empty box", async () => {
    const container = await open(summary({ buckets: [bucket("2026-10-05", 0)] }));
    assert.match(container.textContent ?? "", /Nothing recorded in this period/);
    assert.equal(one(container, ".usage-bars"), null);
    // The axis goes too: "peak 1/day" under "nothing recorded" is a claim about
    // a maximum that does not exist.
    assert.equal(one(container, ".usage-axis"), null);
  });

  test("by key names the provider and counts its requests", async () => {
    const container = await open(
      summary({ totals: { requests: 3 }, by_key: [group("openrouter", 3)] }),
    );
    assert.deepEqual(
      all(container, ".usage-key-name").map((n) => (n.textContent ?? "").trim()),
      ["openrouter"],
    );
    assert.deepEqual(
      all(container, ".usage-key-count").map((n) => (n.textContent ?? "").trim()),
      ["3"],
    );
    // The identifier shown is the fingerprint, never a key.
    assert.equal(one(container, ".usage-key-id")!.textContent, "ab12cd34");
  });

  test("a read that failed says so instead of showing zeroes as the truth", async () => {
    const container = await open(null);
    assert.match(container.textContent ?? "", /Could not read the usage ledger/);
  });

  test("it says how far back it is counting when it knows", async () => {
    const container = await open(summary({ tracking_since: 1_700_000_000 }));
    assert.match(container.textContent ?? "", /Counting since/);
  });
});
