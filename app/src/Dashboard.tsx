/**
 * The usage dashboard: what this window has spent, and on what.
 *
 * A view of the main area rather than a pane, because every question here is a
 * question about a *shape* -- a week of days, a ranking of keys -- and 288px of
 * sidebar would turn both into a list of numbers with no shape to read.
 *
 * **Nothing on this screen is fetched until it is shown.** The summary is asked
 * for when the view opens and when the window changes, and never on a timer: a
 * dashboard that polled would spend the very requests it is counting.
 */

import { useEffect, useState } from "react";

import { openAccountView, readAccountView } from "./account.js";
import type { AccountRead, AccountView } from "./bridge.js";

/** One provider-and-key pair, or provider, as the ledger grouped it. */
export interface UsageGroup {
  provider: string;
  /** The key fingerprint, the model id, or "" for the per-provider roll-up. */
  detail: string;
  requests: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  last_ts: number;
}

export interface UsageBucket {
  day: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageTotals {
  requests: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  duration_ms: number;
}

export interface UsageSummary {
  window: string;
  since: number | null;
  totals: UsageTotals;
  buckets: UsageBucket[];
  by_key: UsageGroup[];
  by_provider: UsageGroup[];
  by_model: UsageGroup[];
  tracking_since: number | null;
}

/**
 * The windows on offer, and what to call them.
 *
 * Named here rather than read from the core, so the strip draws without a round
 * trip. The core validates the name it is sent, so a drift shows up as a
 * refused request rather than as a chart of the wrong period.
 */
const PERIODS = [
  { id: "today", label: "Today" },
  { id: "3d", label: "3 days" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "all", label: "All" },
] as const;

/**
 * The provider's own pages, as the dashboard offers them.
 *
 * The labels are the users': "Usage" rather than "activity", and "Credits"
 * rather than "billing". The ids are the host's, and they are the closed set
 * `AccountBrowser.VIEWS` checks them against.
 */
const ACCOUNT_VIEWS = [
  { id: "activity", label: "Usage" },
  { id: "credits", label: "Credits" },
  { id: "keys", label: "API keys" },
] as const satisfies readonly { id: AccountView; label: string }[];

/**
 * The pages worth reading figures out of, and what to call the button.
 *
 * Not `ACCOUNT_VIEWS` with a different verb: `keys` is on that list because the
 * keys page is where a key is checked and rotated, and there are no figures on it
 * this screen wants. Reading it would be a button that exists to return nothing.
 */
const ACCOUNT_READS = [
  { id: "activity", label: "Read usage" },
  { id: "credits", label: "Read credits" },
] as const satisfies readonly { id: AccountView; label: string }[];

const EMPTY: UsageTotals = {
  requests: 0,
  failed: 0,
  input_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
  total_tokens: 0,
  duration_ms: 0,
};

/** Thousands separators, because a token count is unreadable unseparated. */
const n = (value: number) => new Intl.NumberFormat().format(Math.round(value || 0));

/** "2026-10-10" as "Oct 10", in the reader's own locale and timezone. */
function dayLabel(iso: string): string {
  // `T00:00:00` rather than the bare date: a date-only string is parsed as UTC,
  // which west of Greenwich renders as the day *before* the bucket it labels.
  const at = new Date(`${iso}T00:00:00`);
  return at.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function duration(ms: number): string {
  if (!ms) return "--";
  return ms < 1000 ? `${n(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

interface Props {
  connected: boolean;
  /** Leave the dashboard and go back to the conversation. */
  onClose: () => void;
  /** Ask the core for one window. Resolves to null when it cannot answer. */
  load: (period: string) => Promise<UsageSummary | null>;
}

export function Dashboard({ connected, onClose, load }: Props) {
  const [period, setPeriod] = useState<string>("7d");
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountNote, setAccountNote] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountRead | null>(null);
  const [reading, setReading] = useState(false);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setError(null);
    void load(period).then((result) => {
      // The window can change while a reply is in flight; the late one must not
      // overwrite the newer chart.
      if (!live) return;
      setBusy(false);
      if (result) setSummary(result);
      else setError("Could not read the usage ledger.");
    });
    return () => {
      live = false;
    };
  }, [period, load]);

  /**
   * Open one of the provider's pages, or say why there is none to open.
   *
   * The answer is a sentence either way, because both are things the user has
   * to be told: that a browser window is now showing the page, or that this
   * page has no window to open one in. Silence after a press reads as a broken
   * button.
   */
  const openAccount = async (view: AccountView) => {
    setAccountNote(null);
    try {
      const result = await openAccountView(view);
      if (result.opened) {
        setAccountNote(`Opened ${result.url} in a browser window.`);
      } else {
        setAccountNote(
          result.reason === "no-host"
            ? "This page is not running inside the app, so there is no browser window to open."
            : "The browser window could not be opened.",
        );
      }
    } catch {
      setAccountNote("The browser window could not be opened.");
    }
  };

  /**
   * Read the provider's page and show what it says.
   *
   * Slow, and the view is told so: the host navigates a real window and waits
   * for a page that fetches its own numbers, which is seconds. `AccountView`'s
   * read is the one action here that is not instantaneous, so it is the one with
   * a busy state.
   */
  const readAccount = async (view: AccountView) => {
    setReading(true);
    setAccountNote(null);
    const result = await readAccountView(view);
    setAccount(result);
    setReading(false);
  };

  const totals = summary?.totals ?? EMPTY;
  const buckets = summary?.buckets ?? [];
  const peak = Math.max(1, ...buckets.map((b) => b.requests));
  const byKey = summary?.by_key ?? [];
  const busiest = Math.max(1, ...byKey.map((k) => k.requests));
  const none = totals.requests === 0;

  return (
    <section className="usage" aria-label="Usage dashboard">
      <header className="usage-head">
        <h2>Usage</h2>
        <div className="usage-periods" role="tablist" aria-label="Period">
          {PERIODS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              className={`usage-period${period === entry.id ? " is-active" : ""}`}
              aria-selected={period === entry.id}
              onClick={() => setPeriod(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <button type="button" className="btn" onClick={onClose}>
          Back to chat
        </button>
      </header>

      {error && <p className="warn">{error}</p>}
      {!connected && <p className="warn">The core is not connected, so there is nothing to read.</p>}

      <div className="usage-tiles">
        <Tile label="Requests" value={n(totals.requests)} note={totals.failed ? `${n(totals.failed)} Failed` : "No failures"} />
        <Tile label="Tokens" value={n(totals.total_tokens)} note={`${n(totals.input_tokens)} In / ${n(totals.output_tokens)} Out`} />
        <Tile label="Reasoning" value={n(totals.reasoning_tokens)} note="Inside the output count" />
        <Tile
          label="Average"
          value={totals.requests ? duration(totals.duration_ms / totals.requests) : "--"}
          note="Per request"
        />
      </div>

      <figure className="usage-figure">
        <figcaption>
          Requests per day
          {busy && <span className="usage-busy"> Reading...</span>}
        </figcaption>
        {none ? (
          <p className="usage-empty">
            Nothing recorded in this period yet. Requests appear here as the
            agent talks to a provider.
          </p>
        ) : (
          <div
            className="usage-bars"
            role="img"
            aria-label={`Requests per day, peaking at ${peak}`}
          >
            {buckets.map((bucket) => (
              <div
                key={bucket.day}
                className="usage-bar"
                title={`${dayLabel(bucket.day)}: ${n(bucket.requests)} requests, ${n(bucket.total_tokens)} tokens`}
              >
                <span
                  className={`usage-bar-fill${bucket.requests ? "" : " is-empty"}`}
                  style={{ height: `${Math.round((bucket.requests / peak) * 100)}%` }}
                />
              </div>
            ))}
          </div>
        )}
        {/* `!none` as well as `buckets.length`: an empty window still has its
            days, and the axis under the empty message read "peak 1/day" about
            nothing at all. */}
        {!none && buckets.length > 0 && (
          <div className="usage-axis">
            <span>{dayLabel(buckets[0].day)}</span>
            <span>Peak {n(peak)}/day</span>
            <span>{dayLabel(buckets[buckets.length - 1].day)}</span>
          </div>
        )}
      </figure>

      <figure className="usage-figure">
        <figcaption>By key</figcaption>
        {byKey.length === 0 ? (
          <p className="usage-empty">No keys have been used in this period.</p>
        ) : (
          <ul className="usage-keys">
            {byKey.map((entry) => (
              <li key={`${entry.provider}:${entry.detail}`} className="usage-key">
                <div className="usage-key-line">
                  <span className="usage-key-name" title={`${entry.provider} ${entry.detail}`}>
                    {entry.provider}
                  </span>
                  <code className="usage-key-id">{entry.detail || "--"}</code>
                  <span className="usage-key-count">{n(entry.requests)}</span>
                </div>
                {/* The bar is the share of this list's busiest entry, not of
                    the total: the question a ranking answers is "which of
                    these is biggest", and against the total every bar of a
                    many-key ledger would be a sliver. */}
                <span className="usage-key-track">
                  <span
                    className="usage-key-fill"
                    style={{ width: `${Math.round((entry.requests / busiest) * 100)}%` }}
                  />
                </span>
                <div className="usage-key-meta">
                  <span>{n(entry.total_tokens)} tokens</span>
                  {entry.failed > 0 && <span className="usage-key-failed">{n(entry.failed)} Failed</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </figure>

      <figure className="usage-figure">
        <figcaption>Your provider account</figcaption>
        {/*
          The distinction is the whole point of the panel, so it is stated
          rather than implied: the tiles above are this app's ledger, and the
          account's real usage is a different and larger number.
        */}
        <p className="usage-empty">
          Everything above counts requests that left from this app. Your account&rsquo;s real usage
          — every key on it, every other tool, and the credit balance — is the provider&rsquo;s own
          report, so it opens in a real browser window. You sign in once there; the window keeps
          its own profile, so you stay signed in.
        </p>
        {/*
          Two rows, and the verbs are what tell them apart. "Open" puts the
          provider's page on screen -- which is how the user signs in, and the
          only thing that can be done about a signed-out window. "Read" brings the
          figures back here. A single row of five unlabelled nouns would be five
          buttons whose difference the user has to discover by pressing them.
        */}
        <div className="usage-account-actions">
          {ACCOUNT_VIEWS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className="btn"
              onClick={() => void openAccount(entry.id)}
            >
              Open {entry.label}
            </button>
          ))}
        </div>
        <div className="usage-account-actions">
          {ACCOUNT_READS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className="btn"
              disabled={reading}
              onClick={() => void readAccount(entry.id)}
            >
              {reading ? "Reading..." : entry.label}
            </button>
          ))}
        </div>
        {accountNote && <p className="usage-note">{accountNote}</p>}
        {account && <AccountFigures read={account} />}
      </figure>

      {summary?.tracking_since && (
        <p className="usage-since">
          Counting since {new Date(summary.tracking_since * 1000).toLocaleDateString()}.
        </p>
      )}
    </section>
  );
}

/**
 * What the provider's page said, in as many words as it takes.
 *
 * Four outcomes and four sentences, because they are four different things for the
 * user to do: the page was not reachable, it is the sign-in page, it was read and
 * showed nothing readable, or here are the figures. **The figures are the page's
 * own labels and values, passed through unrenamed and unsorted** -- see
 * `AccountBrowser.EXTRACT` -- so a mis-paired label is visible to the reader
 * instead of hidden behind a nicer name this app chose.
 */
function AccountFigures({ read }: { read: AccountRead }) {
  if (!read.ok) {
    return (
      <p className="usage-note">
        {read.reason === "timeout"
          ? "The page did not finish loading in time. Open it above, then read again."
          : read.reason === "no-window"
            ? "No browser window could be opened to read from."
            : "The page answered with something that could not be read."}
      </p>
    );
  }
  if (read.signed_out) {
    return (
      <p className="usage-note">
        Your browser window is signed out, so there is nothing to read yet. Sign in
        there once — it keeps its own profile — then read again.
      </p>
    );
  }
  if (!read.figures.length) {
    return (
      <p className="usage-note">
        The page was read, but nothing on it looked like a figure. It is somebody else&rsquo;s
        site and it can change without telling this app.
      </p>
    );
  }
  return (
    <>
      <dl className="usage-account-figures">
        {read.figures.map((figure) => (
          <div key={`${figure.label}:${figure.value}`} className="usage-account-figure">
            <dt>{figure.label}</dt>
            <dd>{figure.value}</dd>
          </div>
        ))}
      </dl>
      <p className="usage-note">
        Read from {read.url} at {new Date(read.read_at * 1000).toLocaleTimeString()}.
      </p>
    </>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="usage-tile">
      <span className="usage-tile-label">{label}</span>
      <span className="usage-tile-value">{value}</span>
      <span className="usage-tile-note">{note}</span>
    </div>
  );
}
