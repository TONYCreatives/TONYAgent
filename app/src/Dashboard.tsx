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
        <Tile label="Requests" value={n(totals.requests)} note={totals.failed ? `${n(totals.failed)} failed` : "no failures"} />
        <Tile label="Tokens" value={n(totals.total_tokens)} note={`${n(totals.input_tokens)} in / ${n(totals.output_tokens)} out`} />
        <Tile label="Reasoning" value={n(totals.reasoning_tokens)} note="inside the output count" />
        <Tile
          label="Average"
          value={totals.requests ? duration(totals.duration_ms / totals.requests) : "--"}
          note="per request"
        />
      </div>

      <figure className="usage-figure">
        <figcaption>
          Requests per day
          {busy && <span className="usage-busy"> reading...</span>}
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
            <span>peak {n(peak)}/day</span>
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
                  {entry.failed > 0 && <span className="usage-key-failed">{n(entry.failed)} failed</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </figure>

      {summary?.tracking_since && (
        <p className="usage-since">
          Counting since {new Date(summary.tracking_since * 1000).toLocaleDateString()}.
        </p>
      )}
    </section>
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
