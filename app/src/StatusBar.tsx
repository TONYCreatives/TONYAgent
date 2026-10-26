import { capitalizeFirst, prettifyModelName } from "./displayNames.js";

interface Props {
  provider: string;
  model: string;
  sandbox: string;
  connected: boolean;
  /**
   * The core came up with no provider bound.
   *
   * Separate from an empty `provider` so the bar can say *why* there is
   * nothing to send to. A bare "no provider" reads as a display glitch; this
   * is the user being told which action fixes it, in the place they look when
   * Send does nothing.
   */
  needsProvider?: boolean;
  onConfigure?: () => void;
  logLines?: string[];
  logsOpen?: boolean;
  onToggleLogs?: () => void;
}

export function StatusBar({
  provider,
  model,
  sandbox,
  connected,
  needsProvider,
  onConfigure,
  logLines = [],
  logsOpen = false,
  onToggleLogs,
}: Props) {
  return (
    <footer className="statusbar">
      <span className={connected ? "dot dot-ok" : "dot dot-bad"} title={connected ? "Backend running" : "Backend stopped"} />
      {/*
        Named, the two of them, because the narrow-window rule drops them and
        a rule that drops "the second span" is a rule that drops something else
        the moment this row changes -- see the 560px block in `statusbar.css`.
      */}
      <span className="statusbar-state">{connected ? "Connected" : "Disconnected"}</span>
      <span className="sep" />
      {needsProvider ? (
        <button type="button" className="linkish" onClick={onConfigure}>
          No provider &mdash; choose one to start
        </button>
      ) : (
        <span title={`${provider}${model ? ` / ${model}` : ""}`}>
          {provider ? prettifyModelName(provider) : "No provider"}
          {model && ` / ${prettifyModelName(model)}`}
        </span>
      )}
      <span className="sep" />
      <span className="statusbar-sandbox">Sandbox: {capitalizeFirst(sandbox)}</span>
      {/*
        No busy word. It was the third place a turn announced itself -- beside
        the tab spinner and the run card -- and the strip's job is the
        environment: whether the core is up, what it is talking to, where it
        runs. The top bar's pill is the turn's only home now.
      */}
      {onToggleLogs && (
        <button
          type="button"
          className="statusbar-logs"
          onClick={onToggleLogs}
          aria-expanded={logsOpen}
          title={logsOpen ? "Hide logs" : "Show logs"}
        >
          <span>Logs</span>
          {logLines.length > 0 && (
            <span className="statusbar-logs-count">{logLines.length}</span>
          )}
        </button>
      )}
    </footer>
  );
}
