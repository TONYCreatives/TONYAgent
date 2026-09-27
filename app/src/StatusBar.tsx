interface Props {
  provider: string;
  model: string;
  sandbox: string;
  connected: boolean;
  busy: boolean;
}

export function StatusBar({ provider, model, sandbox, connected, busy }: Props) {
  return (
    <footer className="statusbar">
      <span className={connected ? "dot dot-ok" : "dot dot-bad"} title={connected ? "backend running" : "backend stopped"} />
      <span>{connected ? "connected" : "disconnected"}</span>
      <span className="sep" />
      <span>
        {provider || "no provider"}
        {model && ` / ${model}`}
      </span>
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
