import { useCallback, useEffect, useRef, useState } from "react";
import { TauriBackend } from "./backend";
import { applyEvent, appendUserMessage, initialState, type ChatState } from "./events";
import { Composer } from "./Composer";
import { ConfirmDialog } from "./ConfirmDialog";
import { MessageList } from "./MessageList";
import { StatusBar } from "./StatusBar";

export function App() {
  const [state, setState] = useState<ChatState>(initialState);
  const [connected, setConnected] = useState(false);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [sandbox, setSandbox] = useState("stopped");
  const [logLines, setLogLines] = useState<string[]>([]);

  // One backend per window. Held in a ref rather than state: it is not
  // renderable, and recreating it would spawn a second sidecar.
  const backendRef = useRef<TauriBackend | null>(null);
  if (backendRef.current === null) backendRef.current = new TauriBackend();

  // Pull provider/sandbox out of the event stream. Kept separate from ChatState
  // because these survive a `clear`, and re-reading them on every chat event
  // would be noise.
  useEffect(() => {
    const backend = backendRef.current!;

    const offEvent = backend.onEvent((event) => {
      setState((prev) => applyEvent(prev, event));
      if (event.type === "sandbox.status") {
        const status = event.payload.status;
        if (typeof status === "string") setSandbox(status);
      }
    });

    // onBackendExit registers a single callback and returns nothing to
    // unsubscribe, unlike onEvent. The backend is a per-window singleton and
    // this effect runs once, so there is nothing to tear down here.
    backend.onBackendExit(() => setConnected(false));

    // The sidecar reports its own failures on stderr, and stdout is protocol
    // only -- so without this the UI has no way to show why the core died.
    const offLog = backend.onLog((line) => {
      setLogLines((prev) => [...prev.slice(-40), line]);
    });

    return () => {
      offEvent();
      offLog();
    };
  }, []);

  useEffect(() => {
    const backend = backendRef.current!;
    let cancelled = false;

    const start = async () => {
      try {
        await backend.start();
        if (cancelled) return;
        setConnected(true);
        const snapshot = (await backend.call("state")) as {
          provider?: string;
          model?: string;
        };
        if (cancelled) return;
        setProvider(snapshot.provider ?? "");
        setModel(snapshot.model ?? "");
      } catch (error) {
        if (!cancelled) {
          setConnected(false);
          // The error banner is the user-facing surface; the console keeps the
          // stack for anyone with devtools open.
          console.error("[tonyagent] backend start failed:", error);
          const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
          setState((prev) => ({ ...prev, error: detail }));
        }
      }
    };

    void start();

    // Stop the sidecar on unmount. Without this the Python process outlives
    // the window and keeps holding the sandbox container.
    return () => {
      cancelled = true;
      void backend.stop();
    };
  }, []);

  const send = useCallback(async (text: string) => {
    const backend = backendRef.current!;
    // Optimistic: the user's message appears immediately rather than after a
    // round trip. The core never echoes user text back as an event.
    setState((prev) => appendUserMessage(prev, text));
    try {
      await backend.send(text);
    } catch (error) {
      setState((prev) => ({
        ...prev,
        busy: false,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, []);

  const cancel = useCallback(() => {
    void backendRef.current!.call("cancel").catch(() => {
      /* The turn may already have ended; nothing to report. */
    });
  }, []);

  const respond = useCallback((id: string, confirmed: boolean) => {
    // Clear locally first. The core will also emit confirmation.resolved, but
    // waiting on it would leave the modal up during the round trip.
    setState((prev) => ({ ...prev, pendingConfirm: null }));
    void backendRef.current!.call("confirm.respond", { id, confirmed }).catch((error: unknown) => {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
      }));
    });
  }, []);

  return (
    <div className="app">
      <MessageList messages={state.messages} busy={state.busy} />

      {state.error && <div className="error-banner">{state.error}</div>}

      <Composer busy={state.busy} disabled={!connected} onSend={send} onCancel={cancel} />

      {state.pendingConfirm && <ConfirmDialog request={state.pendingConfirm} onRespond={respond} />}

      {logLines.length > 0 && (
        <div className="logstrip">
          {logLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}

      <StatusBar
        provider={provider}
        model={model}
        sandbox={sandbox}
        connected={connected}
        busy={state.busy}
      />
    </div>
  );
}
