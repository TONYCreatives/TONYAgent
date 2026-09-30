interface Props {
  provider: string;
  model: string;
  sandbox: string;
  connected: boolean;
  busy: boolean;
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
}

export function StatusBar({
  provider,
  model,
  sandbox,
  connected,
  busy,
  needsProvider,
  onConfigure,
}: Props) {
  return (
    <footer className="statusbar">
      <span className={connected ? "dot dot-ok" : "dot dot-bad"} title={connected ? "backend running" : "backend stopped"} />
      <span>{connected ? "connected" : "disconnected"}</span>
      <span className="sep" />
      {needsProvider ? (
        <button type="button" className="linkish" onClick={onConfigure}>
          no provider &mdash; choose one to start
        </button>
      ) : (
        <span>
          {provider || "no provider"}
          {model && ` / ${model}`}
        </span>
      )}
      <span className="sep" />
      <span>sandbox: {sandbox}</span>
      {busy && (
        <>
          <span className="sep" />
          <span className="busy">working...</span>
        </>
      )}
    </footer>
  );
}
