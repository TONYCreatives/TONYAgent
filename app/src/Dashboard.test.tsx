/**
 * The dashboard, which is mostly a set of claims about numbers.
 *
 * Each test here pins an answer the user would otherwise have to trust the
 * chart for: which window was asked for, what the tiles add up to, and what the
 * screen says when there is nothing to draw.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

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

/**
 * Stand in for the window host, recording what the dashboard asked it to open.
 *
 * `window.pywebview.api` is the whole surface the view can reach, so recording
 * the view names here records exactly what the host would have been told.
 */
let opened: string[] = [];
let read: string[] = [];

function insideHost(
  options: {
    opened?: boolean;
    /** What the provider's page reports back, when a test cares. */
    read?: Partial<import("./bridge.js").AccountRead>;
  } = {},
): void {
  opened = [];
  read = [];
  (window as unknown as Record<string, unknown>).pywebview = {
    api: {
      open_account_view: (view: string) => {
        opened.push(view);
        return Promise.resolve({
          view,
          url: `https://openrouter.ai/${view}`,
          opened: options.opened ?? true,
        });
      },
      read_account_view: (view: string) => {
        read.push(view);
        return Promise.resolve({
          view,
          url: "https://openrouter.ai/activity",
          ok: true,
          signed_out: false,
          figures: [],
          read_at: 1_700_000_000,
          ...options.read,
        });
      },
    },
  };
}

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).pywebview;
});

const accountButton = (c: HTMLElement, label: string) =>
  all(c, ".usage-account-actions .btn").find(
    (b) => (b.textContent ?? "").trim() === label,
  )!;

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
    assert.match(text, /2 Failed/);
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

describe("the provider's own pages", () => {
  test("the buttons say what they do, and the ids are the ones the host knows", async () => {
    // The ids are a contract with `AccountBrowser.VIEWS`: a name here that the
    // host does not have is a button that opens nothing, and the failure arrives
    // as a rejected promise rather than as a missing window nobody can see.
    //
    // The verbs are the users', and they are load-bearing: "open" puts the page
    // on screen and "read" brings its figures back here, and the two rows are
    // otherwise five nouns whose difference the user has to discover by pressing
    // them. The provider calls the usage page "activity"; the button does not.
    insideHost();
    const container = await open(summary());
    assert.deepEqual(
      all(container, ".usage-account-actions .btn").map((b) => (b.textContent ?? "").trim()),
      ["Open Usage", "Open Credits", "Open API keys", "Read usage", "Read credits"],
    );
    assert.match(container.textContent ?? "", /requests that left from this app/);
  });

  test("each press asks the host for that page, and says which window opened", async () => {
    insideHost();
    const container = await open(summary());

    for (const [label, id] of [
      ["Open Usage", "activity"],
      ["Open Credits", "credits"],
      ["Open API keys", "keys"],
    ] as const) {
      await click(accountButton(container, label));
      await wait(0);
      assert.equal(opened.at(-1), id, `${label} asked for the wrong page`);
    }
    assert.deepEqual(opened, ["activity", "credits", "keys"]);
    // The last press is the one still on screen, and the sentence names the URL
    // rather than the label: "API keys" is the user's word for the page, and the
    // URL is what actually opened.
    assert.match(
      container.textContent ?? "",
      /Opened https:\/\/openrouter\.ai\/keys in a browser window\./,
    );
    // Opening is not reading: three pages were opened and nothing was asked of
    // `read_account_view`, which is the call that costs seconds.
    assert.deepEqual(read, []);
  });

  test("reading asks for that page and draws the figures the page showed", async () => {
    insideHost({
      read: {
        figures: [
          { label: "Credits remaining", value: "$74.25" },
          { label: "Total usage", value: "$25.75" },
        ],
      },
    });
    const container = await open(summary());

    await click(accountButton(container, "Read credits"));
    await wait(0);

    assert.deepEqual(read, ["credits"]);
    assert.deepEqual(
      all(container, ".usage-account-figure dt").map((n) => (n.textContent ?? "").trim()),
      ["Credits remaining", "Total usage"],
    );
    assert.deepEqual(
      all(container, ".usage-account-figure dd").map((n) => (n.textContent ?? "").trim()),
      ["$74.25", "$25.75"],
    );
    // Attributed, because these are somebody else's numbers: without the page and
    // the time, a stale figure is indistinguishable from a current one.
    assert.match(container.textContent ?? "", /Read from https:\/\/openrouter\.ai\/activity at/);
  });

  test("a signed-out read says to sign in rather than showing no usage", async () => {
    // The failure this exists for: a signed-out window rendering as an account
    // with nothing on it. Nothing is not the same as unknown.
    insideHost({ read: { signed_out: true, figures: [] } });
    const container = await open(summary());
    await click(accountButton(container, "Read usage"));
    await wait(0);
    assert.match(container.textContent ?? "", /signed out/);
    assert.equal(one(container, ".usage-account-figures"), null);
  });

  test("a read that could not happen names which way it failed", async () => {
    insideHost({ read: { ok: false, reason: "timeout" } });
    const container = await open(summary());
    await click(accountButton(container, "Read usage"));
    await wait(0);
    assert.match(container.textContent ?? "", /did not finish loading in time/);
  });

  test("a page that was read and showed nothing says exactly that", async () => {
    // Distinct from signed out and distinct from a failed read: the app looked and
    // found no figure, which is news about somebody else's site rather than about
    // the user's account.
    insideHost({ read: { figures: [] } });
    const container = await open(summary());
    await click(accountButton(container, "Read usage"));
    await wait(0);
    assert.match(container.textContent ?? "", /nothing on it looked like a figure/);
  });

  test("a page with no host says so instead of looking broken", async () => {
    // A browser preview is a legitimate place to run this page, so the button is
    // still there and the press still answers -- with the one honest sentence.
    const container = await open(summary());
    await click(accountButton(container, "Open Usage"));
    await wait(0);
    assert.match(container.textContent ?? "", /not running inside the app/);
  });

  test("a window the host refused to create is not reported as opened", async () => {
    // The failure this exists for: saying "opened" about a window that does not
    // exist. The press must answer with the other sentence.
    insideHost({ opened: false });
    const container = await open(summary());
    await click(accountButton(container, "Open Credits"));
    await wait(0);
    assert.match(container.textContent ?? "", /could not be opened/);
    assert.doesNotMatch(container.textContent ?? "", /Opened .* in a browser window/);
  });
});
