import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TauriBackend } from "./backend";
import { applyEvent, appendUserMessage, initialState, type ChatState } from "./events";
import type { ChatMessage, Role } from "./events";
import { Composer, type ModeInfo } from "./Composer";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  ConversationList,
  type ConversationSummary,
} from "./ConversationList";
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
  // Endpoint override last bound, or "" for the provider default. Kept beside
  // the model because both are "what is this window talking to", not chat state.
  const [baseUrl, setBaseUrl] = useState("");
  /**
   * True when the core came up with no provider bound.
   *
   * Kept distinct from an empty `provider` string so the settings panel does
   * not open over the user's first message every launch: the hint is in the
   * status bar, which is where a user looks for "why can't I send?".
   */
  const [needsProvider, setNeedsProvider] = useState(false);
  const [sandbox, setSandbox] = useState("stopped");
  const [project, setProject] = useState("");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState("");
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [mode, setMode] = useState("build");
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
  const [logsOpen, setLogsOpen] = useState(false);
  /**
   * The left rail's expanded state. FALSE by default: the closed rail is the
   * 70px icon strip, and the wide labelled version is the thing the user
   * opens deliberately. Persisted, because a chrome preference that resets on
   * every launch reads as broken.
   */
  const [railExpanded, setRailExpanded] = useState<boolean>(() => {
    try {
      return localStorage.getItem("tonyagent.rail-expanded") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("tonyagent.rail-expanded", railExpanded ? "1" : "0");
    } catch {
      // Private mode or storage disabled: the preference just does not stick.
    }
  }, [railExpanded]);
  // Closed by default. The Files panel is 425px of a three-column window, and
  // opening it by default squeezed the transcript on a normal laptop width for
  // no benefit until the agent has actually touched a file. It still opens
  // itself the moment a folder is chosen, which is when it has something to say.
  const [filesOpen, setFilesOpen] = useState(false);
  const [fileFilter, setFileFilter] = useState("");

  /**
   * Files changed this session, from the core's own `file_change` artifacts.
   *
   * Two things this deliberately does not do. It does not walk the
   * filesystem -- the core owns what changed, and a second source of truth
   * about the core's state is how the two drift. And it does not scrape a
   * path out of the tool's human-readable `detail`, which is how this worked
   * before Phase 3: a file the agent merely *read* appeared in the tree, and
   * the "+N" badge counted tool invocations rather than lines.
   *
   * The counts are summed, not overwritten, so a file edited three times
   * shows the session total rather than only the last edit -- which is what
   * makes the badge a summary of the session instead of a snapshot of it.
   */
  const treeEntries = useMemo<TreeEntry[]>(() => {
    const byName = new Map<string, TreeEntry>();
    for (const message of state.messages) {
      for (const tool of message.tools) {
        if (!tool.path) continue;
        const existing = byName.get(tool.path);
        byName.set(tool.path, {
          name: tool.path,
          kind: "file",
          depth: 0,
          added: (existing?.added ?? 0) + (tool.added ?? 0),
          removed: (existing?.removed ?? 0) + (tool.removed ?? 0),
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

  /**
   * Bind a provider/model/endpoint on the core and mirror the result locally.
   *
   * One primitive, three callers: app startup, the panel's Apply button, and a
   * key save. It deliberately does not close the panel -- that is Apply's job,
   * and closing it the instant a key is stored would be jarring.
   *
   * Only what the user actually set is sent. An empty field means "provider
   * default", and the core reads a missing key the same way, so omitting it
   * keeps the request minimal and the reply honest.
   */
  const applyBinding = useCallback(
    async (name: string, model: string, endpoint: string) => {
      const params: { name: string; model?: string; base_url?: string } = { name };
      if (model) params.model = model;
      if (endpoint) params.base_url = endpoint;
      const bound = (await backendRef.current!.call("bind_provider", params)) as {
        provider?: string;
        model?: string;
        base_url?: string;
      };
      setProvider(bound.provider ?? name);
      setModel(bound.model ?? model);
      setBaseUrl(bound.base_url ?? endpoint);
      setNeedsProvider(false);
    },
    [],
  );

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
          base_url?: string;
          bound?: boolean;
          project?: string;
          mode?: string;
          conversation?: string;
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
        setBaseUrl(snapshot.base_url ?? "");
        setProject(snapshot.project ?? "");
        setProviders(listed.providers ?? []);
        setMode(snapshot.mode ?? "build");
        if (snapshot.conversation) setConversation(snapshot.conversation);
        await refreshConversations();
        // Modes come from the core for the same reason providers do: a pill
        // list hardcoded here would drift from the tool allow-lists behind
        // it, and the user would be offered a mode that does not exist.
        const modeList = (await backend.call("mode.list")) as {
          modes?: ModeInfo[];
          mode?: string;
        };
        if (cancelled) return;
        setModes(modeList.modes ?? []);
        if (modeList.mode) setMode(modeList.mode);
        // No rebind here. The core restores the saved provider itself, and
        // `state` reports a name only when one is genuinely bound -- so this
        // used to be a workaround for a core that claimed a provider it did
        // not have, and rebinding it again only risked overwriting the
        // selection with the default it was supposed to be reporting.
        if (!snapshot.bound) setNeedsProvider(true);
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

  /**
   * Re-read the list from the core.
   *
   * The core decides what exists, so the list is always fetched rather than
   * patched locally. A locally-maintained copy would have to be updated on
   * create, switch, delete *and* every turn that retitles a conversation, and
   * the one path someone forgets is the one that leaves a stale row on screen
   * pointing at a conversation that no longer exists.
   */
  const refreshConversations = useCallback(async () => {
    const listed = (await backendRef.current!.call("conversations.list")) as {
      conversations?: ConversationSummary[];
    };
    setConversations(listed.conversations ?? []);
  }, []);

  /** Replace the transcript with a conversation's saved messages. */
  const showMessages = useCallback((raw: unknown[]) => {
    const restored: ChatMessage[] = [];
    (raw ?? []).forEach((entry, index) => {
      const message = entry as { role?: string; content?: string | null };
      if (!message.role) return;
      // Tool turns come back as assistant text rather than reconstructed tool
      // cards. Their results are already flattened into the transcript by the
      // core, and a tool call with no card behind it would render as an
      // orphaned heading for work that already happened.
      const role: Role = message.role === "user" ? "user" : "assistant";
      restored.push({
        id: `restored-${index}`,
        role,
        text: message.content ?? "",
        tools: [],
      });
    });
    setState((prev) => ({
      ...prev,
      messages: restored,
      error: null,
      busy: false,
    }));
  }, []);

  /**
   * Open a conversation, or start a new one.
   *
   * Both clear the view first. The core swaps the session underneath us, and
   * the window would otherwise keep showing the old transcript until the reply
   * arrives -- so a click that worked still looks broken while it works.
   */
  const openConversation = useCallback(
    async (id: string) => {
      setState((prev) => ({ ...prev, error: null, busy: true }));
      try {
        const result = (await backendRef.current!.call("conversations.switch", {
          id,
        })) as {
          conversation?: ConversationSummary;
          messages?: unknown[];
        };
        showMessages(result.messages ?? []);
        if (result.conversation) setConversation(result.conversation.id);
        await refreshConversations();
      } catch (error: unknown) {
        setState((prev) => ({
          ...prev,
          busy: false,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },
    [showMessages, refreshConversations],
  );

  const createConversation = useCallback(async () => {
    setState((prev) => ({ ...prev, error: null, busy: true }));
    try {
      const result = (await backendRef.current!.call("conversations.create")) as {
        conversation?: ConversationSummary;
      };
      showMessages([]);
      if (result.conversation) setConversation(result.conversation.id);
      await refreshConversations();
    } catch (error: unknown) {
      setState((prev) => ({
        ...prev,
        busy: false,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, [showMessages, refreshConversations]);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await backendRef.current!.call("conversations.delete", { id });
        // Deleting the open conversation leaves the window on nothing, which
        // reads as a failure rather than as the result that was asked for, so
        // the core clears the transcript and we open a fresh one to replace the
        // row the user just removed.
        if (id === conversation) {
          setConversation("");
          setState((prev) => ({ ...prev, messages: [], error: null }));
        }
        await refreshConversations();
      } catch (error: unknown) {
        setSettingsError(error instanceof Error ? error.message : String(error));
      }
    },
    [conversation, refreshConversations],
  );

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
    setSettingsNotice(null);
    try {
      const result = (await backendRef.current!.call("sandbox.start", {
        path: chosen,
      })) as { running: boolean; isolated?: boolean; project?: string };
      if (!result.running) {
        setSettingsError("The sandbox did not start. See the log below for the reason.");
        return;
      }
      setProject(result.project ?? chosen);
      // The Files panel is the view of this folder; opening it here is what
      // makes the pick feel like it did something.
      setFilesOpen(true);
      // A runtime is not the same as containment. Without Docker the tools
      // still work, but only the two that execute code are unavailable, and
      // saying so is more useful than a green tick that implies otherwise.
      if (result.isolated === false) {
        setSettingsNotice(
          "Working without an isolated sandbox: file, search, web and browser tools are available, but running commands and JavaScript needs Docker.",
        );
      }
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  /**
   * Escape closes the Files overlay.
   *
   * An overlay you can only dismiss by aiming at a small close button is a trap
   * for the keyboard, and the scrim makes the click-anywhere target invisible --
   * there is nothing on screen to say "click here to close". Escape is the
   * affordance that does not depend on seeing anything.
   */
  useEffect(() => {
    if (!filesOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFilesOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filesOpen]);

  const stopSandbox = useCallback(() => {
    void backendRef.current!.call("sandbox.stop").catch((error: unknown) => {
      setSettingsError(error instanceof Error ? error.message : String(error));
    });
  }, []);

  /**
   * The panel's Apply button. Closes the panel on success -- its job is done,
   * and leaving it up after a successful apply just invites a second click.
   */
  const bindProvider = useCallback(
    (name: string, model: string, endpoint: string) => {
      setSettingsError(null);
      void applyBinding(name, model, endpoint)
        .then(() => setSettingsOpen(false))
        .catch((error: unknown) => {
          setSettingsError(error instanceof Error ? error.message : String(error));
        });
    },
    [applyBinding],
  );

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
  const saveKey = useCallback(
    async (saved: string, apiKey: string) => {
      try {
        await backendRef.current!.call("key.save", {
          provider: saved,
          api_key: apiKey,
        });
        // Re-read the provider list so the "(no key)" marker and the Remove
        // button reflect the keyring without this component guessing.
        const listed = (await backendRef.current!.call("providers.list")) as {
          providers?: ProviderInfo[];
        };
        setProviders(listed.providers ?? []);
        // Rebind, so a freshly saved key takes effect immediately instead of
        // silently doing nothing until the user finds Apply. This also
        // reconstructs the provider, which clears any HTTP client cached from
        // an earlier request that was built before the key existed. The model
        // and endpoint are carried over only if they belong to this provider;
        // model ids are provider-specific, so applying another provider's
        // model here would be wrong.
        const same = provider === saved;
        await applyBinding(saved, same ? model : "", same ? baseUrl : "");
        return true;
      } catch {
        return false;
      }
    },
    [provider, model, baseUrl, applyBinding],
  );

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

  const changeMode = useCallback((name: string) => {
    // Optimistic on purpose: the pills feel dead otherwise. The reply then
    // corrects the state to whatever the core actually resolved -- including
    // falling back to Build for a name it does not know, which is the case a
    // local-only update would get permanently wrong.
    setMode(name);
    void backendRef.current!
      .call("mode.set", { mode: name })
      .then((result) => {
        const applied = result as { mode?: string };
        if (applied.mode && applied.mode !== name) setMode(applied.mode);
        // The core clears the conversation on a mode change, so the view has
        // to follow or the transcript would show turns the core has dropped.
        setState((prev) => ({ ...prev, messages: [], error: null }));
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
        void backendRef.current!
          .call("mode.list")
          .then((list) => {
            const current = (list as { mode?: string }).mode;
            if (current) setMode(current);
          })
          .catch(() => {
            /* The banner already says the switch failed. */
          });
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
    <div className={`app${railExpanded ? " rail-open" : ""}`}>
      <div className={`sidecol${railExpanded ? " rail-open" : ""}`}>
        <ConversationList
          conversations={conversations}
          active={conversation}
          busy={state.busy}
          connected={connected}
          onNew={createConversation}
          onOpen={(id) => void openConversation(id)}
          onDelete={(id) => void deleteConversation(id)}
        />
      <IconRail
        connected={connected}
        busy={state.busy}
        messageCount={state.messages.length}
        expanded={railExpanded}
        onToggle={() => setRailExpanded((open) => !open)}
        onClear={clear}
        onCancel={cancel}
        onSettings={() => {
          setSettingsError(null);
          setSettingsOpen(true);
        }}
        onSearch={() => setSearchOpen(true)}
      />
      </div>

      <div className="main">
        <TopBar busy={state.busy} />

        <MessageList messages={state.messages} busy={state.busy} />

        {state.error && <div className="banner">{state.error}</div>}

        {/*
         * Collapsed by default. The strip used to be a permanent 83px block
         * wedged between the transcript and the composer, and at rest the only
         * thing it said was "nothing is wrong" -- space spent saying so. A
         * one-line bar keeps the log one click away and says nothing when it has
         * nothing to say.
         */}
        <div className={`logbar${logsOpen ? " is-open" : ""}`}>
          <button
            type="button"
            className="logbar-toggle"
            onClick={() => setLogsOpen((open) => !open)}
            aria-expanded={logsOpen}
          >
            <span className="logbar-caret">{logsOpen ? "▾" : "▸"}</span>
            <span>Logs</span>
            {logLines.length > 0 && (
              <span className="logbar-count">{logLines.length}</span>
            )}
          </button>
          {logsOpen && (
            <div className="logstrip">
              {logLines.length === 0 ? (
                <div className="logstrip-empty">No log output yet.</div>
              ) : (
                logLines.map((line, i) => <div key={i}>{line}</div>)
              )}
            </div>
          )}
        </div>

        <Composer
          busy={state.busy}
          disabled={!connected}
          model={model}
          modes={modes}
          mode={mode}
          onModeChange={changeMode}
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
            baseUrl={baseUrl}
            project={project}
            sandbox={sandbox}
            trusted={trustedProjects.has(project)}
            error={settingsError}
            notice={settingsNotice}
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
          needsProvider={needsProvider}
          onConfigure={() => {
            setSettingsError(null);
            setSettingsNotice(null);
            setSettingsOpen(true);
          }}
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
