import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TrajectoryView, captureEvent, type CapturedEvent } from "./TrajectoryView.js";
import {
  CoreBackend,
  type ContextReply,
  type Plan,
  type PlanItem,
  type PlanReply,
} from "./backend.js";
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
import { ContextPanel } from "./ContextPanel.js";
import { isPlanWriter, lastPlanCall, turnActivity } from "./activity.js";
import {
  ConversationList,
  type ConversationSummary,
  type SidebarPane,
} from "./ConversationList.js";
import { pickFolder } from "./dialog.js";
import { host } from "./bridge.js";
import { CodeViewer, type ViewerFile } from "./CodeViewer.js";
import { diffLines, type LineRange } from "./diff.js";
import { FilesPane } from "./FileSidebar.js";
import { changesFrom, type CoreTreeEntry } from "./filetree.js";
import { DEFAULT_PALETTE } from "./highlight.js";
import { IconRail } from "./IconRail.js";
import { Launchpad } from "./Launchpad.js";
import { StatusPill } from "./StatusPill.js";
import { ViewSwitch } from "./ViewSwitch.js";
import { Dashboard, type UsageSummary } from "./Dashboard.js";
import { petDraw, petSet, petState } from "./pet.js";
import { petStatus } from "./pet-status.js";
import { MessageList } from "./MessageList.js";
import {
  applyMotionPreference,
  readMotionPreference,
  type MotionPreference,
} from "./motion.js";
import {
  summaryLine,
  textFromContent,
  toWire,
  type PendingAttachment,
} from "./attachments.js";
import { ModelPicker, type ModelDetails, type ModelList } from "./ModelPicker.js";
import { Overlay } from "./Overlay.js";
import { QuestionDialog } from "./QuestionDialog.js";
import { SearchPanel, type SearchMatch } from "./SearchPanel.js";
import type { PermissionList, ReasoningInfo } from "./SettingsMenus.js";
import type { SkillInfo } from "./SkillPicker.js";
import { SettingsPanel, type CoreSettings, type DiagnosticsInfo, type KeyEntry, type ProviderInfo, type SettingsTab, type UpdateAnswer, type UpdateDownload } from "./SettingsPanel.js";
import { StatusBar } from "./StatusBar.js";
import { TopBar, type Tab } from "./TopBar.js";
import { useDelayedUnmount, useLastValue } from "./useDelayedUnmount.js";
import { useMediaQuery } from "./useMediaQuery.js";
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
type MainMode = "agent" | "code" | "trajectory" | "settings";

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

const HELPER_GLYPH: Record<"open" | "closed", string> = {
  open: "M3 4h18v16H3zM15 4v16",
  closed: "M3 4h18v16H3zM19 4v16",
};

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
   * not open over the user's first message every launch. Sending while this
   * holds opens Settings on the Keys tab instead of answering the message
   * with a banner: switching tracks needs no key, so the toggle stays
   * silent, and sending is the act that asks where the key goes.
   */
  const [needsProvider, setNeedsProvider] = useState(false);
  /**
   * The settings tab a programmatic open lands on, or null for the default.
   *
   * Null except while opening: the panel remounts on every open, so this is
   * read once as the initial tab and every plain open resets it. A stale
   * value would land the gear button on Keys because send went there once.
   */
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
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
  /**
   * Catalog facts by model id, for the picker's detail lines.
   *
   * Read beside the list from the same cached entries, so it costs no extra
   * request. Null when unread or unreadable -- rows then render id-only, which
   * is what they did before the catalog existed.
   */
  const [modelDetails, setModelDetails] = useState<Record<
    string,
    ModelDetails
  > | null>(null);
  /**
   * What the last update check found, and the installer once it is verified.
   *
   * Three pieces of state rather than one, because they fail independently: the
   * *check* can fail to reach GitHub, the *download* can fail its digest, and
   * the *install* can be refused because this is a source checkout. Collapsing
   * them would report one failure's reason for another's.
   */
  const [update, setUpdate] = useState<UpdateAnswer | null>(null);
  /**
   * The check is in flight.
   *
   * Split from the fetch below rather than one "busy" flag: the fetch now starts
   * on its own the moment a check finds something, so a single flag would put
   * "Checking…" on a button that is not being pressed while 30 MB arrives in the
   * background. Two questions, two flags -- and the panel says which one it is
   * waiting on.
   */
  const [updateChecking, setUpdateChecking] = useState(false);
  /** The installer is being fetched and verified. */
  const [updateFetching, setUpdateFetching] = useState(false);
  const [updateReady, setUpdateReady] = useState<UpdateDownload | null>(null);
  /**
   * A fetch is in flight, and this version's installer is already on disk.
   *
   * Refs rather than state because both are read inside the callbacks that
   * decide whether to start a fetch, and neither should cause a render or
   * re-create a callback: they are bookkeeping about work already underway, not
   * anything the window draws.
   */
  const updateFetchingRef = useRef(false);
  const updateReadyVersionRef = useRef("");
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
   * Which track the open conversation belongs to: "chat" or "build".
   *
   * Decides which pills the composer draws -- Chat alone, or the four working
   * modes. Read from the conversation's summary (create/switch/list), never
   * guessed from the mode: the mode is per turn and the track is per
   * conversation, and the two only agree right after a switch.
   */
  const [track, setTrack] = useState("build");
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
   * Whether the core has actually answered `skills.list`.
   *
   * Separate from `skills.length`, because an empty list and an unread list are
   * different facts and the nav draws them differently: a count of `0` for a
   * core that has not been asked yet would make a working install look empty.
   */
  const [skillsKnown, setSkillsKnown] = useState(false);
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
   * **Open by default on a window that can dock it, and that is the inverse of
   * the rule this started with.** The old default was closed because the panel
   * was an overlay: 255px of an empty list sat over the transcript to report
   * that there was nothing to report. At 1101 and above it is a *track* now --
   * the centre keeps its 765px at the narrowest dock and its 824 at 1400 -- and
   * it holds the workspace switch, New chat and the project. A front door that
   * is shut on every first launch is a window whose navigation has to be found
   * before it can be used.
   *
   * Below 1101 the answer is still closed: the panel would be an overlay over a
   * transcript that has no column to spare. A stored preference wins at every
   * width, because a chrome preference that resets on every launch reads as
   * broken -- but only once the user has actually said something.
   */
  const [railExpanded, setRailExpanded] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("tonyagent.rail-expanded");
      if (stored !== null) return stored === "1";
    } catch {
      // Private mode or storage disabled: fall through to the width's answer.
    }
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(min-width: 1101px)").matches
      : false;
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

  /**
   * The context pane's expanded state.
   *
   * Not persisted, unlike the nav: the nav is where the user works and a
   * preference for it is stable, while the run panel is opened to answer a
   * question about one turn and should not reappear over the next launch's
   * empty conversation.
   */
  const [contextOpen, setContextOpen] = useState(false);

  /**
   * The core's plan for the open conversation, and how full its context is.
   *
   * Both are read on demand rather than folded into `state` (see `plan.get`),
   * and both keep their last value when a read fails: the panel is describing
   * the turn, and an error banner over a plan is louder than the fact it
   * reports. The empty shape is a plan with nothing in it, which is exactly
   * what the card's own empty state says.
   */
  const [plan, setPlan] = useState<Plan>({
    todos: [],
    goal: "",
    goal_status: "",
    goal_note: "",
  });
  const [contextMeter, setContextMeter] = useState<ContextReply>({
    model: "",
    used: 0,
    known: false,
    window: 0,
  });

  /**
   * Text a suggestion or the Skills row asked the composer to hold.
   *
   * The nonce is the request: two presses of the same suggestion produce the
   * same sentence, so the sentence alone cannot say "again". Cleared by the
   * composer once it has been applied, so a remount does not replay it.
   */
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);

  /**
   * The two dock widths, as questions React asks instead of rules CSS writes.
   *
   * Below 1101 an open nav is an overlay and the rail must stay mounted under
   * it; below 1400 an open context pane is an overlay and the column must stay
   * 48px. Both are answers about what to *mount*, not merely where to paint, so
   * they cannot be media queries alone.
   *
   * 1101 and 1400 rather than 1100 and 1400: the dock is the state at exactly
   * the first width that can hold the 760px column beside it. See the ladder
   * in tokens.css.
   */
  const wideNav = useMediaQuery("(min-width: 1101px)");
  const wideContext = useMediaQuery("(min-width: 1400px)");

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
  /**
   * The last three files this window opened in Code, newest first.
   *
   * The nav's project block offers them back, which is the shortest path from
   * "I was reading that" to reading it again. Window state rather than
   * persisted: it is a reading history, not a project setting, and a list that
   * survived a restart would be a list of files from last week that no longer
   * exist. Three, because the block has room for three -- see `RecentFiles`.
   */
  const [recentFiles, setRecentFiles] = useState<string[]>([]);
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
  /**
   * The raw event log for the trajectory view: every frame the core pushed,
   * unfolded and timestamped, newest last, capped so a long session cannot grow
   * without bound. Deliberately separate from `state`, which is the *reduced*
   * transcript -- this is the complete traffic, not a summary of it.
   */
  const [trajectory, setTrajectory] = useState<CapturedEvent[]>([]);
  const trajSeq = useRef(0);
  /**
   * Whether Code mode's assistant panel is showing.
   *
   * Its own state rather than something derived from `mainMode`: a user who put
   * the panel away and goes back to the conversation and returns must find the
   * window as they left it, not a panel that reappeared because the mode which
   * owns it was re-entered. It is deliberately *not* persisted the way the code
   * palette is -- it is one click to restore, and a panel that came back in the
   * state it was left in last week is a preference nobody remembers setting.
   */
  const [helperOpen, setHelperOpen] = useState(true);
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
   * The motion override, from the App tab's Motion menu.
   *
   * `system` follows the OS; `full` keeps the animations even under an OS
   * reduce preference, `reduced` drops them even without one. Applied to the
   * root as `data-motion` (removed for `system`), which is what both override
   * blocks in `reduced-motion.css` key off -- see `motion.ts`.
   */
  const [motion, setMotion] = useState<MotionPreference>(() => readMotionPreference());
  useEffect(() => {
    applyMotionPreference(motion);
  }, [motion]);

  /**
   * Bring one of the sidebar's panes forward.
   *
   * Two state changes that have to happen together: the pane, and the sidebar
   * that shows it. Search used to open as an overlay and needed only the first;
   * as a pane it needs both, and a caller that set the pane alone would be
   * pointing at a panel nobody can see.
   */
  const openSidebarPane = useCallback((pane: SidebarPane) => {
    setSidebarPane(pane);
    setRailExpanded(true);
  }, []);

  /**
   * Show the settings page.
   *
   * A mode rather than a pane -- see `settingsMode` -- so this is the window
   * changing rather than the sidebar. The stale error and notice go with it:
   * they belong to the last visit's actions, and a warning about a sandbox that
   * failed to start three days ago is not news for a page being opened now.
   *
   * `tab` lands the page on one tab for callers that know where the user
   * needs to be -- sending with no provider opens Keys. Null is the default,
   * and every call without one resets it, so one directed open does not
   * redirect every later one.
   *
   * Always wrapped at `onClick` call sites (`() => openSettings()`): passed
   * bare, React hands the click event in as `tab` and the page opens on no
   * tab at all.
   */
  const openSettings = useCallback((tab?: SettingsTab) => {
    setSettingsError(null);
    setSettingsNotice(null);
    setSettingsTab(tab ?? null);
    setMainMode("settings");
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
      trajSeq.current += 1;
      setTrajectory((prev) => [...prev, captureEvent(event, trajSeq.current, Date.now())].slice(-3000));
      if (event.type === "turn.finished" || event.type === "turn.failed") {
        void refreshConversationsRef.current();
      }
      // The plan has no change event of its own. A plan writer finishing is the
      // only moment it can differ from the card on screen, so that is when the
      // window re-reads it -- once per write, not once per tool call.
      if (
        (event.type === "tool.completed" || event.type === "tool.failed") &&
        typeof event.payload.name === "string" &&
        isPlanWriter(event.payload.name)
      ) {
        void refreshPlanRef.current();
      }
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

  /**
   * Re-read the providers the core will currently accept.
   *
   * The list depends on the mode in force, so it is read again whenever the
   * mode changes rather than kept from the last time it happened to be
   * fetched. A stale list would offer a provider the core refuses -- a
   * local chat model outside Chat mode -- and the failure would land on the
   * next press rather than on the click that caused it.
   */
  const refreshProviders = useCallback(async () => {
    try {
      const listed = (await backendRef.current!.call("providers.list")) as {
        providers?: ProviderInfo[];
      };
      setProviders(listed.providers ?? []);
    } catch {
      /* The panel draws what it has; the core is the authority. */
    }
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
        const rows = await refreshConversations();
        // The core adopted the reopened conversation's track while loading it,
        // so the pills follow the row rather than assuming Build: a reload
        // into a chat-track conversation showing four working pills would
        // offer modes its transcript was never written under.
        const open = rows.find((row) => row.id === snapshot.conversation);
        setTrack(open?.track === "chat" ? "chat" : "build");
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
        // The skills, for the nav's count. Read once at boot rather than when
        // the block is first drawn: the count is part of the front door, and a
        // number that arrived a second after the panel did would be a number
        // that was absent in the frame the user looked at. Failure is silent --
        // the list is a convenience, and the composer's `/` menu is where a
        // skill is actually chosen.
        if (!cancelled) {
          try {
            const listedSkills = (await backend.call("skills.list")) as {
              skills?: SkillInfo[];
            };
            if (!cancelled) {
              setSkills(listedSkills.skills ?? []);
              setSkillsKnown(true);
            }
          } catch {
            /* a core that cannot list skills still has a working composer */
          }
        }
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
    if (needsProvider) {
      // Nowhere to send to. The Keys tab rather than a banner: the message
      // was never attempted, so there is no failure to report -- only the
      // missing key, and the place that fixes it. Checked before the
      // optimistic append below, so refusing keeps no bubble behind.
      openSettings("keys");
      return;
    }
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
        // A send that never reached the core has no turn to time.
        turnStartedAt: null,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, [pendingEdits, needsProvider, openSettings]);

  const cancel = useCallback(() => {
    void backendRef.current!.call("cancel").catch(() => {
      /* The turn may already have ended; nothing to report. */
    });
  }, []);

  /**
   * The nav toggle, and the one-overlay rule.
   *
   * Below 1101 the expanded nav is an overlay and so is the context pane, so
   * two open panes would stack two scrims over one centre and dim it twice. At
   * 1101 and above the nav is docked, so the context may open beside it; at
   * 1400 and above both are docked and neither can close the other.
   */
  const toggleNav = useCallback(() => {
    if (!railExpanded && !wideNav && !wideContext) setContextOpen(false);
    setRailExpanded(!railExpanded);
  }, [railExpanded, wideNav, wideContext]);

  const toggleContext = useCallback(() => {
    if (!contextOpen && !wideNav && !wideContext) setRailExpanded(false);
    setContextOpen(!contextOpen);
  }, [contextOpen, wideNav, wideContext]);

  /**
   * The usage dashboard, from either form of the nav.
   *
   * **It lands in Agent**, because the dashboard is one of Agent's faces: the
   * centre's precedence puts settings above trajectory above the dashboard, so
   * a chart toggled from Trajectory would be switched on behind a page that is
   * still in front. The rail is rendered in Trajectory now, which is what makes
   * this reachable rather than theoretical.
   *
   * An overlay nav closes on the way there -- the chart is the thing to look at,
   * not the list that opened it -- while a docked nav stays, because a dock is a
   * column of the workspace and closing it is not this action's business.
   */
  const openUsage = useCallback(() => {
    setMainMode("agent");
    setUsageTab((open) => (open === "active" ? "open" : "active"));
    if (!wideNav) setRailExpanded(false);
  }, [wideNav]);

  /*
   * The one-overlay rule also has to survive a resize.
   *
   * The toggles above cover a user opening the second pane, but a window dragged
   * from 1400 to 1000 makes both open panes overlays at once -- two scrims over
   * one centre, dimmed twice, and the panel edges ambiguous. The nav is the
   * primary workspace surface and the one the user was in first, so the context
   * pane gives way; it can be reopened from its strip, which is still there.
   */
  useEffect(() => {
    if (!wideNav && !wideContext && railExpanded && contextOpen) {
      setContextOpen(false);
    }
  }, [wideNav, wideContext, railExpanded, contextOpen]);

  /**
   * Re-read the list from the core.
   *
   * The core decides what exists, so the list is always fetched rather than
   * patched locally. A locally-maintained copy would have to be updated on
   * create, switch, delete *and* every turn that retitles a conversation, and
   * the one path someone forgets is the one that leaves a stale row on screen
   * pointing at a conversation that no longer exists.
   */
  const refreshConversations = useCallback(async (): Promise<ConversationSummary[]> => {
    const listed = (await backendRef.current!.call("conversations.list")) as {
      conversations?: ConversationSummary[];
    };
    const rows = listed.conversations ?? [];
    setConversations(rows);
    return rows;
  }, []);

  const refreshConversationsRef = useRef(refreshConversations);
  useEffect(() => {
    refreshConversationsRef.current = refreshConversations;
  }, [refreshConversations]);

  /**
   * Re-read the plan.
   *
   * Normalised rather than trusted: the reply crosses a process boundary, and a
   * status this build does not know is a *row*, not a reason to lose the list.
   * A missing plan leaves the previous one on screen; the first failure leaves
   * the empty state, which is the truth ("no plan is known").
   */
  const refreshPlan = useCallback(async () => {
    try {
      const reply = (await backendRef.current!.call("plan.get")) as Partial<PlanReply> | null;
      const next = reply?.plan;
      if (!next || !Array.isArray(next.todos)) return;
      const todos: PlanItem[] = next.todos
        .filter((item): item is PlanItem => Boolean(item) && typeof item.text === "string")
        .map((item) => ({
          text: item.text,
          status:
            item.status === "completed" || item.status === "in_progress"
              ? item.status
              : "pending",
        }));
      setPlan({
        todos,
        goal: typeof next.goal === "string" ? next.goal : "",
        goal_status: typeof next.goal_status === "string" ? next.goal_status : "",
        goal_note: typeof next.goal_note === "string" ? next.goal_note : "",
      });
    } catch {
      // A panel's meter is not worth an error banner; the last plan stays.
    }
  }, []);

  const refreshPlanRef = useRef(refreshPlan);
  useEffect(() => {
    refreshPlanRef.current = refreshPlan;
  }, [refreshPlan]);

  /**
   * Re-read the context meter.
   *
   * Guarded on `known` because the reply is a measurement, and a reply without
   * one is not a zero: an unanswered call must leave the meter saying `unknown`
   * rather than starting to draw 0%.
   */
  const refreshContextMeter = useCallback(async () => {
    try {
      const reply = (await backendRef.current!.call("context.get")) as Partial<ContextReply> | null;
      if (!reply || typeof reply.known !== "boolean") return;
      setContextMeter({
        model: typeof reply.model === "string" ? reply.model : "",
        used: typeof reply.used === "number" ? reply.used : 0,
        known: reply.known,
        window: typeof reply.window === "number" ? reply.window : 0,
      });
    } catch {
      // Same rule as the plan: keep the last measurement, draw no banner.
    }
  }, []);

  /**
   * When the plan and the meter are re-read.
   *
   * At a turn's start and end -- `busy` is the window's copy of that edge -- and
   * whenever the conversation changes, which is what makes a restored chat show
   * the plan it was saved with. The meter is only read while the panel is open:
   * it is a number nobody can see when the pane is shut, and a request per turn
   * for a hidden value is the kind of traffic this phase is meant to stop.
   */
  useEffect(() => {
    if (!connected) return;
    void refreshPlan();
  }, [connected, conversation, state.busy, refreshPlan]);

  useEffect(() => {
    if (!connected || !contextOpen) return;
    void refreshContextMeter();
  }, [connected, conversation, state.busy, contextOpen, refreshContextMeter]);

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
      // Most recent first, deduplicated, and only what this window opened.
      // Three because the nav block has room for three and a "recent files"
      // list long enough to scroll is a file tree with worse ordering.
      setRecentFiles((seen) => [path, ...seen.filter((p) => p !== path)].slice(0, 3));
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
      try {
        const catalog = (await backend.call("models.catalog")) as {
          models?: Array<{
            id?: string;
            name?: string;
            context_length?: number;
            max_tokens?: number;
            input_modalities?: string[];
            protocol?: string;
          }>;
        };
        const details: Record<string, ModelDetails> = {};
        for (const row of catalog.models ?? []) {
          if (!row || typeof row.id !== "string" || !row.id) continue;
          details[row.id] = {
            name: row.name ?? "",
            context_length: row.context_length ?? 0,
            max_tokens: row.max_tokens ?? 0,
            input_modalities: row.input_modalities ?? [],
            protocol: row.protocol ?? "",
          };
        }
        setModelDetails(details);
      } catch {
        // The list is the contract; facts are enrichment. A catalog failure
        // leaves id-only rows rather than failing the menu.
        setModelDetails(null);
      }
    } catch (error: unknown) {
      setModelList(null);
      setModelListError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  /**
   * Fetch the installer and verify it. Nothing runs until the user says so.
   *
   * **Called on its own as soon as a check finds a new version**, and by hand
   * only when that fetch failed -- the panel offers the button as a retry. So
   * the download is the app's business and the install is the user's, which is
   * the split the two buttons used to draw between them.
   *
   * Two guards, both about not doing the same work twice: a fetch already in
   * flight is left alone, and a file already verified for *this* release is not
   * fetched again. The second is what keeps a re-check from pulling 30 MB that
   * is already on disk.
   */
  const fetchUpdate = useCallback(async (latest?: string) => {
    const backend = backendRef.current;
    if (!backend) return;
    if (updateFetchingRef.current) return;
    if (latest && updateReadyVersionRef.current === latest) return;
    updateFetchingRef.current = true;
    setUpdateFetching(true);
    try {
      const result = (await backend.call("update.download")) as UpdateDownload;
      setUpdateReady(result);
      // Only a verified file counts as ready. A failed fetch records nothing, so
      // the next check tries again rather than deciding it is done.
      if (result.ok) updateReadyVersionRef.current = result.version || latest || "";
    } catch {
      setUpdateReady({ ok: false, reason: "server", path: "", name: "", size: 0 });
    } finally {
      updateFetchingRef.current = false;
      setUpdateFetching(false);
    }
  }, []);

  /**
   * Ask the core whether a newer TONYAgent exists.
   *
   * **Never surfaced as an error.** This is a question the app asks on its own
   * behalf, unprompted -- so an offline laptop must not produce a dialog about
   * a feature nobody invoked. The answer carries its own reason and the panel
   * says it quietly. A thrown failure here is a bug in the protocol rather than
   * news for the user, which is why it is swallowed into the same shape.
   */
  const checkUpdate = useCallback(
    async (force: boolean) => {
      const backend = backendRef.current;
      if (!backend) return;
      setUpdateChecking(true);
      try {
        const answer = (await backend.call("update.check", { force })) as UpdateAnswer;
        setUpdate(answer);
        // A different version means the installer that was downloaded is for the
        // wrong release. Dropped rather than offered: running last week's MSI
        // after seeing this week's notes is the one way this feature could
        // install something the user did not agree to.
        setUpdateReady((prev) => (prev?.version === answer.latest ? prev : null));
        // And then fetch it without being asked. The check already knows the
        // address and the digest, and the only step that *has* to be a decision
        // is running an installer -- so it is fetched now, while the release
        // notes are still being read, and the panel's one button is the press
        // that matters.
        //
        // No installer attached means nothing to fetch; the panel says so
        // rather than starting a download that cannot happen.
        if (answer.available && answer.asset) void fetchUpdate(answer.latest);
      } catch (error: unknown) {
        setUpdate({
          current: "",
          latest: "",
          tag: "",
          available: false,
          prerelease: false,
          notes: "",
          published_at: "",
          url: "",
          asset: null,
          checked_at: 0,
          cached: false,
          reason: "malformed",
        });
      } finally {
        setUpdateChecking(false);
      }
    },
    [fetchUpdate],
  );

  /**
   * Run the verified installer. **This closes the app**, by design.
   *
   * Windows Installer cannot replace a running executable, and the host and the
   * core are one file, so the host starts a helper that waits for this process
   * to exit and then runs the installer. There is nothing to do on the way out:
   * the window is already closing.
   */
  const installUpdate = useCallback(async () => {
    const api = host();
    if (!api) return;
    try {
      await api.update_install();
    } catch {
      // The window is going away regardless; a failure here means the installer
      // did not start, and the user will find the app still open.
      setUpdateReady({ ok: false, reason: "launch_failed", path: "", name: "", size: 0 });
    }
  }, []);

  const openReleases = useCallback(async () => {
    const api = host();
    if (!api) return;
    try {
      await api.open_releases();
    } catch {
      // Opening a browser is best effort; there is nowhere to report it to.
    }
  }, []);

  /**
   * Open the folder the core's log files live in.
   *
   * Best effort like `openReleases`: the host reports whether it opened, but a
   * settings card is not the place that could do anything with a no -- and the
   * path it opened is the one `diagnostics.get` already shows on the card, so
   * the user can see where to look regardless.
   */
  const openLogFolder = useCallback(async () => {
    const api = host();
    if (!api) return;
    try {
      await api.open_logs();
    } catch {
      // Opening a folder is best effort; there is nowhere to report it to.
    }
  }, []);

  /**
   * Open one project file in the OS default app.
   *
   * Best effort like `openLogFolder`: the host confines the path to the
   * project, and a viewer button is not the place that could do anything
   * with a refusal.
   */
  const openExternal = useCallback(async (path: string) => {
    const api = host();
    if (!api || typeof api.open_path !== "function") return;
    try {
      await api.open_path(path);
    } catch {
      // Opening a file is best effort; there is nowhere to report it to.
    }
  }, []);

  /**
   * Copy text to the clipboard, for the diagnostics card.
   *
   * The async clipboard first and a focused field second. The second exists
   * because the clipboard API is unavailable in exactly the situation the card
   * is for -- an insecure context, or a permission the browser withheld -- and
   * "Copy diagnostics" failing there would be the button failing when it is
   * needed most. Resolves true when the text is on the clipboard either way.
   */
  const copyDiagnostics = useCallback(async (text: string): Promise<boolean> => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // Fall through to the field below.
    }
    try {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(field);
      return ok;
    } catch {
      return false;
    }
  }, []);

  /**
   * Ask once, quietly, when the core comes up.
   *
   * Not on a timer and not on every render: the core's own answer is cached for
   * a day, and the check costs one conditional request that GitHub does not
   * charge for. It is keyed on `connected` so it happens once per launch, after
   * there is a core to ask -- before that there is nothing to answer it.
   */
  const checkedOnBootRef = useRef(false);
  useEffect(() => {
    if (!connected || checkedOnBootRef.current) return;
    checkedOnBootRef.current = true;
    void checkUpdate(false);
  }, [connected, checkUpdate]);

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
  const showMessages = useCallback((raw: unknown[]) => {
    const restored: ChatMessage[] = [];
    (raw ?? []).forEach((entry, index) => {
      const message = entry as {
        role?: string;
        content?: string | string[] | null;
        reasoning?: string | null;
      };
      if (!message.role) return;
      const role: Role = message.role === "user" ? "user" : "assistant";
      // A tool result is the one kind of saved row a transcript must not
      // replay. Its `content` is the tool's raw output -- a whole file for
      // `read_file`, the command's stdout for `run_command` -- and leaving it
      // in place squirted that into the conversation as prose: a paste of
      // unrelated source with line numbers, rendered ahead of the answer that
      // was written from it. The live window draws this content in a tool
      // *card*, which is what the transcript means when it says the work
      // happened; restored history has no card to put it in (the tool events
      // themselves were never persisted), so the only honest rendering is not
      // to render the raw output at all. The assistant prose that came out of
      // this work stays, which is what the chat is for.
      if (message.role === "tool") return;

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
      turnStartedAt: null,
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
   * Ask the composer to hold a sentence, and put the caret at its end.
   *
   * A request rather than a value: the field owns its text, and a suggestion is
   * something that happens *to* the field rather than a prop that replaces it.
   * The rAF gives the composer's own effect (which writes the text) a frame to
   * land before the focus moves; focusing first would place the caret in a field
   * that is about to change under it.
   */
  const prefillComposer = useCallback((text: string) => {
    setPrefill((prev) => ({ text, nonce: (prev?.nonce ?? 0) + 1 }));
    requestAnimationFrame(() => composerRef.current?.focus());
  }, []);

  /**
   * Skills, from the nav's row: put the slash in the field and get out of the
   * way.
   *
   * The composer's own `/` menu does the rest -- it lists, filters and inserts --
   * so this action is exactly one character. From Trajectory it first returns to
   * Agent, because there is no composer behind the log; below 1101 it closes the
   * overlay, because the field it just filled is underneath it.
   */
  const useSkills = useCallback(() => {
    setMainMode("agent");
    if (!wideNav) setRailExpanded(false);
    prefillComposer("/");
  }, [wideNav, prefillComposer]);

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
    // The dock stays. Below 1101 the panel is an overlay covering the thing the
    // user just chose, so it leaves; at 1101 and above it is a column of the
    // workspace, and a column that closed itself every time a conversation was
    // selected would be a sidebar nobody could keep open. The guard is here
    // rather than at each caller because three of them (a tab, a row, New chat)
    // share this routine and only one of them is about "get out of the way".
    if (!wideNav) setRailExpanded(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [wideNav]);

  /**
   * Believe a reply about what mode is in force.
   *
   * `mode.set`, `conversations.create` and `conversations.switch` all answer
   * the same pair -- the mode actually in force, and the provider that could
   * not follow it -- so one routine adopts all three. The mode is painted as
   * reported rather than as requested, the mode-filtered provider list is
   * re-read, and a dropped chat-only provider gets the banner rather than a
   * session that has quietly lost its model.
   *
   * Declared before the conversation callbacks that use it: `const` does not
   * hoist, and a helper used before its declaration is a runtime hole the
   * compiler catches.
   */
  const adoptMode = useCallback(
    (modeName: string | undefined, disconnectedProvider: string | undefined) => {
      if (modeName) setMode(modeName);
      // Which providers may be used depends on the mode, so the list is
      // read again. A local chat model is not offered outside Chat mode,
      // and a list still carrying it would offer something the core
      // refuses.
      void refreshProviders();
      if (disconnectedProvider) {
        setState((prev) => ({
          ...prev,
          error:
            `${disconnectedProvider} works in Chat mode only, so it ` +
            `was disconnected when the mode changed.`,
        }));
        setNeedsProvider(true);
        setProvider("");
        setModel("");
      }
    },
    [refreshProviders],
  );

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
          mode?: string;
          disconnected_provider?: string;
        };
        showMessages(result.messages ?? []);
        const opened = result.conversation;
        if (opened) {
          setConversation(opened.id);
          // The track rides the summary, and the mode rides the reply: the
          // core adopted both while loading, so the window paints what is in
          // force rather than sending a `mode.set` of its own -- which would
          // clear the transcript that was just loaded.
          setTrack(opened.track === "chat" ? "chat" : "build");
          adoptMode(result.mode, result.disconnected_provider);
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
    [showMessages, refreshConversations, closePanelToComposer, adoptMode],
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
        setSkillsKnown(true);
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
        }));
      });
  }, []);

  const createConversation = useCallback(
    async (project = "", trackName?: string, stay = false) => {
      // Any act that opens a conversation brings the transcript back, so a new
      // chat cannot be typed into a window that is showing a chart. The tab
      // stays open behind it, the way a tab you switched away from does.
      //
      // `stay` skips the move to the agent view: the track toggle in Code
      // mode's helper mints where it is pressed, and dragging the window out
      // of Code mode to show the same conversation elsewhere would be a
      // switch the user never asked for. Every other caller wants agent.
      if (!stay) {
        setUsageTab((open) => (open === "active" ? "open" : open));
        setMainMode("agent");
      }
      setState((prev) => ({ ...prev, error: null, busy: true }));
      // An explicit track wins; otherwise the new conversation joins the one
      // open -- the "+" mints in the current track, and only the track toggle
      // asks for the other one.
      const wanted = trackName ?? track;
      try {
        const result = (await backendRef.current!.call("conversations.create", {
          project,
          track: wanted,
        })) as {
          conversation?: ConversationSummary;
          mode?: string;
          disconnected_provider?: string;
        };
        showMessages([]);
        const created = result.conversation;
        if (created) {
          setConversation(created.id);
          // The reply's track, not the request's: an empty conversation of the
          // other track may have been reused and retracked, and the row is
          // what is actually in force.
          setTrack(created.track === "chat" ? "chat" : "build");
          adoptMode(result.mode, result.disconnected_provider);
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
    [showMessages, refreshConversations, track, adoptMode],
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
  const startNewChat = useCallback(async (trackName?: string, stay = false) => {
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
    await createConversation(target, trackName, stay);
  }, [project, attachProject, closePanelToComposer, createConversation]);

  /**
   * Cross to the other track by minting, never by converting.
   *
   * A press here starts a fresh conversation in the other track rather than
   * re-moding the open one -- so nothing is cleared, nothing needs confirming,
   * and the chat left behind keeps the track it was written under. Pressing
   * the track already in force does nothing, for the same reason re-picking
   * the mode in force does.
   *
   * It stays where it was pressed: the toggle also sits in Code mode's
   * helper, and minting there must not drag the window back to the agent
   * view to show the same conversation elsewhere.
   */
  const switchTrack = useCallback(
    (next: string) => {
      if (next === track) return;
      void startNewChat(next, true);
    },
    [track, startNewChat],
  );

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
   * Escape leaves the settings page.
   *
   * The same key doing the same job one rung up: settings is a place you enter,
   * and Escape is this window's own way out of one. The page's back button is the
   * other, and it is the one with a label on it -- so this is the shortcut rather
   * than the only door.
   *
   * `defaultPrevented` for the reason above, and it matters more here: this page
   * holds the permission ladder, the thinking dial and the model pickers, and a
   * press that closed one of those must not also leave the page.
   */
  useEffect(() => {
    if (mainMode !== "settings") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setMainMode("agent");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mainMode]);

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

  /**
   * Everything the settings page draws, as the core reports it.
   *
   * Read from the core rather than assembled here. The command lists are the
   * union the shell gate enforces, and the sandbox section carries both the
   * file's values and what is actually serving -- neither of which this window
   * could work out for itself.
   */
  const readSettings = useCallback(async (): Promise<CoreSettings | null> => {
    try {
      const reply = (await backendRef.current!.call("settings.get")) as {
        tools?: CoreSettings["tools"];
        sandbox?: CoreSettings["sandbox"];
      };
      // Checked rather than cast: an unanswered method resolves a marker
      // object, and handing that to the panel's rows would throw in render.
      if (!reply?.tools || !reply?.sandbox) return null;
      return { tools: reply.tools, sandbox: reply.sandbox };
    } catch {
      return null;
    }
  }, []);

  /**
   * Write one setting, or put it back to the default with a value of null.
   *
   * Resolves to null when it took, or to the reason it did not. The core
   * validates each value and its sentence is better than a boolean -- and for
   * these settings the config file *is* the store, so a failed write means
   * nothing changed and the panel has to say so rather than draw what was
   * typed.
   */
  const setSetting = useCallback(
    async (key: string, value: unknown): Promise<string | null> => {
      try {
        const reply = (await backendRef.current!.call("settings.set", {
          key,
          value,
        })) as { persisted?: boolean };
        if (!reply?.persisted) {
          return "That setting could not be written to config.toml.";
        }
        return null;
      } catch (error) {
        return error instanceof Error ? error.message : String(error);
      }
    },
    [],
  );

  /**
   * The facts a bug report needs, as the core knows them.
   *
   * Read from the core rather than assembled here, for the reason the method's
   * own docstring gives: the config path depends on the platform and on which
   * APPDATA the core sees, and a path this window guessed at is how a user ends
   * up looking for logs in a folder that was never written to. Checked rather
   * than cast, like `readSettings`: an unanswered method resolves a marker.
   */
  const readDiagnostics = useCallback(async (): Promise<DiagnosticsInfo | null> => {
    try {
      const reply = (await backendRef.current!.call("diagnostics.get")) as Partial<DiagnosticsInfo>;
      if (
        typeof reply?.version !== "string" ||
        typeof reply?.author !== "string" ||
        typeof reply?.python !== "string" ||
        typeof reply?.frozen !== "boolean" ||
        typeof reply?.config_path !== "string" ||
        typeof reply?.log_dir !== "string"
      ) {
        return null;
      }
      return {
        version: reply.version,
        author: reply.author,
        python: reply.python,
        frozen: reply.frozen,
        config_path: reply.config_path,
        log_dir: reply.log_dir,
      };
    } catch {
      return null;
    }
  }, []);

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
        const applied = result as { mode?: string; disconnected_provider?: string };
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
        adoptMode(applied.mode, applied.disconnected_provider);
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
  }, [refreshProviders, adoptMode]);

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
   *
   * What the two modes share is the *conversation*, which is why
   * `conversationView` below is one element rather than two: Code mode shows it
   * in the assistant panel instead of under a tab strip, it does not have a
   * second one.
   */
  const codeMode = mainMode === "code";
  const trajectoryMode = mainMode === "trajectory";
  const settingsMode = mainMode === "settings";
  const agentMode = !codeMode && !trajectoryMode && !settingsMode;
  /**
   * The two modes that own a nav.
   *
   * Trajectory gained the dock in Phase 2: it is a reading surface like the
   * transcript -- the log is the conversation's raw form -- and leaving its left
   * edge empty while the same chats are one click away in Agent made the window
   * change shape rather than change page. Code still has its explorer, and
   * Settings still has no app nav at all.
   */
  const navMode = agentMode || trajectoryMode;

  /* Whether each open pane is a grid column or an overlay at this width. */
  const navDocked = railExpanded && wideNav;
  const contextDocked = contextOpen && wideContext;
  const contextOverlay = contextOpen && !wideContext;

  /**
   * What the Run card reads.
   *
   * Memoised on the facts it derives from, so a render caused by a resize, a
   * dialog or the panel's own tick does not rebuild it. The reducer copies the
   * message list on each delta, so a streaming turn does rebuild it -- the cost
   * is one pass over the turn's tool calls, which is nothing beside the copy the
   * reducer has already made. Phase 3, when the feed shows rows rather than one
   * state, can narrow the dependency to a tool signature.
   */
  const activity = useMemo(
    () => turnActivity(state),
    [
      state.messages,
      state.busy,
      state.activeTurnId,
      state.turnStartedAt,
      state.pendingConfirm,
      state.pendingAsk,
      state.error,
    ],
  );
  const runningStep = [...activity.steps].reverse().find((step) => step.status === "running");
  const runDetail = runningStep ? `Running ${runningStep.name}` : "";

  /**
   * The last turn's spend, in the one number the strip has room for.
   *
   * Input plus output, which is what a provider bills and what the Usage page
   * totals. Reasoning is *inside* output -- adding it here would count the
   * thinking twice -- so it is left to the Run card's tooltip, where there is
   * room to say what it is.
   */
  const turnTokens = state.turnUsage
    ? state.turnUsage.input + state.turnUsage.output
    : null;

  /** The call that wrote the plan, when it is still in the transcript. */
  const planCallId = useMemo(
    () => lastPlanCall(state.messages)?.id ?? null,
    [state.messages],
  );

  /**
   * Take the reader from a plan row to the call that wrote it.
   *
   * Below the dock width the panel is an overlay with a scrim, so it gets out of
   * the way first -- the same rule choosing a conversation follows. The scroll
   * waits a frame for that unmount, because scrolling to an element inside a
   * container that is about to be hidden lands on a position that is no longer
   * on screen.
   *
   * No smooth behaviour: the window's motion preference is a CSS one, and a
   * scripted smooth scroll would ignore it.
   */
  const revealPlan = useCallback(() => {
    if (planCallId === null) return;
    if (!wideContext) setContextOpen(false);
    requestAnimationFrame(() => {
      document
        .querySelector(`[data-call-id="${planCallId}"]`)
        ?.scrollIntoView({ block: "center" });
    });
  }, [planCallId, wideContext]);

  /*
   * The pills the composer may draw: the track's share of the core's list.
   *
   * Chat is not one pill among five -- it is the other kind of conversation,
   * so a chat-track conversation draws Chat alone and a build-track one draws
   * the four working modes. Filtered here rather than in the composer, which
   * stays dumb about tracks the way the TopBar stays dumb about models. A
   * filter that matched nothing draws everything: a composer with no pills is
   * a composer that cannot switch.
   */
  const trackModes = modes.filter((m) =>
    track === "chat" ? m.name === "chat" : m.name !== "chat",
  );
  const composerModes = trackModes.length > 0 ? trackModes : modes;
  // Labels for the top-bar toggle, from the core's own list -- never written
  // out here, for the reason `modes` gives at boot.
  const chatLabel = modes.find((m) => m.name === "chat")?.label ?? "Chat";
  const buildLabel = modes.find((m) => m.name === "build")?.label ?? "Build";
  // The toggle lives where conversations are opened -- agent and code, which
  // share the one conversation -- and not in trajectory or settings, where
  // minting a chat would happen behind the page.
  const trackChange = trajectoryMode || settingsMode ? undefined : switchTrack;

  /**
   * Settings, which is a *page* rather than a pane.
   *
   * It was the sidebar's fourth pane -- 288px with four tabs across the top --
   * and the row was the constraint everything else was built around: four tracks
   * of 63px, "Permission" the longest label, and a fifth section rejected
   * because it does not fit. Full-window it is the arrangement that has no such
   * ceiling: the sections down the left, the chosen one beside it.
   *
   * A mode and not a flag, for the reason Code mode is one: this decides what
   * the *shell* renders. The rail, the conversation overlay and the tab strip
   * are all absent from it, and `--rail-w` of column 1 goes with them -- see
   * `.app[data-mode="settings"]`. Declared with the other view flags above.
   */

  /**
   * The conversation: the transcript, anything the window has to say about it,
   * and the field.
   *
   * **One element, placed twice.** There is one session and one transcript in
   * this window -- the tabs, the rail's message count and the assistant panel
   * are all reading the same `state` -- so these props are written once, and a
   * second copy inside the panel would be the second place the two could
   * disagree about what is on screen. The failure would be quiet rather than
   * loud: a transcript that stops streaming in the panel, or a field that sends
   * into a conversation nobody is looking at.
   *
   * Only one of the two placements is mounted at a time (`codeMode` decides
   * which), so this is never two composers, and never two scrollers both
   * pinning themselves to the end of the same message.
   */
  const conversationView = (
    <>
      {/*
        Nothing said yet: the launchpad rather than an empty transcript. It is
        placed by the App and not by `MessageList` because it needs the folder,
        the provider, the model, the recent chats and a way to write into the
        composer -- five things the transcript has no business carrying, and
        five props a message list would have had to pass through to a child
        that draws no messages.
      */}
      {state.messages.length === 0 ? (
        <Launchpad
          project={project}
          connected={connected}
          needsProvider={needsProvider}
          model={model}
          conversations={conversations}
          activeId={conversation}
          onChooseFolder={() => void chooseFolder()}
          canChooseFolder={connected && !state.busy}
          onOpen={(id) => void openConversation(id)}
          onPrefill={prefillComposer}
          // The Keys tab, because that is where a provider and its key are
          // entered, and the page lands there rather than on its first section.
          onSetup={() => openSettings("keys")}
        />
      ) : (
        <MessageList messages={state.messages} busy={state.busy} />
      )}

      {state.error && <div className="banner">{state.error}</div>}

      {/*
        The composer, and nothing else. The permission ladder used to sit above
        it as its own bar, with the Thinking dial as a native select in the
        control row; both are in the settings panel now, where a user goes to
        ask what this window may do rather than scrolling past a strip to find
        out. See `SettingsMenus`.
      */}
      <Composer
        inputRef={composerRef}
        busy={state.busy}
        disabled={!connected}
        modes={composerModes}
        mode={mode}
        skills={skills}
        onSkillsNeeded={loadSkills}
        onModeChange={changeMode}
        onSend={send}
        prefill={prefill}
        onPrefillApplied={() => setPrefill(null)}
        onCancel={cancel}
        maxToolCalls={maxToolCalls}
        budgetOpen={budgetOpen}
        onBudgetOpen={() => setBudgetOpen(true)}
        onBudgetClose={() => setBudgetOpen(false)}
        onBudgetChange={(limit) => void changeToolBudget(limit)}
      />
    </>
  );

  return (
    <div
      className="app"
      data-mode={mainMode}
      /*
        The two dock states, as attributes rather than two more classes.
        `data-nav` is what lets the stylesheet size column 1 from one number and
        lets the tests ask "is the nav docked at this width" without parsing a
        media query; `data-context` is the same question for column 3. Neither
        is a behaviour flag -- `App` has already decided what to mount.
      */
      data-nav={railExpanded ? "open" : "closed"}
      data-context={contextOpen ? "open" : "closed"}
    >
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
        // The strip is the conversation's, and Code, Trajectory and Settings
        // have no conversation in front. The bar keeps the mark, the drag
        // region, the switch and the caption -- which is what "the whole screen
        // changes" means at the top edge of the window as well as the middle.
        tabs={codeMode || trajectoryMode || settingsMode ? [] : tabStrip}
        active={
          codeMode || trajectoryMode || settingsMode
            ? ""
            : usageTab === "active"
              ? USAGE_TAB
              : conversation
        }
        track={track}
        onTrackChange={trackChange}
        chatLabel={chatLabel}
        buildLabel={buildLabel}
        /*
          The run's one live state.

          In Agent it is also the run panel's handle, and it is present while
          idle so the answer to "what is happening" has somewhere to live. In
          the other modes there is no panel to open, so a quiet window draws
          nothing and a busy one draws a signpost back to Agent.
        */
        status={
          <StatusPill
            run={activity.run}
            detail={runningStep?.name ?? ""}
            panel={agentMode ? { open: contextOpen, onToggle: toggleContext } : undefined}
            onReturn={() => setMainMode("agent")}
          />
        }
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
        onNewTab={codeMode || trajectoryMode ? undefined : () => void startNewChat()}
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
              details={modelDetails}
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
      {navMode && !navDocked && (
        <IconRail
          connected={connected}
          busy={state.busy}
          messageCount={state.messages.length}
          expanded={railExpanded}
          onToggle={toggleNav}
          onCancel={cancel}
          dashboardOpen={usageTab === "active"}
          onDashboard={openUsage}
          petOpen={petOpen}
          onPet={() => void togglePet()}
          updateAvailable={Boolean(update?.available)}
          onSettings={() => openSettings()}
          onSearch={() => openSidebarPane("search")}
          // The rail's own switch, because the nav it belongs to is closed at
          // this width -- and in Trajectory that is the only way back out.
          view={mainMode}
          canCode={project !== ""}
          onViewChange={(next) => setMainMode(next)}
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
      {navMode && conversationsMounted && (
        <ConversationList
          open={railExpanded}
          docked={navDocked}
          /*
            The view switch, in the nav's head. Code carries its own copy in
            the explorer head while its nav is still a column of files; Settings
            renders none, because the page's back control is its way out and
            the switch's three workspaces are not "views of" it.
          */
          viewSwitch={
            <ViewSwitch
              mode={mainMode}
              canCode={project !== ""}
              onChange={(next) => setMainMode(next)}
            />
          }
          onNewChat={() => void startNewChat()}
          onSkills={useSkills}
          skillCount={skillsKnown ? skills.length : null}
          // The App tab, because that is the page that lists them: Settings has
          // no Skills tab, and inventing a fifth one would have made the row
          // that already names the skills a lie.
          onManageSkills={() => openSettings("app")}
          recentFiles={recentFiles}
          onUsage={openUsage}
          usageOpen={usageTab === "active"}
          onPet={() => void togglePet()}
          petOpen={petOpen}
          conversations={conversations}
          active={conversation}
          project={project}
          busy={state.busy}
          connected={connected}
          onDismiss={() => setRailExpanded(false)}
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
          // The search pane. Built here rather than by the sidebar, because the
          // App owns every handler it needs -- and passed as an element so
          // `ConversationList` stays a container and never imports it.
          searchPane={
            <SearchPanel
              connected={connected}
              hasProject={project !== ""}
              onSearch={search}
            />
          }
          // The rail's actions, because the sidebar covers the rail when open
          // (see ConversationList). Same handlers the rail is given, so the two
          // states of the one sidebar cannot disagree about what a button does
          // -- and the same mark on the gear, for the same reason.
          onSearch={() => openSidebarPane("search")}
          onSettings={() => openSettings()}
          updateAvailable={Boolean(update?.available)}
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
            {/*
              Code's copy of the workspace switch.

              It is here rather than in the title bar because the nav owns the
              switch now, and this head *is* Code's nav until Phase 5 moves the
              explorer into the dock: same corner, same control, so the way out
              of a mode is never a different corner in each mode. The title bar
              has no room for it at the window's minimum width, which is the
              whole reason it left.
            */}
            <ViewSwitch
              mode={mainMode}
              canCode={project !== ""}
              onChange={(next) => setMainMode(next)}
            />
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
          the **core's** agent mode (`chat`, `build`, `plan`, `mission`, `skills`), a
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
        {settingsMode ? (
          /*
            The settings page, in place of the conversation.

            Not a dialog over it and not a pane beside it: the whole window below
            the title bar, with the rail and the tab strip gone -- which is what
            makes it a place you are *in* rather than a panel you have open. See
            `SettingsPanel`, which is one page now and no longer has to fit
            anything into 288px.
          */
          <SettingsPanel
            connected={connected}
            busy={state.busy}
            initialTab={settingsTab ?? undefined}
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
            motion={motion}
            onMotionChange={setMotion}
            // Back to the conversation. The page is a mode, so leaving it is
            // `agent` -- the same thing the title bar's own switch sets.
            onClose={() => setMainMode("agent")}
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
            onReadSettings={readSettings}
            onSetSetting={setSetting}
            onReadDiagnostics={readDiagnostics}
            onCopyDiagnostics={copyDiagnostics}
            onOpenLogFolder={() => void openLogFolder()}
            // `null` until the core answers, so the page can say "not read yet"
            // rather than "no skills" -- see `SettingsPanel`'s prop.
            skills={skillsKnown ? skills : null}
            onLoadSkills={loadSkills}
            update={update}
            updateChecking={updateChecking}
            updateFetching={updateFetching}
            updateReady={updateReady}
            onCheckUpdate={(force) => void checkUpdate(force)}
            onDownloadUpdate={() => void fetchUpdate()}
            onInstallUpdate={() => void installUpdate()}
            onOpenReleases={() => void openReleases()}
          />
        ) : trajectoryMode ? (
          <TrajectoryView events={trajectory} />
        ) : codeMode ? (
          /*
            The code half: the file, and the assistant beside it.

            **The assistant panel is the change here.** Code mode used to end at
            the file -- the composer went with the transcript, because a text
            field under a file offers a message for a conversation that is not
            on screen. That was right about the *window* and wrong about the
            work: reading a file is exactly when the question about it arrives,
            and the only way to ask was to leave the file you were asking about.
            So the conversation is docked on the right instead -- the same
            transcript, the same composer, the file still open beside them.

            Everything inside `.code-split` is that pair. The shell around it
            -- the title bar, the status bar, the dialogs and the log strip --
            belongs to `.main`, which is why this is a row *inside* the column
            rather than a third grid column of the window: with the panel in
            its own column the status bar stopped at the editor's edge, and a
            strip that ends halfway across a window reads as a defect rather
            than as a decision.

            With no file open this is a signpost rather than a blank pane: the
            project is there, the tree is one click away, and an empty surface
            that explains nothing is the dead end this replaces.
          */
          <div className="code-split">
            {viewerPath === "" ? (
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
                onOpenExternal={(path) => void openExternal(path)}
              />
            )}

            {/*
              The assistant: a header with the one control that puts it away,
              and the conversation below it.

              Docked rather than floating, and put away by a click rather than
              by a breakpoint: a panel that vanishes when the window narrows is
              a panel whose state the user did not choose, and the toggle is how
              this window has always answered "I need the width" -- see the
              rail. A narrow window keeps it too, over the file rather than
              beside it; see the media query in `shell.css`.

              The header stays when the panel is away, and that is the whole
              reason the toggle lives in it rather than in the file header: the
              control that put the panel away is inside the panel, so a closed
              state that unmounted everything would hide its own way back. What
              goes away is the *body*, which is also why reopening starts at the
              end of the conversation -- `MessageList` pins to the bottom when it
              mounts, and a scroller left in a hidden subtree would have come
              back where it was, or at the top.
            */}
            <aside
              className="helper"
              data-state={helperOpen ? "open" : "closed"}
              aria-label="Assistant"
            >
              <div className="helper-head">
                <span className="helper-title">Assistant</span>
                <button
                  type="button"
                  className="helper-toggle"
                  onClick={() => setHelperOpen((open) => !open)}
                  title={helperOpen ? "Hide the assistant" : "Show the assistant"}
                  aria-label={helperOpen ? "Hide the assistant" : "Show the assistant"}
                  aria-expanded={helperOpen}
                >
                  {/*
                    A frame with a divider: on the right when the panel is
                    shown, pushed against the edge when it is away. The rail's
                    toggle is the mirror of this and not the same drawing,
                    because the two name opposite edges -- and `currentColor`
                    with `strokeWidth` is the rail's own frame, so the two read
                    as one family.
                  */}
                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d={HELPER_GLYPH[helperOpen ? "open" : "closed"]} />
                  </svg>
                </button>
              </div>

              {helperOpen && <div className="helper-body">{conversationView}</div>}
            </aside>
          </div>
        ) : usageTab === "active" ? (
          <Dashboard
            connected={connected}
            onClose={() => setUsageTab("open")}
            load={loadUsage}
          />
        ) : (
          /* The conversation, in the column it belongs to -- see `conversationView`. */
          conversationView
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

      </div>

      {/*
        The context pane, and its scrim.

        Rendered only in Agent mode: Code has its own assistant panel on the
        right and Settings, Usage and Trajectory have no turn to report. The
        scrim is a sibling rather than a child of the panel so the panel itself
        stays above it -- and it is only mounted when the pane is an overlay,
        because a docked pane has no "behind" to dismiss.

        **After `.main` in the DOM**, which is also where it is on screen. The
        grid puts it in column 3; the order here is what makes the tab sequence
        go nav -> centre -> context -> strip, matching the visual order. Mounted
        before the transcript it would have been the middle stop on the way to
        the composer, which is the opposite of where the eye goes.
      */}
      {agentMode && contextOverlay && (
        <button
          type="button"
          className="context-scrim"
          onClick={() => setContextOpen(false)}
          tabIndex={-1}
          aria-label="Close the run panel"
        />
      )}
      {agentMode && (
        <ContextPanel
          open={contextOpen}
          docked={contextDocked}
          run={activity.run}
          startedAt={state.turnStartedAt}
          detail={runDetail}
          usage={state.turnUsage}
          plan={plan}
          planCallId={planCallId}
          steps={activity.steps}
          files={activity.files}
          context={contextMeter}
          onToggle={toggleContext}
          onStop={cancel}
          onOpenTrajectory={() => setMainMode("trajectory")}
          onRevealPlan={revealPlan}
          onOpenFile={(path) => void openFile(path)}
        />
      )}

      {/*
        The window's lower edge, and now the window's rather than the main
        column's: it is a row of the shell, so it spans the nav, the centre and
        the context pane instead of stopping at the editor's edge in Code mode.
        That is also why it is after `.main` rather than inside it -- a grid item
        cannot span tracks it is nested under.
      */}
      <StatusBar
        provider={provider}
        model={model}
        sandbox={sandbox}
        connected={connected}
        needsProvider={needsProvider}
        turnTokens={turnTokens}
        onConfigure={() => {
          openSettings();
        }}
        logLines={logLines}
        logsOpen={logsOpen}
        onToggleLogs={() => setLogsOpen((open) => !open)}
      />
    </div>
  );
}
