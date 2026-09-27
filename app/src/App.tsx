import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TauriBackend } from "./backend";
import { applyEvent, appendUserMessage, initialState, type ChatState } from "./events";
import { Composer } from "./Composer";
import { ConfirmDialog } from "./ConfirmDialog";
import { pickFolder } from "./dialog";
import { FileSidebar, type TreeEntry } from "./FileSidebar";
import { IconRail } from "./IconRail";
import { MessageList } from "./MessageList";
import { SearchPanel, type SearchMatch } from "./SearchPanel";
import { SettingsPanel, type ProviderInfo } from "./SettingsPanel";
import { StatusBar } from "./StatusBar";
import { TopBar } from "./TopBar";

export function App() {
  const [state, setState] = useState<ChatState>(initialState);
  const [connected, setConnected] = useState(false);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [sandbox, setSandbox] = useState("stopped");
  const [project, setProject] = useState("");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  /**
   * Folders this window has trusted.
   *
   * The core keeps trust in memory with no getter, so the UI cannot ask. It
   * remembers what it asked for instead; defaulting to *untrusted* is the safe
   * direction to be wrong in, because a wrongly-trusted folder would skip the
   * confirmation prompt.
   */
  const [trustedProjects, setTrustedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  const [logLines, setLogLines] = useState<string[]>([]);
  const [railOpen, setRailOpen] = useState(true);
  const [filesOpen, setFilesOpen] = useState(true);
  const [fileFilter, setFileFilter] = useState("");

  /**
   * Files touched this session, derived from the tool calls the core reported.
   *
   * The core is the only thing that knows what it changed, so the tree is built
   * from its own tool events rather than by walking the filesystem from the UI --
   * a second source of truth about state the core owns.
   */
  const treeEntries = useMemo<TreeEntry[]>(() => {
    const byName = new Map<string, TreeEntry>();
    for (const message of state.messages) {
      for (const tool of message.tools) {
        // Only file tools carry a path worth listing.
        const match = /\b(read|write|edit|delete)_file\b/.test(tool.name);
        if (!match) continue;
        const detail = tool.detail ?? "";
        const path = detail.split(/[\s,:]/).find((t) => t.includes(".")) ?? detail;
        if (!path) continue;
        const existing = byName.get(path);
        byName.set(path, existing ? { ...existing, added: (existing.added ?? 0) + 1 } : {
          name: path,
          kind: "file",
          depth: 0,
        });
      }
    }
    return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [state.messages]);

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
          project?: string;
        };
        // Provider names come from the core's registry. A local copy would
        // drift the moment a provider is added or renamed, and the panel would
        // offer one the core cannot build.
        const listed = (await backend.call("providers.list")) as {
          providers?: ProviderInfo[];
        };
        if (cancelled) return;
        setProvider(snapshot.provider ?? "");
        setModel(snapshot.model ?? "");
        setProject(snapshot.project ?? "");
        setProviders(listed.providers ?? []);
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

  /**
   * Clear the conversation.
   *
   * Both sides have to agree: the core owns the real history, so dropping the
   * local list alone would leave the next turn replaying messages the user can
   * no longer see. Clear the core first, then the view.
   */
  const clear = useCallback(() => {
    void backendRef.current!
      .call("clear")
      .then(() => {
        setState(initialState);
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
      });
  }, []);

  // "New chat" and "clear" are the same operation for a single-conversation
  // app: there is no session list yet, so a new chat *is* a cleared one.
  const newChat = clear;

  /**
   * Point the sandbox at a folder the user picked.
   *
   * The picker returns null on cancel, which is a normal outcome and must not
   * be reported as an error. Anything else the core rejects -- a path that
   * vanished, a backend that will not start -- surfaces verbatim.
   */
  const chooseFolder = useCallback(async () => {
    const chosen = await pickFolder();
    if (!chosen) return;
    setSettingsError(null);
    try {
      const result = (await backendRef.current!.call("sandbox.start", {
        path: chosen,
      })) as { running: boolean; project?: string };
      if (!result.running) {
        setSettingsError("The sandbox did not start. See the log below for the reason.");
        return;
      }
      setProject(result.project ?? chosen);
      // The Files panel is the view of this folder; opening it here is what
      // makes the pick feel like it did something.
      setFilesOpen(true);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  const stopSandbox = useCallback(() => {
    void backendRef.current!.call("sandbox.stop").catch((error: unknown) => {
      setSettingsError(error instanceof Error ? error.message : String(error));
    });
  }, []);

  const bindProvider = useCallback((name: string, model: string) => {
    setSettingsError(null);
    void backendRef.current!
      .call("bind_provider", model ? { name, model } : { name })
      .then((result) => {
        const bound = result as { provider?: string; model?: string };
        setProvider(bound.provider ?? name);
        setModel(bound.model ?? model);
        // Close on success: the panel's job is done, and leaving it up after
        // a successful apply just invites a second click.
        setSettingsOpen(false);
      })
      .catch((error: unknown) => {
        setSettingsError(error instanceof Error ? error.message : String(error));
      });
  }, []);

  const setTrust = useCallback((target: string, trusted: boolean) => {
    setTrustedProjects((prev) => {
      const next = new Set(prev);
      if (trusted) next.add(target);
      else next.delete(target);
      return next;
    });
    void backendRef.current!.call("trust.set", { project: target, trusted }).catch((error: unknown) => {
      setTrustedProjects((prev) => {
        const next = new Set(prev);
        // Roll the checkbox back: the core refused, so the UI must not claim
        // the folder is trusted.
        if (trusted) next.delete(target);
        else next.add(target);
        return next;
      });
      setSettingsError(error instanceof Error ? error.message : String(error));
    });
  }, []);

  /**
   * Store an API key in the OS keyring.
   *
   * Resolves to a boolean rather than throwing: the panel reports success or
   * failure inline, and the core's own error text is deliberately vague about
   * *why* it failed, because the keyring's message can quote the value.
   */
  const saveKey = useCallback(async (provider: string, apiKey: string) => {
    try {
      await backendRef.current!.call("key.save", { provider, api_key: apiKey });
      // Re-read the provider list so the "(no key)" marker and the Remove
      // button reflect the keyring without this component guessing.
      const listed = (await backendRef.current!.call("providers.list")) as {
        providers?: ProviderInfo[];
      };
      setProviders(listed.providers ?? []);
      return true;
    } catch {
      return false;
    }
  }, []);

  const deleteKey = useCallback(async (provider: string) => {
    try {
      await backendRef.current!.call("key.delete", { provider });
      const listed = (await backendRef.current!.call("providers.list")) as {
        providers?: ProviderInfo[];
      };
      setProviders(listed.providers ?? []);
      return true;
    } catch {
      return false;
    }
  }, []);

  const search = useCallback(async (pattern: string): Promise<SearchMatch[]> => {
    const result = (await backendRef.current!.call("search", { pattern })) as {
      matches?: SearchMatch[];
    };
    return result.matches ?? [];
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
    <div className={`app${railOpen ? "" : " rail-collapsed"}`}>
      {railOpen && (
        <IconRail
          connected={connected}
          busy={state.busy}
          messageCount={state.messages.length}
          onNewChat={newChat}
          onClear={clear}
          onCancel={cancel}
          onSettings={() => {
            setSettingsError(null);
            setSettingsOpen(true);
          }}
          onSearch={() => setSearchOpen(true)}
        />
      )}

      <div className="main">
        <TopBar
          busy={state.busy}
          connected={connected}
          onNewChat={newChat}
          onClear={clear}
          onToggleRail={() => setRailOpen((open) => !open)}
        />

        <MessageList messages={state.messages} busy={state.busy} />

        {state.error && <div className="banner">{state.error}</div>}

        {logLines.length > 0 && (
          <div className="logstrip">
            {logLines.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        )}

        <Composer
          busy={state.busy}
          disabled={!connected}
          model={model}
          onSend={send}
          onCancel={cancel}
        />

        {state.pendingConfirm && <ConfirmDialog request={state.pendingConfirm} onRespond={respond} />}

        {settingsOpen && (
          <SettingsPanel
            connected={connected}
            busy={state.busy}
            providers={providers}
            provider={provider}
            model={model}
            project={project}
            sandbox={sandbox}
            trusted={trustedProjects.has(project)}
            error={settingsError}
            onClose={() => setSettingsOpen(false)}
            onChooseFolder={chooseFolder}
            onStopSandbox={stopSandbox}
            onBindProvider={bindProvider}
            onTrust={setTrust}
            onSaveKey={saveKey}
            onDeleteKey={deleteKey}
          />
        )}

        {searchOpen && (
          <SearchPanel
            connected={connected}
            hasProject={project !== ""}
            onClose={() => setSearchOpen(false)}
            onSearch={search}
          />
        )}

        <StatusBar
          provider={provider}
          model={model}
          sandbox={sandbox}
          connected={connected}
          busy={state.busy}
        />
      </div>

      <FileSidebar
        entries={treeEntries}
        filter={fileFilter}
        onFilterChange={setFileFilter}
        onToggle={() => setFilesOpen((v) => !v)}
        onChooseFolder={chooseFolder}
        hasProject={project !== ""}
        open={filesOpen}
      />
    </div>
  );
}
