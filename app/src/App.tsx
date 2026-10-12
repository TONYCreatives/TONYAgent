import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CoreBackend } from "./backend.js";
import {
  applyEvent,
  appendUserMessage,
  blankMessage,
  initialState,
  type ChatState,
} from "./events.js";
import type { ChatMessage, Role } from "./events.js";
import { Composer, type ModeInfo } from "./Composer.js";
import { ConfirmDialog } from "./ConfirmDialog.js";
import {
  ConversationList,
  type ConversationSummary,
  type SidebarPane,
} from "./ConversationList.js";
import { pickFolder } from "./dialog.js";
import { CodeViewer, type ViewerFile } from "./CodeViewer.js";
import { diffLines, type LineRange } from "./diff.js";
import { FilesPane } from "./FileSidebar.js";
import { changesFrom, type CoreTreeEntry } from "./filetree.js";
import { DEFAULT_PALETTE } from "./highlight.js";
import { IconRail } from "./IconRail.js";
import { Dashboard, type UsageSummary } from "./Dashboard.js";
import { petDraw, petSet, petState } from "./pet.js";
import { petStatus } from "./pet-status.js";
import { MessageList } from "./MessageList.js";
import {
  summaryLine,
  textFromContent,
  toWire,
  type PendingAttachment,
} from "./attachments.js";
import { ModelPicker, type ModelList } from "./ModelPicker.js";
import { Overlay } from "./Overlay.js";
import { QuestionDialog } from "./QuestionDialog.js";
import { SearchPanel, type SearchMatch } from "./SearchPanel.js";
import type { PermissionList, ReasoningInfo } from "./SettingsMenus.js";
import type { SkillInfo } from "./SkillPicker.js";
import { SettingsPanel, type KeyEntry, type ProviderInfo } from "./SettingsPanel.js";
import { StatusBar } from "./StatusBar.js";
import { TopBar, type Tab } from "./TopBar.js";
import { useDelayedUnmount, useLastValue } from "./useDelayedUnmount.js";
import { useWindowControls } from "./useWindowControls.js";

/**
 * The whole window.
 *
 * `backend` is a seam, not a setting. The default builds the real host
 * client, which is what the shipped window wants; a test passes one built over
 * a fake transport, which is what makes this component renderable at all.
 *
 * **Why the prop is the concrete `CoreBackend` and not an interface.** The
 * obvious move is to declare a `Backend` interface and pass a plain object, and
 * it is the wrong one here: an interface is a second statement of the protocol,
 * and this file's own module comment records what that costs -- a second
 * implementation that drifts from the first. `CoreBackend`'s constructor
 * already takes a transport factory, so a test can supply the *bytes* and still
 * exercise the real framing, request ids, reply routing and error handling
 * underneath. The protocol is verified once and the window is verified on top
 * of it.
 *
 * Read once, on mount. A window does not change which core it is talking to
 * mid-session, and treating it as a prop that could change would mean every
 * effect that reaches for the backend would have to handle being swapped under
 * it.
 *
 * `pickProject` is the same kind of seam for the folder picker, and it is here
 * for one reason rather than for symmetry: "New chat" asks for a folder when
 * none is open, so that branch opens a *native dialog*, and a native dialog is
 * not reachable from jsdom. Left un-injected it could only ever be verified by
 * driving the packaged app and watching a folder picker appear -- which is
 * exactly how the project binding went unnoticed for as long as it did.
 */
/**
 * The id of the Usage tab.
 *
 * A sentinel rather than a conversation id, and deliberately *not* shaped like
 * one: it can never collide with a real conversation, so the strip's callbacks
 * can tell the two kinds apart by identity instead of searching the
 * conversation list on every click.
 */
const USAGE_TAB = "usage-tab";

/**
 * The two things the main area can be: the conversation, or the code.
 *
 * A mode rather than a tab, and it replaced the viewer's tab when this
 * arrived. Two ways to reach one surface is two states to keep in step --
 * "which tab is in front" and "which mode am I in" can disagree, and the
 * window then shows a file while the strip highlights a chat. The strip
 * keeps one job (which conversation), the switch keeps the other.
 */
type MainMode = "agent" | "code";

/**
 * A folder path split into where it lives and what it is called.
 *
 * Both separators, because the core reports the platform's own: Windows paths
 * arrive with backslashes and the walk in the sandbox answers with forward
 * slashes, and an explorer that only split one of them would show the whole
 * path in the name slot for half of its users. The cut is kept *in* the
 * directory half so the two pieces put back together are the path again.
 */
function splitFolder(path: string): [string, string] {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut === -1 ? ["", path] : [path.slice(0, cut + 1), path.slice(cut + 1)];
}

export function App({
  backend: injected,
  pickProject: injectedPick,
}: {
  backend?: CoreBackend;
  pickProject?: () => Promise<string | null>;
} = {}) {
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
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  /**
   * The per-turn tool call budget, as the core last reported it.
   *
   * Null until read. The control says "reading" rather than drawing a number
   * it does not have, because this number is what the reader uses to tell
   * whether a turn is about to be cut off.
   */
  const [maxToolCalls, setMaxToolCalls] = useState<number | null>(null);
  const [budgetOpen, setBudgetOpen] = useState(false);
  /**
   * The Usage tab: absent, open as a tab, or open and showing.
   *
   * Three states rather than a boolean plus a tab list, because the tab and the
   * view are one thing -- `open` is a tab you are not looking at, which is what
   * every other tab in this strip can be. It is never persisted: reopening the
   * window on a chart would hide the conversation it was left on.
   */
  const [usageTab, setUsageTab] = useState<"closed" | "open" | "active">("closed");
  /**
   * The provider's model list, or null before it has been read.
   *
   * Null and empty are different things and the menu says which is which: an
   * unread list is "Loading", and a provider that returned nothing is an error
   * from the core rather than an empty dropdown a user has to interpret.
   */
  const [modelList, setModelList] = useState<ModelList | null>(null);
  const [modelListError, setModelListError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState("");
  /**
   * The chats open in the title bar's tab strip, in the order they were opened.
   *
   * **A tab is an open conversation, not a copy of one.** The core holds a single
   * session, so switching tabs is `conversations.switch` and the transcript is
   * re-read. Nothing is duplicated, and two tabs cannot disagree about what a
   * chat says, because there is only ever one of it.
   *
   * The active tab is `conversation`, above -- one piece of state rather than two
   * that would have to be kept in step.
   */
  const [tabs, setTabs] = useState<string[]>([]);
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [mode, setMode] = useState("build");
  /**
   * What the `/` menu offers. Read when the menu opens, not at mount.
   *
   * Deliberately not fetched alongside the modes above: the mode list is fixed
   * while the process runs, and this one changes whenever the user saves a file
   * in their editor -- so a copy taken at launch would be wrong exactly when
   * someone is looking at it. It is also the reason there is no refresh button
   * anywhere for this: the refresh is the act of opening the menu.
   */
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  /**
   * How much the agent may do, and the ladder it sits on.
   *
   * `permissionList` is null until the core has read it, which is why the bar
   * renders nothing in that window: a row of segments naming a choice nobody
   * has been told the terms of is worse than no bar.
   *
   * Held as the core reported it rather than as a local guess. An unrecognised
   * name resolves to the core's default, so a bar that echoed the request back
   * would be labelling a level the orchestrator is not enforcing -- and this
   * control's whole claim is that it is real.
   */
  const [permissionList, setPermissionList] = useState<PermissionList | null>(null);
  const [permission, setPermission] = useState("");
  const [reasoning, setReasoning] = useState<ReasoningInfo | null>(null);
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
   * Whether the conversation panel is open.
   *
   * FALSE by default: an empty panel held 255px of the window open to report
   * that there was nothing to report, and it covered the transcript while it
   * did. Persisted, because a chrome preference that resets on every launch
   * reads as broken.
   */
  const [railExpanded, setRailExpanded] = useState<boolean>(() => {
    try {
      return localStorage.getItem("tonyagent.rail-expanded") === "1";
    } catch {
      return false;
    }
  });

  /**
   * The panel stays mounted for the length of its exit animation.
   *
   * Without this the panel is deleted from the tree the instant it closes, and
   * an unmounted node has no box to animate -- so `slide-out-left` could never
   * play and closing would be a cut however long the keyframe claimed to be.
   * This is the same hook the files panel and the row menu use, and the reason
   * it exists rather than a plain conditional is in its own comment.
   */
  const conversationsMounted = useDelayedUnmount(railExpanded);

  /*
   * The caption buttons. Null when there is no window, so the bar draws nothing
   * rather than drawing three controls with nothing behind them.
   *
   * Read here and passed into the bar rather than called inside it so the top
   * bar stays a pure component -- the window is the shell's business, and a
   * title bar that reached for it itself could not be rendered in a test or in
   * a browser.
   */
  const windowControls = useWindowControls();
  useEffect(() => {
    try {
      localStorage.setItem("tonyagent.rail-expanded", railExpanded ? "1" : "0");
    } catch {
      // Private mode or storage disabled: the preference just does not stick.
    }
  }, [railExpanded]);

  /*
   * The window owns three open/closed flags and nothing else about how a
   * surface behaves. `<Overlay>` handles staying mounted for the exit
   * animation; the log strip, which is not an overlay, handles its own.
   *
   * The confirmation is the one that carries content -- which tool, which
   * arguments -- so it needs the same retention as the row menu: the request
   * has to still be there to render while the dialog fades out, or it empties
   * itself mid-exit.
   */
  const logsMounted = useDelayedUnmount(logsOpen);
  const shownConfirm = useLastValue(state.pendingConfirm);
  const shownAsk = useLastValue(state.pendingAsk);
  /**
   * Which pane the left sidebar is showing, and the tree's filter.
   *
   * The Files tree was a panel of its own on the right edge of the window, and
   * Settings and Search were dialogs over it; all three are panes of the one
   * sidebar now, so "is it open" is no longer a question about a surface -- the
   * sidebar is the surface, and this says which of its four faces is in front.
   * It still switches to Files the moment a folder is chosen, which is when the
   * tree has something to say.
   */
  const [sidebarPane, setSidebarPane] = useState<SidebarPane>("chats");
  const [fileFilter, setFileFilter] = useState("");

  /**
   * The project tree, as the core's walk reports it.
   *
   * Flat rows in, tree out: `buildTree` adds the depth, the collapse and the
   * filter, so this is only ever the core's own answer to "what is in this
   * folder". It is re-read when a folder is bound and again when a turn ends,
   * because the agent's writes are what change it -- a tree that still showed
   * a file the agent had just deleted would be the pane lying about the
   * project.
   */
  const [treeEntries, setTreeEntries] = useState<CoreTreeEntry[]>([]);
  const [treeTruncated, setTreeTruncated] = useState(false);
  const [treeLoading, setTreeLoading] = useState(false);

  /**
   * The code viewer: which file, and what the core said about it.
   *
   * One file at a time. `viewerFile` is whatever `files.read` answered --
   * text, an image, or a file with no preview -- so the pane's own shape is
   * the core's answer rather than a decision taken here from the extension.
   */
  const [viewerPath, setViewerPath] = useState("");
  const [viewerFile, setViewerFile] = useState<ViewerFile | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerSaving, setViewerSaving] = useState(false);
  /**
   * Whether the open file may be typed into.
   *
   * The user's switch, and it starts **on** for every file the viewer opens:
   * read-only is the safe direction to be wrong in, and a file that turned up
   * editable because of a preference set days ago is a surprise nobody asked
   * for. The turn lock overrides it either way -- see `CodeViewer`.
   */
  const [readOnly, setReadOnly] = useState(true);
  /**
   * Hand edits, per file, waiting to be told to the agent.
   *
   * Keyed by path so a file edited three times sends one entry with the
   * *current* line ranges rather than three overlapping reports; the counts
   * are the core's own (`files.write` computes them with the same line-diff
   * the agent's tools use) and the ranges are `diffLines`'s, because only the
   * window knows what the keystrokes did. Cleared when the message carrying
   * them is sent: they describe what the agent has not seen yet.
   */
  const [pendingEdits, setPendingEdits] = useState<
    Map<string, { added: number; removed: number; lines: LineRange[] }>
  >(new Map());
  /** Which half of the main area is in front. */
  const [mainMode, setMainMode] = useState<MainMode>("agent");
  /** Guards a slow read from overwriting a file the user has moved on from. */
  const viewerPathRef = useRef("");
  /**
   * The dirty flag, readable from callbacks that must not close over it.
   *
   * `openFile` has stable identity on purpose -- it is handed to the tree,
   * which re-renders on every keystroke of the filter -- so it cannot read the
   * state variable without becoming a new function on every edit, and it must
   * not read a stale one.
   */
  const viewerDirtyRef = useRef(false);

  /**
   * The syntax palette, which is a window preference and not project state.
   *
   * Persisted for the same reason the rail's state is: a colour scheme that
   * resets on every launch reads as broken rather than as a default.
   */
  const [palette, setPalette] = useState<string>(() => {
    try {
      return localStorage.getItem("tonyagent.code-palette") ?? DEFAULT_PALETTE;
    } catch {
      return DEFAULT_PALETTE;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("tonyagent.code-palette", palette);
    } catch {
      // Private mode or storage disabled: the preference just does not stick.
    }
  }, [palette]);

  /**
   * Bring one of the sidebar's panes forward.
   *
   * Two state changes that have to happen together: the pane, and the sidebar
   * that shows it. Settings and search used to open as overlays and needed only
   * the first; as panes they need both, and a caller that set the pane alone
   * would be pointing at a panel nobody can see.
   */
  const openSidebarPane = useCallback((pane: SidebarPane) => {
    setSidebarPane(pane);
    setRailExpanded(true);
  }, []);

  /**
   * What the agent changed this session, per file.
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
   *
   * These are *badges on the tree*, not the tree: the rows come from the
   * core's walk (`files.tree`), so a file nobody has touched yet is still
   * reachable. This is the overlay of what happened to them.
   */
  const fileChanges = useMemo(() => {
    const artifacts: Array<{ path?: string; added?: number; removed?: number }> = [];
    for (const message of state.messages) {
      for (const tool of message.tools) {
        if (!tool.path) continue;
        artifacts.push({ path: tool.path, added: tool.added, removed: tool.removed });
      }
    }
    return changesFrom(artifacts);
  }, [state.messages]);

  // One backend per window. Held in a ref rather than state: it is not
  // renderable, and recreating it would start a second core. The `?? null`
  // is what lets an injected backend skip that construction entirely, so a
  // test never reaches `makeHostTransport`.
  const backendRef = useRef<CoreBackend | null>(injected ?? null);
  if (backendRef.current === null) backendRef.current = new CoreBackend();

  // The folder picker, on the same terms as the backend: the real one by
  // default, a stub where a test can choose what "the user picked a folder" and
  // "the user cancelled" look like. Both are outcomes the window has to handle
  // differently, and neither can be produced from a test without this.
  //
  // Assigned once and read through `pickRef`, so a caller cannot swap the
  // picker out mid-session -- the same reason the backend is held in a ref.
  const pickRef = useRef(injectedPick ?? pickFolder);

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

    // The core reports its own failures on stderr, and stdout is protocol
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
          permission?: string;
          conversation?: string;
          sandbox?: string;
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
        if (snapshot.permission) setPermission(snapshot.permission);
        if (snapshot.conversation) {
          setConversation(snapshot.conversation);
          // The strip starts with what the core was already on, so a window that
          // reloads keeps the tab it was looking at rather than opening an empty
          // one beside it.
          setTabs([snapshot.conversation]);
        }
        // The core is asked what it has, not what this window last did. The
        // sandbox outlives a window -- it is shared -- so a reload that assumed
        // "stopped" would offer Start over a runtime that is already up, and a
        // reload that assumed "running" would hide Stop over one that is not.
        if (snapshot.sandbox) setSandbox(snapshot.sandbox);
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
        // The ladder itself. Read from the core because the four levels carry
        // the tool allow-lists they enforce, and a frontend copy would drift
        // from them silently -- the bar would read "Medium" over a gate that
        // had since become Full.
        const permissions = (await backend.call("permission.list")) as PermissionList;
        if (cancelled) return;
        setPermissionList(permissions);
        if (permissions.permission) setPermission(permissions.permission);
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

    // Stop the *client* on unmount, not the core.
    //
    // The core belongs to the host, and the host reaps it when the window
    // closes -- so there is no process here to end. What this releases is this
    // page's end of the conversation: replies still in flight are failed and the
    // transport is dropped, so a remount starts clean rather than inheriting a
    // half-torn-down connection.
    return () => {
      cancelled = true;
      void backend.stop();
    };
  }, []);

  const send = useCallback(async (text: string, attachments: PendingAttachment[] = []) => {
    const backend = backendRef.current!;
    // What the user changed by hand since the last message, on its way to the
    // agent. Cleared only after the send is accepted, so a refused message
    // does not lose the report it was going to carry.
    const edits = [...pendingEdits.entries()].map(([path, change]) => ({
      path,
      added: change.added,
      removed: change.removed,
      lines: change.lines,
    }));
    // Optimistic: the user's message appears immediately rather than after a
    // round trip. The core never echoes user text back as an event. The
    // attachment names stand in for the message text when there is none,
    // because a message that was only a screenshot would otherwise render as
    // an empty bubble in the user's own transcript.
    setState((prev) => appendUserMessage(prev, text || summaryLine(attachments)));
    try {
      await backend.send(text, toWire(attachments), edits);
      if (edits.length) setPendingEdits(new Map());
    } catch (error) {
      setState((prev) => ({
        ...prev,
        busy: false,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, [pendingEdits]);

  const cancel = useCallback(() => {
    void backendRef.current!.call("cancel").catch(() => {
      /* The turn may already have ended; nothing to report. */
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

  /**
   * Read the project tree from the core.
   *
   * A failure is an empty tree rather than a banner. The two reasons it can
   * fail -- no folder bound yet, or a folder that has since vanished -- are
   * both normal states the pane's own empty message describes better than an
   * error strip over an empty sidebar would.
   */
  const loadTree = useCallback(async () => {
    const backend = backendRef.current;
    if (!backend) return;
    setTreeLoading(true);
    try {
      const reply = (await backend.call("files.tree", {})) as {
        entries?: CoreTreeEntry[];
        truncated?: boolean;
      };
      setTreeEntries(reply.entries ?? []);
      setTreeTruncated(Boolean(reply.truncated));
    } catch {
      setTreeEntries([]);
      setTreeTruncated(false);
    } finally {
      setTreeLoading(false);
    }
  }, []);

  /**
   * Read one file into the viewer. The shared half of open and discard.
   *
   * Deliberately not "reset the read-only switch": discarding a buffer must
   * not quietly unlock a file the user had made read-only, and opening a
   * *new* file is the only thing that should start locked again.
   */
  const loadFile = useCallback(async (path: string) => {
    viewerPathRef.current = path;
    setViewerPath(path);
    setViewerFile(null);
    setViewerError(null);
    setViewerLoading(true);
    try {
      const reply = (await backendRef.current!.call("files.read", { path })) as ViewerFile;
      // A reply for a file the user has since closed or replaced would put
      // the wrong bytes under the right path in the header.
      if (viewerPathRef.current !== path) return;
      setViewerFile(reply);
    } catch (error: unknown) {
      if (viewerPathRef.current !== path) return;
      setViewerError(error instanceof Error ? error.message : String(error));
    } finally {
      if (viewerPathRef.current === path) setViewerLoading(false);
    }
  }, []);

  /**
   * Open a file in the viewer.
   *
   * A read, always: what comes back is text, a picture, or a file the window
   * cannot draw, and the pane renders whichever it is. Opening a file also
   * brings the code half of the window to the front, because a file the user
   * cannot see is a file they did not open.
   *
   * **A dirty buffer refuses the switch.** There is one viewer and one
   * buffer, so opening another file would discard what the user typed -- and
   * the editor they are imitating would not do that either. The refusal is
   * visible rather than silent: the dirty marker and its hint stay on screen,
   * and nothing changes.
   */
  const openFile = useCallback(
    async (path: string) => {
      if (viewerDirtyRef.current && path !== viewerPathRef.current) return;
      setMainMode("code");
      // Read-only again for every newly opened file: the switch is about the
      // file in front of you, not a global preference.
      setReadOnly(true);
      await loadFile(path);
    },
    [loadFile],
  );

  /**
   * Save the viewer's buffer.
   *
   * The core writes it atomically and answers with what changed; the pane is
   * then handed the text that is now on disk, which is what clears the dirty
   * state. The change is recorded twice over: as a badge on the tree (so the
   * file looks edited, the same way the agent's writes do) and as a pending
   * report for the next message, which is how the agent finds out that the
   * file it remembers is not the file that is there.
   */
  const saveFile = useCallback(
    async (content: string) => {
      const path = viewerPathRef.current;
      if (!path || viewerFile?.kind !== "text") return;
      const before = viewerFile.content;
      if (content === before) return;
      setViewerSaving(true);
      try {
        const saved = (await backendRef.current!.call("files.write", {
          path,
          content,
        })) as {
          path: string;
          size: number;
          total_lines: number;
          added: number;
          removed: number;
          language: string;
        };
        if (viewerPathRef.current !== path) return;
        // The diff is computed here rather than taken from the reply because
        // the reply counts *lines* and the report needs *which* lines -- and
        // the counts it does carry are the core's own, so the tree's badge
        // and the agent's report cannot disagree about how much changed.
        const diff = diffLines(before, content);
        setPendingEdits((previous) => {
          const next = new Map(previous);
          next.set(path, { added: saved.added, removed: saved.removed, lines: diff.ranges });
          return next;
        });
        setViewerFile({
          kind: "text",
          path,
          content,
          total_lines: saved.total_lines,
          language: saved.language,
          size: saved.size,
        });
        setViewerError(null);
      } catch (error: unknown) {
        setViewerError(error instanceof Error ? error.message : String(error));
      } finally {
        setViewerSaving(false);
      }
    },
    [viewerFile],
  );

  /**
   * Throw the buffer away and go back to what is on disk.
   *
   * Re-reading is what discards it: the draft lives in the viewer and is
   * keyed on the content it was loaded from, so handing back the same content
   * clears it. Nothing is written.
   */
  const discardFile = useCallback(() => {
    const path = viewerPathRef.current;
    if (path) void loadFile(path);
  }, [loadFile]);

  /** Put the viewer away, keeping the tree's other state as it is. */
  const closeViewer = useCallback(() => {
    viewerPathRef.current = "";
    setViewerPath("");
    setViewerFile(null);
    setViewerError(null);
    viewerDirtyRef.current = false;
  }, []);

  /**
   * Read the tree once per folder, and again whenever a turn ends.
   *
   * The ref rather than the state is what keeps this from looping: a folder
   * that legitimately has no files would otherwise re-trigger the read on
   * every render for ever, because "no entries" is exactly what it just set.
   */
  const treeFolderRef = useRef("");
  const wasBusyRef = useRef(false);
  useEffect(() => {
    const finished = wasBusyRef.current && !state.busy;
    wasBusyRef.current = state.busy;
    if (!connected || project === "") return;
    if (treeFolderRef.current === project && !finished) return;
    treeFolderRef.current = project;
    void loadTree();
  }, [connected, project, state.busy, loadTree]);

  /**
   * The desktop pet's toggle, and whether the card is up.
   *
   * Two booleans, and they are not the same one. `wanted` is what the shell
   * remembered from the last run; `petOpen` is whether a window exists now,
   * which a webview can refuse. The button draws the second and the boot below
   * acts on the first -- a toggle that drew the remembered value would claim a
   * card that had never been created.
   */
  const [petOpen, setPetOpen] = useState(false);

  useEffect(() => {
    let live = true;
    void petState().then(async (reply) => {
      if (!live || !reply.wanted) return;
      // Asked for last time, so it comes back. The reply to *this* is what the
      // toggle shows: the shell only knows whether the window was made.
      const now = await petSet(true);
      if (live) setPetOpen(now.open);
    });
    return () => {
      live = false;
    };
  }, []);

  /**
   * Tell the card what the agent is doing, when it changes.
   *
   * Keyed on the status rather than fired from the effect's dependencies: `state`
   * changes on every streamed token, and a host round trip per token is a feature
   * that costs more than the requests it is reporting on. A ref holds the last
   * thing sent, so the pet hears about changes and nothing else.
   */
  const petSentRef = useRef("");
  useEffect(() => {
    const status = petStatus(state);
    const key = `${status.mood}|${status.label}|${status.detail}`;
    if (key === petSentRef.current) return;
    petSentRef.current = key;
    void petDraw(status);
  }, [state]);

  /** Show or hide the card, and believe the shell about the result. */
  const togglePet = useCallback(async () => {
    const next = !petOpen;
    const reply = await petSet(next);
    setPetOpen(reply.open);
  }, [petOpen]);

  /**
   * The name of the open conversation, for the top bar.
   *
   * Read out of the list rather than held separately, because the list is
   * re-fetched from the core after every change -- including a rename, which
   * means this follows the new name without anyone having to remember to
   * update a second copy of it.
   */
  /**
   * What the strip draws: one entry per open tab.
   *
   * Built from the list rather than from a second copy of the titles, so a rename
   * shows up in the tab without anything having to remember to update it -- the
   * same reason `activeTitle` is read out of the list.
   *
   * `renameable` is the row's `message_count` and not its title. A chat with no
   * messages has a placeholder name, and renaming it would take the automatic
   * title away from the first thing the user says: the core retitles only while
   * the name is still "New chat", so a name typed into an empty chat is a name
   * that chat can never outgrow.
   */
  const tabStrip = useMemo(
    () => {
      const strip: Tab[] = tabs.map((id) => {
        const row = conversations.find((c) => c.id === id);
        return {
          id,
          title: row?.title ?? "",
          renameable: (row?.message_count ?? 0) > 0,
        };
      });
      // Appended rather than pinned to the front: it opens when it is opened,
      // like every other tab here, and putting it first would renumber the
      // strip every time it was closed.
      if (usageTab !== "closed") {
        strip.push({ id: USAGE_TAB, title: "Usage", renameable: false });
      }
      return strip;
    },
    [tabs, conversations, usageTab],
  );

  /**
   * Re-read what the bound model can be asked to think.
   *
   * Called whenever the model can have changed, because the answer belongs to
   * the model: the same dropdown is five options on one model and correctly
   * absent on the next. Failures leave it null, which hides the control
   * rather than showing one that would be refused.
   */
  const refreshReasoning = useCallback(async (cancelled?: boolean) => {
    const backend = backendRef.current;
    if (!backend) return;
    try {
      const listed = (await backend.call("reasoning.list")) as ReasoningInfo;
      if (cancelled) return;
      setReasoning(listed);
    } catch (error: unknown) {
      if (cancelled) return;
      // An unread answer is an absent control, not an error the user has to
      // clear: the model still works, it just thinks however it thinks.
      setReasoning(null);
      console.warn("Could not read reasoning support:", error);
    }
  }, []);

  const changeReasoning = useCallback(async (effort: string) => {
    // Painted straight away, because the core has to write the choice to disk
    // and a dropdown that lags a round trip feels broken. The reply corrects
    // it if the model refuses, which is the same contract `changeMode` has.
    setReasoning((prev) => (prev ? { ...prev, effort } : prev));
    try {
      const applied = (await backendRef.current!.call("reasoning.set", { effort })) as {
        effort?: string;
      };
      if (applied.effort !== undefined) {
        setReasoning((prev) => (prev ? { ...prev, effort: applied.effort! } : prev));
      }
    } catch (error: unknown) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
      }));
      await refreshReasoning();
    }
  }, [refreshReasoning]);

  /**
   * Read the model list, once.
   *
   * Called when the menu is first opened rather than at launch: OpenRouter
   * answers with several hundred ids, and a window that reads them on every
   * start spends a request to render a chip the user may never click.
   *
   * A failure is kept as a message rather than a console warning, because the
   * menu is the one place the user is looking when they wonder why the list is
   * not there.
   */
  const loadModelList = useCallback(async () => {
    const backend = backendRef.current;
    if (!backend) return;
    setModelListError(null);
    try {
      const listed = (await backend.call("models.list")) as {
        models?: string[];
        current?: string;
      };
      setModelList({ models: listed.models ?? [], current: listed.current ?? "" });
    } catch (error: unknown) {
      setModelList(null);
      setModelListError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  /**
   * Switch models, by re-binding the provider.
   *
   * Refused while a turn is in flight. The turn's history is being written by
   * one model and rebinding mid-turn interleaves another model's answers into
   * the same conversation -- so the guard is here rather than left to the user
   * to notice, and the menu explains it instead of being quietly inert.
   */
  const changeModel = useCallback(
    async (next: string) => {
      if (state.busy) return;
      if (next === model) return;
      if (!provider) {
        setModelListError("No provider is bound. Choose one in Settings first.");
        return;
      }
      // Cleared first, so the reasoning dropdown does not keep offering the old
      // model's efforts during the round trip. They belong to a model that is
      // no longer bound, and the request layer would refuse them.
      setReasoning(null);
      try {
        const bound = (await backendRef.current!.call("bind_provider", {
          name: provider,
          model: next,
          ...(baseUrl ? { base_url: baseUrl } : {}),
        })) as { model?: string };
        setModel(bound.model ?? next);
      } catch (error: unknown) {
        setModelListError(error instanceof Error ? error.message : String(error));
        // The chip still shows the old model, because `model` was never
        // changed -- so the window and the core agree. Reading the list again
        // is not needed; the failure was in the bind, not the list.
      }
    },
    [state.busy, model, provider, baseUrl],
  );

  /**
   * Re-read the per-turn tool call budget.
   *
   * From the core, not from a local copy: this number is what bounds a turn,
   * so a control that reported a value the core is not holding to would be
   * the one number in the window that lies.
   */
  const refreshToolBudget = useCallback(async (cancelled?: boolean) => {
    const backend = backendRef.current;
    if (!backend) return;
    try {
      const listed = (await backend.call("tools.get")) as { max_tool_calls?: number };
      if (cancelled) return;
      setMaxToolCalls(listed.max_tool_calls ?? null);
    } catch (error: unknown) {
      if (cancelled) return;
      // Same contract as the reasoning dial: an unread answer is a control
      // that says "reading", not an error the user has to clear.
      setMaxToolCalls(null);
      console.warn("Could not read the tool call budget:", error);
    }
  }, []);

  /**
   * Change the per-turn tool call budget.
   *
   * Painted straight away, then corrected by the reply. A rejected value
   * (zero, say) leaves the painted number on screen for a round trip, which
   * is the same brief lag the reasoning dropdown has; the re-read on failure
   * is what puts the truth back.
   */
  const changeToolBudget = useCallback(async (limit: number) => {
    setMaxToolCalls(limit);
    try {
      const applied = (await backendRef.current!.call("tools.set", {
        max_tool_calls: limit,
      })) as { max_tool_calls?: number };
      setMaxToolCalls(applied.max_tool_calls ?? limit);
    } catch (error: unknown) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
      }));
      await refreshToolBudget();
    }
  }, [refreshToolBudget]);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    void refreshToolBudget(cancelled);
    return () => {
      cancelled = true;
    };
  }, [connected, refreshToolBudget]);

  // Re-read whenever the model can have changed. One effect rather than a call
  // in three places, because the failure mode of forgetting the third is a
  // dropdown offering efforts the new model does not have.
  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    void refreshReasoning(cancelled);
    return () => {
      cancelled = true;
    };
  }, [connected, model, refreshReasoning]);

  /** Replace the transcript with a conversation's saved messages. */
  const showMessages = useCallback((raw: unknown[]) => {      const restored: ChatMessage[] = [];
      (raw ?? []).forEach((entry, index) => {
        const message = entry as {
          role?: string;
          content?: string | string[] | null;
          reasoning?: string | null;
        };
        if (!message.role) return;
        // Tool turns come back as assistant text rather than reconstructed tool
        // cards. Their results are already flattened into the transcript by the
        // core, and a tool call with no card behind it would render as an
        // orphaned heading for work that already happened.
        const role: Role = message.role === "user" ? "user" : "assistant";
        restored.push({
          ...blankMessage(`restored-${index}`, role),
          text: textFromContent(message.content),
          // A saved message is finished by definition. Without this it would
          // come back mid-stream and its panel would sit open forever, waiting
          // for a `reasoning.completed` that was sent hours ago.
          reasoning: message.reasoning ?? "",
          reasoningComplete: true,
        });
      });
    setState((prev) => ({
      ...prev,
      messages: restored,
      error: null,
      busy: false,
      // The transcript being replaced is the only one this window renders, so
      // any turn it was in the middle of is no longer its own. Leaving the id
      // set here would make the next turn's `turn.started` look like a
      // subagent's and be ignored -- a transcript that silently stops after a
      // conversation switch.
      activeTurnId: null,
    }));
  }, []);

  /**
   * Open a conversation, or start a new one.
   *
   * Both clear the view first. The core swaps the session underneath us, and
   * the window would otherwise keep showing the old transcript until the reply
   * arrives -- so a click that worked still looks broken while it works.
   */
  /**
   * The composer's textarea, so closing the sidebar can put the caret somewhere
   * deliberate. See `ConversationList` for why the sidebar closes at all.
   */
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  /**
   * Close the conversation panel and hand the caret to the composer.
   *
   * The panel is an overlay, so it covers the conversation the user just chose.
   * Leaving it up means the thing they switched to is half hidden by the list
   * of what they could switch to instead -- and on a narrow window that is the
   * whole transcript.
   *
   * **The focus move is not tidying, it is the other half of the change.** The
   * click landed on a row inside the panel, and the panel is about to leave the
   * document. Without this the focused element is deleted out from under the
   * caret and focus falls back to `<body>`, so the next Tab starts again from
   * the top of the window: a keyboard user switching conversations would walk
   * past the title bar, the rail and the whole panel every single time.
   *
   * The composer is the right destination rather than the transcript because it
   * is the thing one does *next* with a conversation -- the panel's job was to
   * get out of the way of reading and replying. `requestAnimationFrame` because
   * the panel does not leave synchronously (`useDelayedUnmount` holds it for the
   * exit), and focusing an element while something overlapping it is still on
   * its way out would scroll the departing panel back into view.
   */
  const closePanelToComposer = useCallback(() => {
    setRailExpanded(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, []);

  const openConversation = useCallback(
    async (id: string) => {
      setState((prev) => ({ ...prev, error: null, busy: true }));
      closePanelToComposer();
      // Selecting a chat is a switch away from the dashboard, which stays open
      // as a tab rather than disappearing -- and the same switch away from the
      // viewer, whose tab also stays open with its file.
      setUsageTab((open) => (open === "active" ? "open" : open));
      setMainMode("agent");
      try {
        const result = (await backendRef.current!.call("conversations.switch", {
          id,
        })) as {
          conversation?: ConversationSummary;
          messages?: unknown[];
        };
        showMessages(result.messages ?? []);
        const opened = result.conversation;
        if (opened) {
          setConversation(opened.id);
          // Opening a chat gives it a tab. Clicking one that is already open
          // activates the tab it has rather than adding a second -- two tabs on
          // one conversation are two views of one session, and the only thing
          // they could disagree about is which of them the user meant.
          setTabs((prev) => (prev.includes(opened.id) ? prev : [...prev, opened.id]));
        }
        await refreshConversations();
      } catch (error: unknown) {
        setState((prev) => ({
          ...prev,
          busy: false,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },
    [showMessages, refreshConversations, closePanelToComposer],
  );

  /**
   * Point the sandbox at a folder and record it as the current project.
   *
   * Split out of `chooseFolder` rather than called from it, because "New chat"
   * needs the same two steps -- bind the folder, then create under it -- and
   * they have to happen in that order. A conversation created before its folder
   * was bound would be filed under the *previous* project, and its tools would
   * act on a directory the user never picked.
   *
   * Returns the project it settled on, or "" if the folder did not take. The
   * caller has to know either way: a conversation filed under a project that
   * failed to open is a row the user cannot work in, and no row is the better
   * failure. Returning the path rather than a boolean is what lets a caller
   * that just changed the folder file the next chat under it without waiting
   * for a render to tell it what the state now says.
   */
  const attachProject = useCallback(async (path: string): Promise<string> => {
    setSettingsError(null);
    setSettingsNotice(null);
    try {
      const result = (await backendRef.current!.call("sandbox.start", {
        path,
      })) as { running: boolean; isolated?: boolean; project?: string };
      if (!result.running) {
        setSettingsError("The sandbox did not start. See the log below for the reason.");
        return "";
      }
      const settled = result.project ?? path;
      setProject(settled);
      // A new folder is a new tree, and whatever the viewer was showing came
      // from a folder that is no longer open -- the paths would resolve
      // against the new root and quietly name a different file. Put both
      // away; the tree is re-read by the effect below.
      setTreeEntries([]);
      setTreeTruncated(false);
      treeFolderRef.current = "";
      closeViewer();
      // A runtime is not the same as containment. Without Docker the tools
      // still work, but only the two that execute code are unavailable, and
      // saying so is more useful than a green tick that implies otherwise.
      if (result.isolated === false) {
        setSettingsNotice(
          "Working without an isolated sandbox: file, search, web and browser tools are available, but running commands and JavaScript needs Docker.",
        );
      }
      return settled;
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : String(error));
      return "";
    }
  }, [closeViewer]);

  /**
   * Start a conversation, filed under `project`.
   *
   * The project is sent rather than left to the core's current one, because the
   * whole point of the sidebar's grouping is that a conversation says which
   * project it belongs to -- and a chat that inherited whatever folder happened
   * to be open would be filed under a project the user never chose for it.
   */
  /** Ask the core for one window of usage. Null when it cannot answer. */
  const loadUsage = useCallback(
    (period: string): Promise<UsageSummary | null> =>
      backendRef
        .current!.call("usage.summary", { window: period })
        .then((reply) => reply as UsageSummary)
        .catch(() => null),
    [],
  );

  /**
   * Re-read the skill list for the `/` menu.
   *
   * Stable (`[]` deps) on purpose: the composer calls it from an effect keyed
   * on the menu opening, and a callback whose identity changed every render
   * would make that effect run on every render -- one RPC per keystroke.
   *
   * A failure leaves the list as it was rather than clearing it. The menu is a
   * convenience over a syntax that works without it, so a failed refresh must
   * not turn a working `/review` into "no skills yet"; the reason lands in the
   * banner, where every other failed call lands.
   */
  const loadSkills = useCallback(() => {
    void backendRef
      .current!.call("skills.list")
      .then((reply) => {
        const listed = reply as { skills?: SkillInfo[] };
        setSkills(listed.skills ?? []);
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
      });
  }, []);

  const createConversation = useCallback(
    async (project = "") => {
      // Any act that opens a conversation brings the transcript back, so a new
      // chat cannot be typed into a window that is showing a chart. The tab
      // stays open behind it, the way a tab you switched away from does.
      setUsageTab((open) => (open === "active" ? "open" : open));
      setMainMode("agent");
      setState((prev) => ({ ...prev, error: null, busy: true }));
      try {
        const result = (await backendRef.current!.call("conversations.create", {
          project,
        })) as {
          conversation?: ConversationSummary;
        };
        showMessages([]);
        const created = result.conversation;
        if (created) {
          setConversation(created.id);
          setTabs((prev) => (prev.includes(created.id) ? prev : [...prev, created.id]));
        }
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

  /**
   * What "New chat" does, which depends on whether a project is open.
   *
   * **With a project already chosen, it asks nothing.** The second chat in a
   * folder is the common case by far, and a dialog in front of it every time
   * would make the common path the slow one. Changing project is a deliberate
   * act -- the "+" beside the open project -- and is reachable from there.
   *
   * **With no project at all, it asks first**, because a chat with no project
   * is a chat whose tools have nothing to act on: every file path resolves
   * against "no project folder selected". Creating it and failing later, on the
   * first attempt to read a file, would be a worse answer than one question up
   * front.
   *
   * A cancelled picker creates nothing. Cancelling is a normal outcome, and an
   * empty untitled conversation left behind would make the button look like it
   * had worked.
   */
  const startNewChat = useCallback(async () => {
    // "New chat" leaves an empty transcript behind, which the panel would then
    // sit on top of -- the same problem as picking a conversation, and the same
    // fix. See `closePanelToComposer`.
    closePanelToComposer();

    // Read into a local rather than re-reading `project` after the await. The
    // state variable belongs to this render, and `attachProject` setting it does
    // not update the closure that is already running -- so a chat created after
    // a fresh pick would be filed under the empty string, which is precisely
    // the bug this flow exists to prevent. `attachProject` returns the project
    // it settled on for exactly this.
    let target = project;
    if (target === "") {
      const chosen = await pickRef.current();
      if (!chosen) return;
      target = await attachProject(chosen);
      if (!target) return;
    }
    await createConversation(target);
  }, [project, attachProject, closePanelToComposer, createConversation]);

  /**
   * Delete a conversation, and start a fresh one if it was the open one.
   *
   * **"Moved on to a fresh one" is not a courtesy.** With no conversation at all
   * the window is in a state the rest of the core does not support: `_persist`
   * returns early on an empty id, so a message typed into that empty state was
   * never saved anywhere -- and the tab went on naming the chat that had just
   * been deleted, because the title is read out of the list by the open id.
   *
   * The fresh conversation is created here rather than by the core, which is
   * where its own delete handler's comment says the moving-on happens. A
   * conversation invented in the core would be one the window has never heard
   * of -- there is no push for "you are now in a different conversation" -- so
   * the reply would have to carry it and every caller would have to adopt it.
   * `conversations.create` already exists, files under the folder this window
   * knows it is in, and answers here directly.
   *
   * Deleting a row you are *not* looking at is the other half: nothing moves, the
   * list is just re-read.
   */
  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await backendRef.current!.call("conversations.delete", { id });
        // Its tab goes either way: the conversation no longer exists, and a tab
        // on a deleted chat is a tab that cannot be opened.
        setTabs((prev) => prev.filter((tab) => tab !== id));
        if (id === conversation) {
          setConversation("");
          setState((prev) => ({
            ...prev,
            messages: [],
            error: null,
            activeTurnId: null,
          }));
          await createConversation(project);
        } else {
          await refreshConversations();
        }
      } catch (error: unknown) {
        setSettingsError(error instanceof Error ? error.message : String(error));
      }
    },
    [conversation, project, createConversation, refreshConversations],
  );

  /**
   * Close a tab.
   *
   * **Closing a tab is not deleting a chat.** The conversation stays in the
   * sidebar, which is where it has always been; what goes away is one of the
   * views of it. Deleting is the row menu's Delete, and it is a different word
   * on purpose.
   *
   * The window has to land somewhere. "Nowhere" is the state that lost messages
   * before -- `_persist` returns early with no conversation id -- so the tab that
   * takes the closed one's place is opened, or the one before it if it was the
   * last one, and a fresh chat starts if it was the only tab.
   */
  const closeTab = useCallback(
    async (id: string) => {
      const index = Math.max(0, tabs.indexOf(id));
      const rest = tabs.filter((tab) => tab !== id);
      setTabs(rest);
      if (id !== conversation) return;
      const next = rest[Math.min(index, rest.length - 1)];
      if (next) {
        await openConversation(next);
      } else {
        await createConversation(project);
      }
    },
    [tabs, conversation, project, openConversation, createConversation],
  );

  /**
   * Rename a conversation from the list.
   *
   * A rejected name comes back as an error and the row keeps whatever it had:
   * the core refuses a blank title, and showing the old one is better than
   * showing a name the user never asked for.
   */
  const renameConversation = useCallback(
    async (id: string, title: string) => {
      // Cleared up front, not only on failure. An error left standing from
      // something else would otherwise sit under a rename that worked, and
      // read as though the rename were what went wrong.
      setState((prev) => ({ ...prev, error: null }));
      try {
        await backendRef.current!.call("conversations.rename", { id, title });
        await refreshConversations();
      } catch (error: unknown) {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },
    [refreshConversations],
  );

  const duplicateConversation = useCallback(
    async (id: string) => {
      setState((prev) => ({ ...prev, error: null }));
      try {
        await backendRef.current!.call("conversations.duplicate", { id });
        await refreshConversations();
      } catch (error: unknown) {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },
    [refreshConversations],
  );

  /**
   * Point the sandbox at a folder the user picked, and bring the chat with you.
   *
   * The picker returns null on cancel, which is a normal outcome and must not
   * be reported as an error. Anything else the core rejects -- a path that
   * vanished, a backend that will not start -- surfaces verbatim.
   *
   * **The open conversation is moved into the new folder.** The window works in
   * one folder at a time and the sidebar lists that folder's chats, so a chat
   * left filed under the old one would vanish from the list the moment the
   * folder changed -- and a chat about a folder is exactly the thing you would
   * want to carry across when you change which folder you are working in. The
   * folder is bound first: `conversations.move` files the chat under a path the
   * caller names, and a pick that did not take must not move anything.
   *
   * A failed move is reported and does not undo the folder. The folder is where
   * the user asked to work; the chat is still readable where it was, and undoing
   * the one to repair the other would be a worse surprise than the error.
   */
  const chooseFolder = useCallback(async () => {
    const chosen = await pickRef.current();
    if (!chosen) return;
    const attached = await attachProject(chosen);
    if (attached === "") return;
    if (conversation) {
      try {
        await backendRef.current!.call("conversations.move", {
          id: conversation,
          project: attached,
        });
      } catch (error: unknown) {
        setSettingsError(error instanceof Error ? error.message : String(error));
      }
      await refreshConversations();
    }
    // The Files pane is the view of this folder, and opening the sidebar on it
    // is what makes the pick feel like it did something. Only here and not in
    // `attachProject`, because a chat that was asked for should not drag the
    // sidebar open over the transcript the user is about to type into.
    setSidebarPane("files");
    setRailExpanded(true);
  }, [attachProject, conversation, refreshConversations]);

  /**
   * Escape closes the sidebar.
   *
   * There is one overlay on the left now -- the sidebar -- so there is one
   * thing to put away, and it returns to the chats pane on the way out, so the
   * next open is not still showing a file tree from ten minutes ago.
   */
  useEffect(() => {
    if (!railExpanded) return;
    const onKey = (event: KeyboardEvent) => {
      // `defaultPrevented` is the other half: a menu inside the sidebar answers
      // Escape itself, and `useDismiss` claims the key in the capture phase, so
      // a press that closed a menu does not also close the sidebar behind it.
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setSidebarPane("chats");
      setRailExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [railExpanded]);

  /**
   * Start the sandbox on the folder already chosen.
   *
   * Sends no path. `sandbox.start` falls back to the folder the core already
   * has registered, which is the same folder this window is showing -- sending
   * it would only restate what the core knows, and would let the two disagree.
   */
  const startSandbox = useCallback(() => {
    setSettingsError(null);
    void attachProject("");
  }, [attachProject]);

  const stopSandbox = useCallback(() => {
    void backendRef.current!.call("sandbox.stop").catch((error: unknown) => {
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
   * Store one named API key in the OS keyring.
   *
   * Resolves to a boolean rather than throwing: the panel reports success or
   * failure inline, and the core's own error text is deliberately vague about
   * *why* it failed, because the keyring's message can quote the value.
   *
   * An empty name means the default slot; the core canonicalises anything else.
   */
  const saveKey = useCallback(
    async (saved: string, name: string, apiKey: string) => {
      try {
        await backendRef.current!.call("key.save", {
          provider: saved,
          api_key: apiKey,
          name,
        });
        // Re-read the provider list so anything that reports has_credentials
        // reflects the keyring without this component guessing.
        const listed = (await backendRef.current!.call("providers.list")) as {
          providers?: ProviderInfo[];
        };
        setProviders(listed.providers ?? []);
        // Rebind, so a freshly saved key takes effect immediately. This also
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

  /**
   * Read one stored key, for the panel's reveal control.
   *
   * Resolves to null rather than throwing, on the same reasoning saveKey
   * resolves to a boolean: the panel shows nothing either way, and an error
   * banner over "there is nothing stored" would be a lie about the state.
   *
   * The value goes straight back to the caller and never enters this
   * component's state, so no snapshot of the window holds a credential.
   */
  const revealKey = useCallback(
    async (target: string, name: string): Promise<string | null> => {
      try {
        const reply = (await backendRef.current!.call("key.reveal", {
          provider: target,
          name,
        })) as { api_key?: string | null };
        return reply.api_key ?? null;
      } catch {
        return null;
      }
    },
    [],
  );

  /**
   * Remove one named key.
   *
   * The name is passed through as given: this never means "the active one", so
   * a call that lost the name cannot delete a key the user did not point at.
   */
  const deleteKey = useCallback(async (target: string, name: string) => {
    try {
      await backendRef.current!.call("key.delete", { provider: target, name });
      const listed = (await backendRef.current!.call("providers.list")) as {
        providers?: ProviderInfo[];
      };
      setProviders(listed.providers ?? []);
      return true;
    } catch {
      return false;
    }
  }, []);

  /**
   * The stored keys, as the core's registry reports them.
   *
   * Resolves to an empty list rather than throwing: the panel draws an "add a
   * key" row either way, and an error banner over "you have none yet" would be
   * a lie about the state.
   */
  const listKeys = useCallback(async (target?: string): Promise<KeyEntry[]> => {
    try {
      const reply = (await backendRef.current!.call(
        "key.list",
        target ? { provider: target } : {},
      )) as KeyEntry[];
      // Array.isArray, not a null check: a core that does not answer at all
      // still resolves something (the tests' fake returns a marker object), and
      // handing that to the panel's rows would throw inside render.
      return Array.isArray(reply) ? reply : [];
    } catch {
      return [];
    }
  }, []);

  /**
   * Make one stored key the one a turn spends.
   *
   * A successful activation also re-binds the provider, because the HTTP client
   * caches the credential it was built with -- without this the press would
   * change the config and leave the next request using the old key.
   */
  const activateKey = useCallback(
    async (target: string, name: string) => {
      try {
        await backendRef.current!.call("key.activate", { provider: target, name });
        if (provider === target) await applyBinding(target, model, baseUrl);
        return true;
      } catch {
        return false;
      }
    },
    [provider, model, baseUrl, applyBinding],
  );

  /**
   * Bind the Base URL to the provider already in use.
   *
   * The panel no longer picks a provider or a model, so neither is an argument:
   * the window's own selection is sent, which is the only one it can mean.
   */
  const applyEndpoint = useCallback(
    (endpoint: string) => {
      setSettingsError(null);
      void applyBinding(provider, model, endpoint).catch((error: unknown) => {
        setSettingsError(error instanceof Error ? error.message : String(error));
      });
    },
    [provider, model, applyBinding],
  );

  const search = useCallback(async (pattern: string): Promise<SearchMatch[]> => {
    const result = (await backendRef.current!.call("search", { pattern })) as {
      matches?: SearchMatch[];
    };
    return result.matches ?? [];
  }, []);

  const changePermission = useCallback((name: string) => {
    // Painted straight away, for the reason `changeReasoning` paints: the bar is
    // a control the user is about to act on, and a bar that lags a round trip
    // reads as not having registered the press. The reply then corrects it to
    // whatever the core resolved, which is the same contract the others have.
    setPermission(name);
    void backendRef.current!
      .call("permission.set", { permission: name })
      .then((result) => {
        const applied = result as { permission?: string };
        if (applied.permission && applied.permission !== name) {
          setPermission(applied.permission);
        }
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
        // Back to what the core is actually enforcing, rather than leaving the
        // bar showing a level that was refused -- which would be the one place
        // a user looks to find out what the agent is allowed to do.
        void backendRef.current!
          .call("permission.list")
          .then((list) => {
            const current = (list as PermissionList).permission;
            if (current) setPermission(current);
          })
          .catch(() => {
            /* The banner already says the switch failed. */
          });
      });
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
        // The turn id goes with the transcript for the same reason as in
        // `showMessages`: the next turn belongs to the new, empty one.
        setState((prev) => ({
          ...prev,
          messages: [],
          error: null,
          activeTurnId: null,
        }));
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

  const respondAsk = useCallback((id: string, answer: string) => {
    // Cleared locally first, for the same reason as the confirmation above:
    // the core settles the ask with `user.resolved`, and waiting on that would
    // leave the dialog up -- over the turn it is meant to be unblocking -- for
    // the length of the round trip.
    //
    // The answer is trimmed by the dialog, and may be empty: an empty answer is
    // "no comment", which is a real answer the core can act on. It is not a
    // cancellation, and the reply's `answered` flag says whether it still found
    // anything to answer.
    setState((prev) => ({ ...prev, pendingAsk: null }));
    void backendRef.current!.call("user.respond", { id, answer }).catch((error: unknown) => {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
      }));
    });
  }, []);

  /**
   * Code mode is a different *window*, not a different pane.
   *
   * Agent mode is a conversation with a rail beside it; Code mode is a project
   * with an explorer beside it. So this decides what the shell renders -- the
   * rail, the conversation overlay and the chat tab strip are all absent from
   * it -- and the grid it lays out is `--code-side-w` of explorer plus the
   * editor. See `.app[data-mode="code"]`.
   */
  const codeMode = mainMode === "code";

  return (
    <div className="app" data-mode={mainMode}>
      {/*
        The title bar spans the window, not the transcript column.

        It has to: the caption buttons have to sit at the right *edge of the
        window*, and a bar confined to column 2 would put them 425px from that
        edge the moment the Files panel opened -- which is where the panel's own
        header is. It also means the whole top edge is a drag handle, rather than
        the part of it that happens to be over the transcript.

        Placed first, and pinned to row 1 in CSS along with everything else, so
        no sibling's absence can move it into a different row.
      */}
      <TopBar
        busy={state.busy}
        // The strip is the conversation's, and Code mode has no conversation in
        // front. The bar keeps the mark, the drag region, the switch and the
        // caption -- which is what "the whole screen changes" means at the top
        // edge of the window as well as the middle.
        tabs={codeMode ? [] : tabStrip}
        active={codeMode ? "" : usageTab === "active" ? USAGE_TAB : conversation}
        mode={mainMode}
        canCode={project !== ""}
        onModeChange={(next) => {
          setMainMode(next);
        }}
        onSelect={(id) => {
          if (id === USAGE_TAB) {
            setUsageTab("active");
            setMainMode("agent");
            return;
          }
          // Choosing a chat is a switch away from the dashboard, which stays
          // open behind it -- the same thing selecting another chat tab does.
          setUsageTab((open) => (open === "active" ? "open" : open));
          // ...and back to the conversation, because a chat tab is the agent.
          setMainMode("agent");
          void openConversation(id);
        }}
        onClose={(id) => {
          if (id === USAGE_TAB) {
            setUsageTab("closed");
            return;
          }
          void closeTab(id);
        }}
        // The "+" is part of the strip, so it goes with the strip. It used to
        // stay, and Code mode drew a lone "+" beside the app's mark with
        // nothing to be a "+" *of* -- a button that starts a chat in a window
        // whose whole point is that it is not showing chats. Starting one is a
        // click on Agent away, which is the same door the tabs use.
        onNewTab={codeMode ? undefined : () => void startNewChat()}
        onRename={(id, title) => void renameConversation(id, title)}
        controls={windowControls}
        // Built here and placed by the bar, so `TopBar` stays presentational
        // and knows nothing about models -- see its `modelSelector` prop. The
        // picker is the *conversation's* setting, so it goes with the tab strip.
        modelSelector={
          codeMode ? undefined : (
            <ModelPicker
              model={model}
              busy={state.busy}
              disabled={!connected}
              list={modelList}
              error={modelListError}
              onOpen={() => {}}
              onClose={() => {}}
              onChange={(next) => void changeModel(next)}
              onLoad={() => void loadModelList()}
            />
          )
        }
      />

      {/*
        Agent mode's left edge: the rail, and the conversation panel it opens.

        Neither is rendered in Code mode. The rail is a column of chat actions
        and the panel is a list of conversations: beside a file tree they are a
        second sidebar, and floating over an editor they are a panel with
        nothing to say. Code mode replaces this whole column with the explorer
        below -- which is the difference between "a pane changed" and "the
        window changed".
      */}
      {!codeMode && (
        <IconRail
          connected={connected}
          busy={state.busy}
          messageCount={state.messages.length}
          expanded={railExpanded}
          onToggle={() => setRailExpanded((open) => !open)}
          onCancel={cancel}
          dashboardOpen={usageTab === "active"}
          onDashboard={() =>
            setUsageTab((open) => (open === "active" ? "open" : "active"))
          }
          petOpen={petOpen}
          onPet={() => void togglePet()}
          onSettings={() => {
            setSettingsError(null);
            openSidebarPane("settings");
          }}
          onSearch={() => openSidebarPane("search")}
        />
      )}

      {/*
        The conversation panel, floating over the transcript beside the rail.

        `conversationsMounted &&` rather than `railExpanded &&`, and `data-state`
        rather than a mount/unmount pair: the node has to still be here on its
        way out for `slide-out-left` to have anything to play. `data-state` is
        what tells the two apart, and the closed state is inert -- see
        `.chatlist[data-state="closed"]`.
      */}
      {!codeMode && conversationsMounted && (
        <ConversationList
          open={railExpanded}
          conversations={conversations}
          active={conversation}
          project={project}
          busy={state.busy}
          connected={connected}
          onDismiss={() => setRailExpanded(false)}
          onNew={() => void startNewChat()}
          onChooseProject={chooseFolder}
          onOpen={(id) => void openConversation(id)}
          onDelete={(id) => void deleteConversation(id)}
          onRename={(id, title) => void renameConversation(id, title)}
          onDuplicate={(id) => void duplicateConversation(id)}
          // The sidebar's second pane, and the state that switches to it. The
          // App owns `pane` because choosing a folder has to be able to bring
          // the Files pane forward -- see `chooseFolder`.
          pane={sidebarPane}
          onPaneChange={setSidebarPane}
          files={treeEntries}
          fileChanges={fileChanges}
          fileFilter={fileFilter}
          onFileFilterChange={setFileFilter}
          onChooseFolder={() => void chooseFolder()}
          onOpenFile={(path) => void openFile(path)}
          treeTruncated={treeTruncated}
          treeLoading={treeLoading}
          hasProject={project !== ""}
          // The other two panes. Built here rather than by the sidebar, because
          // the App owns every handler they need -- and passed as elements so
          // `ConversationList` stays a container and never imports them.
          settingsPane={
            <SettingsPanel
              connected={connected}
              busy={state.busy}
              providers={providers}
              provider={provider}
              baseUrl={baseUrl}
              project={project}
              sandbox={sandbox}
              trusted={trustedProjects.has(project)}
              permissionList={permissionList}
              permission={permission}
              reasoning={reasoning}
              error={settingsError}
              notice={settingsNotice}
              // The same state and the same handler the rail's pet button is
              // given. Two ways to reach one action, and neither is allowed its
              // own idea of whether the card is up -- see `togglePet`.
              petOpen={petOpen}
              onPet={() => void togglePet()}
              // "Close" means back to the conversations now. The panel is a pane
              // of the sidebar rather than a dialog over the window, so there is
              // nothing to close -- there is somewhere to go back to.
              onClose={() => setSidebarPane("chats")}
              onChooseFolder={chooseFolder}
              onStartSandbox={startSandbox}
              onStopSandbox={stopSandbox}
              onPermissionChange={changePermission}
              onReasoningChange={(effort) => void changeReasoning(effort)}
              onApplyEndpoint={applyEndpoint}
              onTrust={setTrust}
              onSaveKey={saveKey}
              onDeleteKey={deleteKey}
              onRevealKey={revealKey}
              onActivateKey={activateKey}
              onListKeys={listKeys}
            />
          }
          searchPane={
            <SearchPanel
              connected={connected}
              hasProject={project !== ""}
              onSearch={search}
            />
          }
          // The rail's actions, because the sidebar covers the rail when open
          // (see ConversationList). Same handlers the rail is given, so the two
          // states of the one sidebar cannot disagree about what a button does.
          onSearch={() => openSidebarPane("search")}
          onSettings={() => {
            setSettingsError(null);
            openSidebarPane("settings");
          }}
        />
      )}

      {/*
        Code mode's left column: the current project, as a tree.

        The same `FilesPane` the sidebar shows, in a column of its own rather
        than in an overlay -- which is the whole difference the mode makes. It
        is fed by the same tree state, so the two places a file can be opened
        from cannot disagree about what the project contains.
      */}
      {codeMode && (
        <aside className="code-explorer" aria-label="Project files">
          {/*
            Two rows, and each one is a row.

            It was one: the section title and the path side by side on a shared
            baseline inside a fixed 34px band, which drew both of them against
            the band's *top* edge -- `align-items: baseline` positions a line by
            its baseline, and a baseline-anchored line in a taller box sits
            high. So the header read as text that had slipped upward, with the
            path crammed against the title.

            VSCode's explorer answers the same two questions in the same two
            rows: what is this list (a section title), and which folder is it
            (the folder row, with the name carrying the emphasis). Splitting
            them also gives the path the whole width to be long in.
          */}
          <div className="code-explorer-head">
            <span className="code-explorer-title">Explorer</span>
            {project === "" ? (
              <span className="code-explorer-project code-explorer-none">
                no folder
              </span>
            ) : (
              <span className="code-explorer-project" title={project}>
                <svg
                  className="code-explorer-folder"
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                </svg>
                {/*
                  The path is one run of text, in one child, for two reasons.

                  It has to be: the two spans put back together *are* the path
                  `title` promises -- the test reads this element's text as the
                  folder it names -- so there is no whitespace between them
                  (JSX drops whitespace containing a newline, which is what
                  makes that true rather than accidental).

                  And it is one element so the row's `gap` does not fall
                  between the directory and the name: `C:/work/ tonyagent` is
                  not a path anybody has. The gap belongs between the folder
                  glyph and the path, which is where it is now.
                */}
                <span className="code-explorer-path">
                  <span className="code-explorer-dir">{splitFolder(project)[0]}</span>
                  <span className="code-explorer-name">{splitFolder(project)[1]}</span>
                </span>
              </span>
            )}
          </div>
          <FilesPane
            entries={treeEntries}
            changes={fileChanges}
            filter={fileFilter}
            onFilterChange={setFileFilter}
            onChooseFolder={() => void chooseFolder()}
            onOpenFile={(path) => void openFile(path)}
            truncated={treeTruncated}
            loading={treeLoading}
            hasProject={project !== ""}
          />
        </aside>
      )}

      <div className="main">
        {/*
          Three faces of one column, in precedence order: the file the user
          opened, then the usage dashboard, then the conversation.

          Which mode the *window* is in decides the first -- `codeMode`, not
          `mode`, and the distinction is the whole bug this replaces: `mode` is
          the **core's** agent mode (`build`, `plan`, `mission`, `skills`), a
          different question with its own picker, and no core mode is called
          `code`. Gating the viewer on it meant the pane could never render: the
          file was read, the state was set, and the frame went on drawing the
          conversation, so a click in the tree looked like it did nothing.

          The Usage tab replaces the transcript and the composer together.

          The composer goes with the transcript because a text field under a
          chart would offer a message for a conversation that is not on screen.
          Choosing any chat brings both back and leaves this tab open behind it,
          which is what selecting another tab does everywhere else in this
          window -- see `openConversation`, `createConversation` and `TopBar`.
        */}
        {codeMode ? (
          /*
            The code half: the viewer, and nothing else. The composer goes with
            the transcript for the same reason the dashboard takes it -- a text
            field under a file would offer a message for a conversation that is
            not on screen -- and the tree is the explorer column beside this
            pane, the same `FilesPane` the sidebar shows.

            With no file open this is a signpost rather than a blank pane: the
            project is there, the tree is one click away, and an empty surface
            that explains nothing is the dead end this replaces.
          */
          viewerPath === "" ? (
            <div className="code-empty">
              <p>
                {project === ""
                  ? "Choose a project folder to browse its files."
                  : "Pick a file from the explorer to read it here."}
              </p>
              {/*
                No "open the tree" button any more: the tree *is* the column
                beside this pane, so a button that revealed it would be a
                control for something already on screen. What is left is the
                one thing the mode cannot do on its own -- choose a folder.
              */}
              {project === "" && (
                <button type="button" className="btn" onClick={() => void chooseFolder()}>
                  Choose folder...
                </button>
              )}
            </div>
          ) : (
            <CodeViewer
              path={viewerPath}
              file={viewerFile}
              loading={viewerLoading}
              error={viewerError}
              readOnly={readOnly}
              locked={state.busy}
              onToggleReadOnly={(next) => setReadOnly(next)}
              saving={viewerSaving}
              onSave={(content) => void saveFile(content)}
              onDirtyChange={(dirty) => {
                viewerDirtyRef.current = dirty;
              }}
              onDiscard={discardFile}
              palette={palette}
              onPalette={setPalette}
              onClose={closeViewer}
            />
          )
        ) : usageTab === "active" ? (
          <Dashboard
            connected={connected}
            onClose={() => setUsageTab("open")}
            load={loadUsage}
          />
        ) : (
          <>
            <MessageList
              messages={state.messages}
              busy={state.busy}
              project={project}
              onChooseFolder={() => void chooseFolder()}
              canChooseFolder={connected && !state.busy}
            />

            {state.error && <div className="banner">{state.error}</div>}

            {/*
              The composer, and nothing else. The permission ladder used to sit
              above it as its own bar, with the Thinking dial as a native select
              in the control row; both are in the settings panel now, where a
              user goes to ask what this window may do rather than scrolling
              past a strip to find out. See `SettingsMenus`.
            */}
            <Composer
              inputRef={composerRef}
              busy={state.busy}
              disabled={!connected}
              modes={modes}
              mode={mode}
              skills={skills}              onSkillsNeeded={loadSkills}
              onModeChange={changeMode}
              onSend={send}
              onCancel={cancel}
              maxToolCalls={maxToolCalls}
              budgetOpen={budgetOpen}
              onBudgetOpen={() => setBudgetOpen(true)}
              onBudgetClose={() => setBudgetOpen(false)}
              onBudgetChange={(limit) => void changeToolBudget(limit)}
            />
          </>
        )}

        {shownConfirm && (
          <Overlay open={state.pendingConfirm !== null}>
            <ConfirmDialog request={shownConfirm} onRespond={respond} />
          </Overlay>
        )}

        {shownAsk && (
          <Overlay open={state.pendingAsk !== null}>
            <QuestionDialog request={shownAsk} onRespond={respondAsk} />
          </Overlay>
        )}

        {logsMounted && (
          <div className="logstrip" data-state={logsOpen ? "open" : "closed"}>
            {logLines.length === 0 ? (
              <div className="logstrip-empty">No log output yet.</div>
            ) : (
              logLines.map((line, i) => <div key={i}>{line}</div>)
            )}
          </div>
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
            openSidebarPane("settings");
          }}
          logLines={logLines}
          logsOpen={logsOpen}
          onToggleLogs={() => setLogsOpen((open) => !open)}
        />
      </div>
    </div>
  );
}
