/**
 * Settings panel.
 *
 * One modal for everything the rail can actually change, rather than a separate
 * surface per thing: the project folder and the provider both answer "what is
 * this window working on", and the permission level and the thinking effort both
 * answer "how much may it do without asking". Splitting them would mean more
 * surfaces to style and more ways to reach the same core methods.
 *
 * **Model selection is deliberately not here.** This panel used to carry a
 * provider picker, a model picker and an Apply that bound them together. That
 * is a choice about what a new conversation talks to, not a property of the
 * window, and it lived in the composer's model chip the whole time. Two places
 * to change one binding meant two places that could disagree about it. The one
 * field that is *not* model selection stays: the Base URL, which is how a
 * person points the app at a local Ollama or a proxy. It is an endpoint, not a
 * model id, and there is nowhere else to set it.
 *
 * The API key controls are the other half, and they are now named: one section
 * per provider, every stored key a row with reveal, use and delete, and a row
 * to add one. A name is a real thing the keyring cannot enumerate -- see
 * keyring.stored_key_names -- so the list comes from the core's registry.
 *
 * The key field is uncontrolled-then-cleared so the value lives in the DOM for
 * the shortest possible time, and the reveal is a *press*: key.reveal is the
 * only method in the protocol whose reply carries a secret, and it is never
 * called by anything that runs on its own.
 */

import { useEffect, useRef, useState } from "react";

import {
  PermissionDetail,
  PermissionMenu,
  ThinkingMenu,
  type PermissionList,
  type ReasoningInfo,
} from "./SettingsMenus.js";
import { prettifyModelName } from "./displayNames.js";

/**
 * One `update.check` reply.
 *
 * `reason` is "" when the question was answered and otherwise names why it was
 * not. The panel turns that into a sentence rather than showing the token --
 * see `updateMessage`, which is a pure function so the wording is testable
 * without a window.
 */
export interface UpdateAnswer {
  current: string;
  latest: string;
  tag: string;
  available: boolean;
  prerelease: boolean;
  notes: string;
  published_at: string;
  url: string;
  asset: { name: string; size: number; digest: string; url: string } | null;
  checked_at: number;
  cached: boolean;
  reason: string;
}

/** One `update.download` reply. `reason` is "" when the file is ready. */
export interface UpdateDownload {
  ok: boolean;
  reason: string;
  path: string;
  name: string;
  size: number;
  version?: string;
}

/**
 * What to say about an answer, in one sentence.
 *
 * **Every failure gets its own wording, and none of them say "up to date".** A
 * check that could not run has not learned that this version is the newest, and
 * telling the user they are current on the strength of a failed request is the
 * one claim this feature must never make. The same distinction `models.list`
 * draws between "no models" and "could not ask".
 */
export function updateMessage(answer: UpdateAnswer | null): string {
  if (!answer) return "Not checked yet.";
  if (answer.reason === "offline") return "Could not reach GitHub. Check your connection.";
  if (answer.reason === "rate_limited") return "GitHub is rate-limiting this machine. Try again later.";
  if (answer.reason === "not_found") {
    return "The release repository could not be read. It may be private or renamed.";
  }
  if (answer.reason === "server") return "GitHub returned an error. Try again later.";
  if (answer.reason === "malformed") return "GitHub answered with something this app could not read.";
  if (answer.available) {
    return `${answer.tag || answer.latest} is available.`;
  }
  return "You are up to date.";
}

/** Shape of one entry in the providers.list reply. */
export interface ProviderInfo {  name: string;
  models: string[];
  has_credentials: boolean;
  /**
   * True when the provider is a plain chat model: usable in Chat mode and
   * nowhere else.
   *
   * The core does not send these providers outside Chat mode at all, so this
   * is only ever true for a row that is being drawn *in* Chat mode. It is
   * carried so the panel can say what the provider is, rather than leaving
   * the user to discover it by switching modes and watching the row vanish.
   */
  chat_only?: boolean;
}

/** One stored key, as key.list reports it. Never carries a value. */
export interface KeyEntry {
  provider: string;
  name: string;
  active: boolean;
}

/**
 * The command lists, as `settings.get` reports them.
 *
 * `command_denylist` is what a turn is held to -- the core's own patterns plus
 * anything the config file adds -- and it is here to be read rather than
 * edited. `command_allowlist_defaults` is what "Restore defaults" goes back to,
 * sent by the core so this component does not hold a copy of a list the core
 * owns and would go stale the day the list changes.
 */
export interface CommandSettings {
  command_allowlist: string[];
  command_allowlist_defaults: string[];
  command_denylist: string[];
}

/** Where the sandbox is actually running, as `settings.get` reports it. */
export interface SandboxRuntime {
  running: boolean;
  /**
   * The backend's own name: "wsl", "docker", "local", or "" while stopped.
   *
   * Reported instead of the configured type, because `auto` is the common
   * value and says nothing about what it resolved to. A page that could only
   * echo "Auto" would leave a user unable to tell whether they got the
   * environment they expected.
   */
  kind: string;
  /** The distro in use, on WSL; "" on every other backend. */
  distro: string;
  /** Whether what runs inside is actually contained. */
  isolated: boolean;
}

/**
 * The sandbox section, as `settings.get` reports it.
 *
 * The five fields are the ones a person changes on purpose. The rest of the
 * `[sandbox]` table -- pids, capabilities, ulimits -- is the containment the
 * backend guarantees, and a settings page that could loosen it would be a page
 * that can turn the sandbox off one switch at a time.
 */
export interface SandboxSettings {
  type: string;
  wsl_distro: string;
  enable_network: boolean;
  memory_limit: string;
  cpu_limit: string;
  /**
   * What each field goes back to when it is empty.
   *
   * Sent rather than hardcoded here so the placeholders cannot drift from the
   * model that actually answers when the file says nothing.
   */
  defaults: {
    wsl_distro: string;
    memory_limit: string;
    cpu_limit: string;
  };
  runtime: SandboxRuntime;
}

/**
 * Everything `settings.get` answers with.
 *
 * One read for both groups. They live on different tabs, but a second method
 * for the second half would be a second chance for the two to disagree -- and
 * they are read from the same file, so they can be answered together.
 */
export interface CoreSettings {
  tools: CommandSettings;
  sandbox: SandboxSettings;
}

/**
 * The facts a bug report needs, as `diagnostics.get` reports them.
 *
 * Paths rather than names: the config path depends on the platform and on
 * which APPDATA the core sees, and the log directory is the one the logging
 * setup writes. A window that guessed at either would send the user looking in
 * a folder that was never written to.
 */
export interface DiagnosticsInfo {
  version: string;
  author: string;
  python: string;
  /** Whether this is the installed build rather than a source checkout. */
  frozen: boolean;
  config_path: string;
  log_dir: string;
}

/** Where this build runs from, in one sentence. */
export function diagnosticsRuntime(info: DiagnosticsInfo): string {
  return info.frozen
    ? "Installed app (frozen bundle), Python " + info.python + "."
    : "From source, Python " + info.python + ".";
}

/**
 * The card as plain text, for the clipboard.
 *
 * Built here rather than in the window so the shape is testable without one:
 * what gets pasted into an issue should be exactly what the card shows, and
 * two renderings of the same facts are two chances to disagree.
 */
export function diagnosticsText(info: DiagnosticsInfo): string {
  return [
    "TONYAgent " + info.version + " by " + info.author,
    diagnosticsRuntime(info),
    "Config: " + info.config_path,
    "Logs: " + info.log_dir,
  ].join("\n");
}

/**
 * The backends a window may choose, in display order.
 *
 * `windows` is missing on purpose: `WsbSandboxBackend` is a documented stub
 * whose transport methods are all `pass`, so choosing it would configure a
 * sandbox that cannot start. A file that already names it still draws it --
 * see the select -- but nothing here selects it.
 */
const SANDBOX_BACKENDS = [
  { id: "auto", label: "Automatic" },
  { id: "docker", label: "Docker" },
  { id: "wsl", label: "WSL" },
  { id: "local", label: "None (on this computer)" },
] as const;

/** One sentence naming where code is running, from what the core reported. */
export function sandboxIdentity(runtime: SandboxRuntime | null): string {
  if (!runtime || !runtime.running) return "Not running.";
  if (runtime.kind === "wsl") {
    return runtime.distro
      ? "Running in WSL (" + runtime.distro + ")."
      : "Running in WSL.";
  }
  if (runtime.kind === "docker") return "Running in Docker.";
  if (runtime.kind === "local") return "Running on this computer, without isolation.";
  // A backend that did not name itself. Saying "Running" is weaker than naming
  // it and stronger than claiming it is stopped, which is the only thing we
  // know for certain is not true.
  return "Running.";
}

/** What that means for the tools, in one sentence. */
export function sandboxMeaning(runtime: SandboxRuntime | null): string {
  if (!runtime || !runtime.running) {
    return "Choose a project folder and press Start above.";
  }
  if (runtime.isolated) {
    return "Code the agent writes runs in there. The permission level still decides whether it may run at all.";
  }
  return "Code the agent writes cannot run here unless the permission level is Full, which runs it on this computer.";
}

/**
 * The panel's sections, as tabs.
 *
 * Four, because there are four questions in here and they get asked at
 * different times: how the agent is allowed to behave, what it is working on,
 * what it is talking to, and what the program itself does. The third tab is Keys
 * rather than Model now that the model pickers are gone -- the credential is the
 * only thing left on it.
 *
 * **App rather than Window, and About is not a fifth tab.** The last tab used to
 * be called Window, because the desktop pet was the only thing on it. The
 * version and the update check are the same kind of setting -- they change
 * nothing about the agent, they are about the program -- so they belong beside
 * it rather than in a tab of their own.
 *
 * A fifth tab was tried first and does not fit. Measured: the pane's usable
 * width is 252px, which is 48px per track at five, and "Behavior" measures about
 * 55px at `--text-sm`. The row is why the labels are short in the first place --
 * "Permission" measured 69px against four 63px tracks and was renamed for it --
 * and the honest answer to a fifth label is a different arrangement rather than
 * a clipped one.
 */
const SETTINGS_TABS = [
  { id: "permission", label: "Behavior" },
  { id: "project", label: "Project" },
  { id: "keys", label: "Keys" },
  { id: "app", label: "App" },
] as const;

type SettingsTab = (typeof SETTINGS_TABS)[number]["id"];

export type { SettingsTab };

interface Props {
  connected: boolean;
  busy: boolean;
  providers: ProviderInfo[];
  provider: string;
  /**
   * The endpoint override last bound, or "" for the provider default.
   *
   * Held by the window rather than the core because the reply to
   * bind_provider echoes only what was requested; the core never claims a
   * default the provider chooses for itself.
   */
  baseUrl: string;
  project: string;
  sandbox: string;
  /**
   * Whether the core currently trusts project.
   *
   * Passed in rather than read here because the protocol has no trust.get:
   * the orchestrator keeps the set in memory, and the only way a frontend can
   * learn the answer is to remember what it asked for. Inventing a getter
   * would mean the panel could disagree with the core.
   */
  trusted: boolean;
  permissionList: PermissionList | null;
  permission: string;
  reasoning: ReasoningInfo | null;
  error: string | null;
  notice: string | null;
  /** Whether the desktop pet's card is on screen right now. */
  petOpen: boolean;
  /**
   * Show or hide the card.
   *
   * Deliberately not gated on `connected`. The pet is a *window* -- the shell can
   * make one whether or not a core is running, and a card that says "waiting"
   * beside a stopped core is telling the truth. The rail's entry is enabled for
   * the same reason; this is the second way to reach it, not a different thing.
   */
  onPet: () => void;
  /**
   * The last answer about updates, or null before one has arrived.
   *
   * `UpdateAnswer` rather than a boolean, because the interesting cases are not
   * "yes" and "no": a check that could not reach GitHub has not learned that
   * you are current, and the panel has to say which of those happened.
   */
  update: UpdateAnswer | null;
  /** The check is in flight. The fetch below has its own flag. */
  updateChecking: boolean;
  /**
   * The installer is being fetched and verified.
   *
   * Separate from `updateChecking` because the fetch starts on its own: with one
   * flag, a check that found a new version would put "Checking…" on a button
   * nobody pressed while 30 MB arrived in the background.
   */
  updateFetching: boolean;
  /** The downloaded installer, once one has been fetched and verified. */
  updateReady: UpdateDownload | null;
  onCheckUpdate: (force: boolean) => void;
  onDownloadUpdate: () => void;
  /** Run the installer and close the app. */
  onInstallUpdate: () => void;
  /** Open the releases page in the user's own browser. */
  onOpenReleases: () => void;
  onClose: () => void;
  onChooseFolder: () => void;
  onStartSandbox: () => void;
  onStopSandbox: () => void;
  onPermissionChange: (name: string) => void;
  onReasoningChange: (effort: string) => void;
  /**
   * Bind the Base URL to the provider already in use.
   *
   * No provider or model arguments: the panel no longer chooses either, and
   * passing them would let it name a provider the window is not on.
   */
  onApplyEndpoint: (baseUrl: string) => void;
  onTrust: (project: string, trusted: boolean) => void;
  /** Save one key under one name. An empty name means the default slot. */
  onSaveKey: (provider: string, name: string, apiKey: string) => Promise<boolean>;
  onDeleteKey: (provider: string, name: string) => Promise<boolean>;
  /**
   * Read one stored key, for the Reveal control. Resolves to null when there is
   * nothing stored under that name or the keyring will not answer -- the panel
   * shows nothing either way, because those two states are the same thing to a
   * user who is about to type a key in.
   */
  onRevealKey: (provider: string, name: string) => Promise<string | null>;
  /** Make one stored key the one a turn spends. */
  onActivateKey: (provider: string, name: string) => Promise<boolean>;
  /**
   * Every stored key, from the core's registry.
   *
   * A callback rather than a prop, because the list has to be re-read after
   * every mutation: the row that disappeared must disappear because the store
   * says so, not because this component edited its own copy and would keep
   * saying so if the delete had failed.
   */
  onListKeys: (provider?: string) => Promise<KeyEntry[]>;
  /**
   * Everything the page draws, as the core reports it.
   *
   * One read for both groups rather than one per group: `settings.get` answers
   * with both, and a second call for the second half would be a second chance
   * for the two to disagree. Resolves to null when the core will not answer,
   * which is drawn as "not read yet" rather than as an empty list: "nothing is
   * allowed" and "I could not ask" are different claims, and only one of them
   * is about the user's settings.
   */
  onReadSettings: () => Promise<CoreSettings | null>;
  /**
   * Write one setting.
   *
   * Resolves to null when it took, or to the reason it did not. The core
   * validates -- a memory limit with no unit, a program name that is really a
   * path -- and its sentence is better than anything this component could
   * invent from a boolean. For these settings the config file *is* the store,
   * so a failure means nothing changed.
   */
  onSetSetting: (key: string, value: unknown) => Promise<string | null>;
  /**
   * The facts a bug report needs, as the core reports them.
   *
   * Resolves to null when the core will not answer, drawn as "not read yet"
   * rather than as empty facts: a missing version and a missing log folder are
   * different claims, and only one of them is about this build.
   */
  onReadDiagnostics: () => Promise<DiagnosticsInfo | null>;
  /**
   * Copy text to the clipboard. Resolves true when it is there.
   *
   * A callback rather than `navigator.clipboard` inline so the panel stays
   * testable without a clipboard: the window owns the fallback chain, the card
   * owns the text and the notice.
   */
  onCopyDiagnostics: (text: string) => Promise<boolean>;
  /** Open the folder the core's log files live in, in the file explorer. */
  onOpenLogFolder: () => void;
  /**
   * The tab a directed open lands on, or undefined for the default.
   *
   * Sending with no provider opens Keys. Read once as the initial tab: the
   * page remounts on every open, so this is fresh each time by construction.
   */
  initialTab?: SettingsTab;
}

/** How long a revealed key stays on screen before it hides itself. */
const REVEAL_MS = 15000;

/** Show the last segment of a path; the full one is in the title attribute. */
function shortPath(path: string): string {
  if (!path) return "";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/**
 * The reveal eye, opened or struck through.
 *
 * Shared by every key row, which are all asking the same question of the same
 * protocol method -- so they get the same glyph rather than several that drift.
 */
function EyeIcon({ slashed }: { slashed: boolean }) {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="2.6" />
      {slashed && <path d="M4 4l16 16" />}
    </svg>
  );
}

/**
 * The remove glyph for a key row.
 *
 * A bin rather than an x: the eye is already the other button on this line, and
 * an x between them reads as "close" on a row that has nothing to close.
 */
function TrashIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 7h16" />
      <path d="M9 7V5h6v2" />
      <path d="M6.5 7l1 13h9l1-13" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  );
}

/**
 * The remove glyph for one allowed program.
 *
 * An x rather than the bin the key rows carry: the eye is already the other
 * button a key row can hold, and an x between them would read as "close" on a
 * row that has nothing to close. Here the x is the only control on the line,
 * so there is nothing to confuse it with.
 */
function DropIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/**
 * Whether two program lists hold the same names.
 *
 * Order and case aside, because both are incidental to the rule: the match is
 * case-insensitive, and the list is drawn in the order it was written. This is
 * what decides whether "Restore defaults" is worth offering, and a second
 * button for a list that is already the default is a control that does nothing.
 */
function sameNames(left: string[], right: string[]): boolean {
  const fold = (list: string[]) => list.map((name) => name.toLowerCase()).sort();
  const a = fold(left);
  const b = fold(right);
  return a.length === b.length && a.every((name, index) => name === b[index]);
}

export function SettingsPanel({
  connected,
  busy,
  providers,
  provider,
  baseUrl,
  project,
  sandbox,
  trusted,
  permissionList,
  permission,
  reasoning,
  error,
  notice,
  petOpen,
  onPet,
  update,
  updateChecking,
  updateFetching,
  updateReady,
  onCheckUpdate,
  onDownloadUpdate,
  onInstallUpdate,
  onOpenReleases,
  onClose,
  onChooseFolder,
  onStartSandbox,
  onStopSandbox,
  onPermissionChange,
  onReasoningChange,
  onApplyEndpoint,
  onTrust,
  onSaveKey,
  onDeleteKey,
  onRevealKey,
  onActivateKey,
  onListKeys,
  onReadSettings,
  onSetSetting,
  onReadDiagnostics,
  onCopyDiagnostics,
  onOpenLogFolder,
  initialTab,
}: Props) {
  // The tab a directed open lands on -- sending with no provider opens Keys.
  // An initializer, not a sync: the page remounts on every open, so the prop
  // is fresh each time, and a later prop change must not yank the tab out
  // from under a user already reading another one.
  const [tab, setTab] = useState<SettingsTab>(initialTab ?? "permission");

  // Local mirror of the endpoint, so typing does not re-bind on every keystroke.
  const [draftBaseUrl, setDraftBaseUrl] = useState(baseUrl);

  // The rows, as the core last reported them.
  const [keys, setKeys] = useState<KeyEntry[]>([]);
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyNotice, setKeyNotice] = useState<string | null>(null);

  // The add-a-key fields, per provider. Held as maps rather than one pair so
  // two sections can be half-filled at once without the second clearing the
  // first -- the user did nothing to ask for that.
  const [draftNames, setDraftNames] = useState<Record<string, string>>({});
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({});
  // The add form: one button, one form, one provider at a time. The drafts
  // above stay keyed by provider, so switching the form's select mid-typing
  // keeps each provider's half-typed row rather than clearing it.
  const [addingKey, setAddingKey] = useState(false);
  const [addProvider, setAddProvider] = useState("");

  // The revealed row, and only one at a time: a list that can show every key at
  // once is a page of plaintext credentials. openKey remembers which value was
  // fetched, so a timer fires with the closure it was created in and hides
  // exactly the row it showed.
  const [openKey, setOpenKey] = useState<{ provider: string; name: string; value: string } | null>(
    null,
  );
  const rowTimer = useRef(0);

  // Everything `settings.get` answered, as the core last reported it. Null
  // means "not read", which is drawn differently from an empty list -- see
  // `onReadSettings`.
  const [settings, setSettings] = useState<CoreSettings | null>(null);
  const [settingBusy, setSettingBusy] = useState(false);
  // The two groups are on different tabs, so a failure belongs to one of them:
  // an error about a program name has no business appearing over the sandbox.
  const [commandsNotice, setCommandsNotice] = useState<string | null>(null);
  const [sandboxNotice, setSandboxNotice] = useState<string | null>(null);
  // The program name being typed. Held here rather than in the core: it is not
  // a setting until it is added, and a half-typed word is not a rule.
  const [draftProgram, setDraftProgram] = useState("");
  // The facts a bug report needs, as the core last reported them. Null means
  // "not read" -- see `onReadDiagnostics`.
  const [diagnostics, setDiagnostics] = useState<DiagnosticsInfo | null>(null);
  // "Copied." or the reason it is not on the clipboard. The card's only notice:
  // nothing here is written, so there is no failure that belongs anywhere else.
  const [diagnosticsNotice, setDiagnosticsNotice] = useState<string | null>(null);

  // Adopt whatever the core reports, but only when the panel is not mid-edit:
  // an incoming event must not silently discard a half-typed endpoint.
  useEffect(() => {
    if (busy) return;
    setDraftBaseUrl(baseUrl);
  }, [baseUrl, busy]);

  // A reveal outliving the panel is the one way a value could sit in a DOM
  // nobody is looking at.
  useEffect(
    () => () => {
      window.clearTimeout(rowTimer.current);
    },
    [],
  );

  // A revealed row belongs to the tab that opened it, so leaving the tab takes
  // the value with it rather than having it reappear on the way back.
  useEffect(() => {
    if (tab !== "keys") {
      window.clearTimeout(rowTimer.current);
      rowTimer.current = 0;
      setOpenKey(null);
    }
  }, [tab]);

  /**
   * Re-read the core's list.
   *
   * After every mutation rather than editing the local array: a row that
   * vanished because delete failed and one that vanished because delete worked
   * would look identical, and the next render from the core would bring the
   * failed one back under the user's cursor.
   */
  const refreshKeys = async () => {
    if (!connected) {
      setKeys([]);
      return;
    }
    try {
      const listed = await onListKeys();
      setKeys(listed);
    } catch {
      setKeyNotice("Could not read the stored keys.");
    }
  };

  useEffect(() => {
    // Only while the Keys tab is showing, and only when the connection
    // changes: opening Settings to flip a permission must not spend a round
    // trip on a list nobody is looking at, and re-running on every render
    // would be a request loop. Every mutation already refreshes what it did.
    if (tab !== "keys") return;
    void refreshKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, tab]);

  /** Re-read what the core says about both sections. */
  const refreshSettings = async () => {
    if (!connected) {
      setSettings(null);
      return;
    }
    setSettings(await onReadSettings());
  };

  useEffect(() => {
    // Behavior and Project are the two tabs that draw a section of this
    // payload, and Behavior is the tab the page opens on -- so this is one call
    // when Settings opens, one when Project is chosen, and nothing per render.
    if (tab !== "permission" && tab !== "project") return;
    void refreshSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, tab]);

  useEffect(() => {
    // Starting or stopping changes what `settings.get` reports as the runtime,
    // without changing a single value in the file -- so the Project tab reads
    // again when the sandbox's own status moves. Not while it is starting: the
    // local runtime is already up at that point and the card would announce
    // "running on this computer" over a sandbox that is on its way in. The
    // settle is what the dep catches.
    if (tab !== "project" || sandbox === "starting") return;
    void refreshSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sandbox]);

  /** Re-read the facts a bug report needs. */
  const refreshDiagnostics = async () => {
    if (!connected) {
      setDiagnostics(null);
      return;
    }
    setDiagnostics(await onReadDiagnostics());
  };

  useEffect(() => {
    // Only while the App tab is showing, for the reason the key list gives:
    // opening Settings to flip a permission must not spend a round trip on
    // facts nobody is looking at.
    if (tab !== "app") return;
    void refreshDiagnostics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, tab]);

  /**
   * Copy the card as text, and say whether it took.
   *
   * The text is built from what the core reported rather than from what the
   * rows show, for the reason `diagnosticsText` gives: one rendering, drawn
   * and pasted alike, so the issue gets exactly what the card says.
   */
  const copyDiagnostics = async () => {
    if (!diagnostics) return;
    setDiagnosticsNotice(null);
    const copied = await onCopyDiagnostics(diagnosticsText(diagnostics));
    setDiagnosticsNotice(copied ? "Copied." : "Could not copy to the clipboard.");
  };

  /**
   * Write one setting, then adopt whatever the core says.
   *
   * Re-read rather than patch local state, for the reason the key rows do: a
   * value that changed because the write worked and one that changed because it
   * failed look identical, and the next read would put the failed one back
   * under the user's cursor. It also means the rows always show what the core
   * normalised -- it trims, folds duplicates and refuses a name that could
   * never match -- rather than what was typed.
   *
   * `notice` is the setter of the group the message belongs to.
   */
  const write = async (
    key: string,
    value: unknown,
    notice: (text: string | null) => void,
  ): Promise<boolean> => {
    setSettingBusy(true);
    notice(null);
    const reason = await onSetSetting(key, value);
    if (reason === null) await refreshSettings();
    setSettingBusy(false);
    if (reason !== null) notice(reason);
    return reason === null;
  };

  /** Add the name in the field, then clear it if it took. */
  const addProgram = async () => {
    const name = draftProgram.trim();
    if (!name || !settings) return;
    if (
      await write(
        "tools.command_allowlist",
        [...settings.tools.command_allowlist, name],
        setCommandsNotice,
      )
    ) {
      setDraftProgram("");
    }
  };

  /** Put a revealed row away again. Only the value this control fetched. */
  const hideRow = () => {
    window.clearTimeout(rowTimer.current);
    rowTimer.current = 0;
    setOpenKey(null);
  };

  /** Show one stored key, or put it away. */
  const toggleRow = async (target: string, name: string) => {
    if (openKey?.provider === target && openKey.name === name) {
      hideRow();
      return;
    }
    hideRow();
    setKeyBusy(true);
    setKeyNotice(null);
    const value = await onRevealKey(target, name);
    setKeyBusy(false);
    if (!value) {
      setKeyNotice("No key is stored under " + name + ".");
      return;
    }
    setOpenKey({ provider: target, name, value });
    rowTimer.current = window.setTimeout(hideRow, REVEAL_MS);
  };

  /** Remove one stored key. */
  const removeRow = async (target: string, name: string) => {
    hideRow();
    setKeyBusy(true);
    setKeyNotice(null);
    const ok = await onDeleteKey(target, name);
    await refreshKeys();
    setKeyBusy(false);
    setKeyNotice(
      ok
        ? "Key removed for " + target + " (" + name + ")."
        : "Could not remove " + name + " for " + target + ".",
    );
  };

  /** Make one stored key the one a turn spends. */
  const activateRow = async (target: string, name: string) => {
    hideRow();
    setKeyBusy(true);
    setKeyNotice(null);
    const ok = await onActivateKey(target, name);
    await refreshKeys();
    setKeyBusy(false);
    setKeyNotice(
      ok
        ? name + " is now the active key for " + target + "."
        : "Could not activate " + name + ".",
    );
  };

  /** Store the key typed into the add form. Resolves whether it landed. */
  const saveDraft = async (target: string): Promise<boolean> => {
    const apiKey = (draftKeys[target] ?? "").trim();
    if (!apiKey) return false;
    const name = (draftNames[target] ?? "").trim();
    setKeyBusy(true);
    setKeyNotice(null);
    const ok = await onSaveKey(target, name, apiKey);
    // Clear the secret whatever the outcome. Leaving it in the DOM after the
    // save resolves is the thing this panel exists not to do.
    setDraftKeys((prev) => ({ ...prev, [target]: "" }));
    if (ok) setDraftNames((prev) => ({ ...prev, [target]: "" }));
    await refreshKeys();
    setKeyBusy(false);
    setKeyNotice(
      ok ? "Key saved to the system keyring." : "Could not save the key.",
    );
    return ok;
  };

  /** Open the add form on the sensible provider: this window's, when it takes
   * a key, else the first one that does. */
  const openAddForm = () => {
    const keyable = providers.filter((entry) => !entry.chat_only);
    setAddProvider(
      keyable.some((entry) => entry.name === provider)
        ? provider
        : (keyable[0]?.name ?? ""),
    );
    setKeyNotice(null);
    setAddingKey(true);
  };

  /** Put the add form away. The secret leaves the DOM with it, and the draft
   * is cleared too, so a cancelled key is not sitting in memory behind a
   * closed form. The name stays: it was never a secret. */
  const closeAddForm = () => {
    setDraftKeys((prev) => ({ ...prev, [addProvider]: "" }));
    setAddingKey(false);
  };

  const running = sandbox === "running";
  const starting = sandbox === "starting";
  const canStart = Boolean(project) && !running && !starting;

  /*
   * The Keys tab's shape: one stored list, one add form.
   *
   * A section per provider meant every provider drew its own add row whether
   * or not it had a key, so the tab was N copies of the same two fields with
   * N Save buttons. Now providers with rows share one list, providers with
   * none are simply absent from it, and there is one form that names its
   * provider up front.
   */
  const storedGroups = providers
    .map((entry) => ({
      provider: entry,
      rows: keys.filter((row) => row.provider === entry.name),
    }))
    .filter((group) => group.rows.length > 0);
  const keyableProviders = providers.filter((entry) => !entry.chat_only);
  const keylessNames = providers
    .filter((entry) => entry.chat_only)
    .map((entry) => prettifyModelName(entry.name));

  return (
    /*
      A page, not a dialog and not a pane.

      It has been both: a centred 500px `.modal`, and a 288px pane of the
      sidebar. The pane is what made the arrangement awkward -- four sections
      sharing a 252px tab row, where a fifth does not fit, and rows that had to
      stack because a provider, a model and Apply want 420px between them.

      Full-window, the shape is the one a settings page always takes: the
      sections down the left, the chosen one beside it with the width to lay its
      rows out in a line.
    */
    <div className="settings-page">
      <nav className="settings-nav" aria-labelledby="settings-title">
        {/*
          The way out, where the sidebar's own back control was: a back button
          and the page's name, which is the pair `.chatlist-subhead` draws one
          rung down. Settings is somewhere you enter and leave, so this is the
          control that leaves it.
        */}
        <div className="settings-nav-head">
          <button
            type="button"
            className="settings-back"
            onClick={onClose}
            title="Back to the chat"
            aria-label="Back to the chat"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <h2 id="settings-title">Settings</h2>
        </div>

        {/*
          The sections. A tablist still -- four of them, one showing -- but
          stacked rather than in a row. At 252px the row *was* the constraint the
          whole arrangement was built around; down a column the labels have the
          width they want, and a fifth would be one more row rather than a
          rearrangement.
        */}
        <div
          className="settings-tabs"
          role="tablist"
          aria-orientation="vertical"
          aria-label="Settings sections"
          data-tab={tab}
        >
          {SETTINGS_TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              className={"settings-tab" + (tab === entry.id ? " is-active" : "")}
              aria-selected={tab === entry.id}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </nav>

      {/*
        The one scrolling region on the page.

        The nav is a column of its own and does not move, and the back control is
        in it rather than on the floor, so this is the only thing that scrolls --
        which is what keeps the way out reachable on every section and at every
        window height. It used to be a sticky footer doing that job; a back
        button at the top does it without a second fixed band.

        It is a wrapper rather than four siblings because a scroll container has
        to be one node, and because the four sections must *share* it: a scroller
        per section would take the scroll position of the last one with it when
        the section changed.
      */}
      <div className="settings-body">
        {error && <p className="warn">{error}</p>}
        {notice && <p className="notice">{notice}</p>}
        {tab === "permission" && (
          <>
            {/*
              The ladder and its terms, side by side.

              The body caps every row at the reading measure, which left this
              page's right half blank. The ladder stays at the measure -- it
              is the control, and a control wider than a line of prose stops
              being one -- while the detail column takes the rest: the full
              terms of each rung, drawn from the same facts as the rows.
            */}
            <section className="settings-group settings-split">
              <div className="settings-split-main">
                <h3>Permission</h3>
                <p className="settings-note">
                  What the agent may do without asking. This is the ceiling the core
                  enforces on every tool call in this window, not a preference.
                </p>
                <PermissionMenu
                  list={permissionList}
                  value={permission}
                  busy={busy}
                  disabled={!connected}
                  onChange={onPermissionChange}
                />
              </div>
              <PermissionDetail list={permissionList} value={permission} />
            </section>

            {reasoning && reasoning.efforts.length > 0 && (
              <section className="settings-group">
                <h3>Thinking</h3>
                <p className="settings-note">
                  How hard the model should think. Applies from the next message; a
                  turn already in flight keeps the effort it started with.
                </p>
                <ThinkingMenu
                  info={reasoning}
                  busy={busy}
                  disabled={!connected}
                  onChange={onReasoningChange}
                />
              </section>
            )}

            {/*
              The programs the agent may run.

              On Behavior rather than on a tab of its own, because that is what
              this tab's own heading asks: the permission ladder is the ceiling
              on what a turn may do, and this is the list it is checked against
              underneath that ceiling. Full is the one rung that bypasses it, so
              the note says so -- a user who has just widened the ladder needs to
              know the list below stopped applying.

              The deny list is a read-out, not an editor. It is the handful of
              commands that destroy the machine rather than a set the app happens
              not to trust, and the core unions it with whatever the file adds --
              so a control here that could cut it would be offering to shorten a
              floor. See `effective_command_lists`.
            */}
            <section className="settings-group">
              <h3>Commands</h3>
              <p className="settings-note">
                The programs the agent may run. A command is matched against this
                list by name, and anything else is refused -- except at Full,
                which is the one level that runs outside it.
              </p>

              {settings && settings.tools.command_allowlist.length === 0 ? (
                <p className="settings-hint">
                  Nothing is allowed, so no command runs outside the list below.
                  Only Full will run one.
                </p>
              ) : (
                <ul className="settings-commands">
                  {(settings?.tools.command_allowlist ?? []).map((name) => (
                    <li key={name} className="settings-command">
                      <span className="settings-command-name">{name}</span>
                      <button
                        type="button"
                        className="settings-command-drop"
                        title={"Stop allowing " + name}
                        aria-label={"Stop allowing " + name}
                        disabled={!connected || settingBusy}
                        onClick={() =>
                          void write(
                            "tools.command_allowlist",
                            (settings?.tools.command_allowlist ?? []).filter(
                              (one) => one !== name,
                            ),
                            setCommandsNotice,
                          )
                        }
                      >
                        <DropIcon />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {/*
                Enter adds, as well as the button. The field holds one word, so
                a key that does the obvious thing costs nothing and saves the
                trip to the mouse -- the same pair the key rows' fields use.
              */}
              <div className="settings-row">
                <input
                  className="settings-input"
                  type="text"
                  value={draftProgram}
                  onChange={(e) => {
                    setDraftProgram(e.target.value);
                    setCommandsNotice(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void addProgram();
                    }
                  }}
                  placeholder="Add a program name"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  disabled={!connected || settingBusy}
                  aria-label="Add a program to the allow-list"
                />
                <button
                  type="button"
                  className="btn"
                  disabled={!connected || settingBusy || !draftProgram.trim()}
                  onClick={() => void addProgram()}
                >
                  Add
                </button>
              </div>

              {settings && !sameNames(
                settings.tools.command_allowlist,
                settings.tools.command_allowlist_defaults,
              ) && (
                <div className="settings-row">
                  <button
                    type="button"
                    className="btn"
                    disabled={!connected || settingBusy}
                    onClick={() =>
                      void write("tools.command_allowlist", null, setCommandsNotice)
                    }
                  >
                    Restore defaults
                  </button>
                </div>
              )}

              {commandsNotice && <p className="settings-hint">{commandsNotice}</p>}

              <details className="settings-notes">
                <summary>
                  {settings
                    ? settings.tools.command_denylist.length +
                      " commands are always refused"
                    : "Commands that are always refused"}
                </summary>
                <p className="settings-note">
                  Patterns matched against the whole command and checked before
                  the allow-list, so they hold at every permission level. This
                  list belongs to the core and cannot be shortened from here.
                </p>
                <ul className="settings-denylist">
                  {(settings?.tools.command_denylist ?? []).map((pattern) => (
                    <li key={pattern}>
                      <code>{pattern}</code>
                    </li>
                  ))}
                </ul>
              </details>
            </section>
          </>
        )}

        {tab === "project" && (
          <>
            <section className="settings-group">
              <h3>Project folder</h3>
              <p className="settings-note">
                The sandbox runs the agent against one directory. Tools are refused
                outside it -- except at Full, which runs commands on this computer
                instead of in here.
              </p>
              <div className="settings-row">
                <span className="settings-value" title={project || undefined}>
                  {project ? shortPath(project) : "none selected"}
                </span>
                <button
                  type="button"
                  className="btn"
                  onClick={onChooseFolder}
                  disabled={!connected || busy}
                >
                  {project ? "Change..." : "Choose folder..."}
                </button>
                {canStart && (
                  <button
                    type="button"
                    className="btn"
                    onClick={onStartSandbox}
                    disabled={!connected || busy}
                  >
                    Start
                  </button>
                )}
                {starting && (
                  <button type="button" className="btn" disabled>
                    Starting...
                  </button>
                )}
                {running && (
                  <button
                    type="button"
                    className="btn"
                    onClick={onStopSandbox}
                    disabled={!connected || busy}
                  >
                    Stop
                  </button>
                )}
              </div>

              {project && (
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={trusted}
                    onChange={(e) => onTrust(project, e.target.checked)}
                    disabled={!connected}
                  />
                  <span>
                    Trust this folder
                    <em>
                      Skips the per-command confirmation prompt for shell tools
                      inside it.
                    </em>
                  </span>
                </label>
              )}
            </section>

            {/*
              Where the agent's code actually runs.

              **The identity comes first and the controls second**, because the
              question this card answers is "what am I running in". The
              configured type is `auto` on most machines and says nothing about
              what it resolved to, so the sentence above the fields reports the
              *runtime* and the select below reports the choice.

              The five fields are the ones a person changes on purpose. The rest
              of the `[sandbox]` table -- pids, capabilities, ulimits -- is the
              containment the backend guarantees: a page that could loosen it
              would be a page that can turn the sandbox off one switch at a
              time. See `_EDITABLE_SETTINGS`.

              Every field here is read at `sandbox.start`, so a change applies
              to the next start rather than to the one already running. That is
              said once at the foot of the group rather than repeated under each
              control.
            */}
            <section className="settings-group">
              <h3>Sandbox</h3>
              <p className="settings-value">
                {sandboxIdentity(settings?.sandbox.runtime ?? null)}
              </p>
              <p className="settings-note">
                {sandboxMeaning(settings?.sandbox.runtime ?? null)}
              </p>

              <label className="settings-field">
                <span className="settings-field-name">Backend</span>
                <span className="settings-select-wrap">
                  <select
                    className="settings-select"
                    value={settings?.sandbox.type ?? ""}
                    disabled={!connected || settingBusy || !settings}
                    onChange={(e) =>
                      void write("sandbox.type", e.target.value, setSandboxNotice)
                    }
                  >
                    {SANDBOX_BACKENDS.map((entry) => (
                      <option key={entry.id} value={entry.id}>
                        {entry.label}
                      </option>
                    ))}
                    {/*
                      A value the list does not offer -- `windows`, which is in
                      the settings model and is a documented stub. Drawn rather
                      than silently shown as Automatic, which would be this page
                      reporting a backend the core is not configured for.
                    */}
                    {settings &&
                      !SANDBOX_BACKENDS.some(
                        (entry) => entry.id === settings.sandbox.type,
                      ) && (
                        <option value={settings.sandbox.type}>
                          {settings.sandbox.type === "windows"
                            ? "Windows Sandbox (not available)"
                            : settings.sandbox.type}
                        </option>
                      )}
                  </select>
                </span>
              </label>
              <p className="settings-hint">
                Automatic prefers Docker, then WSL, and falls back to running on
                this computer.
              </p>

              {/*
                A text field rather than a list of installed distros. Listing
                them means running `wsl.exe` inside the request the page makes
                every time it opens, so a wedged WSL would wedge Settings
                instead of one start -- see `_clean_distro`. Empty is the
                default distro, which is what this machine already uses.
              */}
              <label className="settings-field">
                <span className="settings-field-name">WSL distro</span>
                <input
                  className="settings-input"
                  type="text"
                  key={settings?.sandbox.wsl_distro ?? ""}
                  defaultValue={settings?.sandbox.wsl_distro ?? ""}
                  placeholder={
                    settings?.sandbox.defaults.wsl_distro || "Default distro"
                  }
                  disabled={!connected || settingBusy || !settings}
                  spellCheck={false}
                  autoComplete="off"
                  onChange={() => setSandboxNotice(null)}
                  onBlur={(e) =>
                    void write(
                      "sandbox.wsl_distro",
                      e.currentTarget.value.trim() || null,
                      setSandboxNotice,
                    )
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                  }}
                  aria-label="WSL distro"
                />
              </label>
              <p className="settings-hint">
                Only used by the WSL backend. Leave it empty to use the default
                distro.
              </p>

              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={settings?.sandbox.enable_network ?? false}
                  disabled={!connected || settingBusy || !settings}
                  onChange={(e) =>
                    void write(
                      "sandbox.enable_network",
                      e.target.checked,
                      setSandboxNotice,
                    )
                  }
                />
                <span>
                  Allow network access
                  <em>
                    Docker and WSL start with the network off. The browser tools
                    need it on; a shell command does not.
                  </em>
                </span>
              </label>

              {/*
                Docker's two resource caps, behind a disclosure because they are
                the only fields here that a WSL machine ignores entirely. Kept
                visible rather than hidden: a Docker user needs them, and a note
                that says which backend reads them is more honest than a control
                that appears and disappears with the backend above.
              */}
              <details className="settings-notes">
                <summary>Docker limits</summary>
                <p className="settings-note">
                  Only used when the backend is Docker. Leave a field empty for
                  the default.
                </p>
                <label className="settings-field">
                  <span className="settings-field-name">Memory</span>
                  <input
                    className="settings-input"
                    type="text"
                    key={settings?.sandbox.memory_limit ?? ""}
                    defaultValue={settings?.sandbox.memory_limit ?? ""}
                    placeholder={settings?.sandbox.defaults.memory_limit || "2g"}
                    disabled={!connected || settingBusy || !settings}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={() => setSandboxNotice(null)}
                    onBlur={(e) =>
                      void write(
                        "sandbox.memory_limit",
                        e.currentTarget.value.trim() || null,
                        setSandboxNotice,
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                    aria-label="Container memory limit"
                  />
                </label>
                <label className="settings-field">
                  <span className="settings-field-name">CPU</span>
                  <input
                    className="settings-input"
                    type="text"
                    key={settings?.sandbox.cpu_limit ?? ""}
                    defaultValue={settings?.sandbox.cpu_limit ?? ""}
                    placeholder={settings?.sandbox.defaults.cpu_limit || "2.0"}
                    disabled={!connected || settingBusy || !settings}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={() => setSandboxNotice(null)}
                    onBlur={(e) =>
                      void write(
                        "sandbox.cpu_limit",
                        e.currentTarget.value.trim() || null,
                        setSandboxNotice,
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                    aria-label="Container CPU limit"
                  />
                </label>
              </details>

              {sandboxNotice && <p className="settings-hint">{sandboxNotice}</p>}

              <p className="settings-hint">
                Changes apply the next time the sandbox starts.
              </p>
            </section>
          </>
        )}

        {tab === "keys" && (
          <>
            {providers.length === 0 && (
              <p className="settings-hint">No providers are registered.</p>
            )}

            {providers.length > 0 && (
              <section className="settings-group">
                <h3>Stored keys</h3>
                <p className="settings-note">
                  Keys stored for each provider. The one marked Active is the
                  key a turn spends; the others are kept but not used.
                </p>
                {keys.length === 0 && (
                  <p className="settings-hint">No API keys stored yet.</p>
                )}
                {storedGroups.map(({ provider: entry, rows }) => (
                  <div className="settings-key-group" key={entry.name}>
                    {/*
                      Words, with the id one hover away: `opencode-go` reads
                      `OpenCode Go`, and the tooltip keeps the address the keys
                      are stored under.
                    */}
                    <p className="settings-key-provider" title={entry.name}>
                      {prettifyModelName(entry.name)}
                    </p>
                    <ul className="settings-keys">
                      {rows.map((row) => {
                        const open =
                          openKey?.provider === entry.name && openKey.name === row.name
                            ? openKey.value
                            : null;
                        return (
                          <li key={row.name} className="settings-key-item">
                            <div className="settings-key-line">
                              <span className="settings-key-name" title={row.name}>
                                {row.name}
                              </span>
                              {row.active ? (
                                <span
                                  className="settings-key-flag"
                                  title={"Turns use this key"}
                                >
                                  Active
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  className="settings-key-use"
                                  title={"Use " + row.name + " for " + entry.name}
                                  aria-label={"Use the " + row.name + " key for " + entry.name}
                                  disabled={!connected || keyBusy}
                                  onClick={() => void activateRow(entry.name, row.name)}
                                >
                                  Use
                                </button>
                              )}
                              <button
                                type="button"
                                className="settings-reveal"
                                title={open ? "Hide this key" : "Show this key"}
                                aria-label={
                                  (open ? "Hide" : "Show") +
                                  " the " +
                                  row.name +
                                  " key for " +
                                  entry.name
                                }
                                aria-pressed={open !== null}
                                disabled={!connected || keyBusy}
                                onClick={() => void toggleRow(entry.name, row.name)}
                              >
                                <EyeIcon slashed={open !== null} />
                              </button>
                              <button
                                type="button"
                                className="settings-unkey"
                                title={"Remove the " + row.name + " key for " + entry.name}
                                aria-label={"Remove the " + row.name + " key for " + entry.name}
                                disabled={!connected || keyBusy}
                                onClick={() => void removeRow(entry.name, row.name)}
                              >
                                <TrashIcon />
                              </button>
                            </div>
                            {open && (
                              <code className="settings-key-value">{open}</code>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
                {keylessNames.length > 0 && (
                  <p className="settings-note">
                    {keylessNames.join(", ")} {keylessNames.length === 1 ? "works" : "work"} in
                    Chat mode only, and {keylessNames.length === 1 ? "needs" : "need"} no
                    API key -- the server runs on this machine.
                  </p>
                )}
              </section>
            )}

            {keyableProviders.length > 0 && (
              <section className="settings-group">
                <h3>Add a key</h3>
                {/*
                  One form for every provider. Provider first, because the two
                  fields below are labelled with it; name above key above
                  buttons, because two fields plus two buttons on one line is
                  four controls fighting over it.
                */}
                {!addingKey ? (
                  <button
                    type="button"
                    className="btn"
                    disabled={!connected || keyBusy}
                    onClick={openAddForm}
                  >
                    Add new API key
                  </button>
                ) : (
                  <div className="settings-key settings-key-new">
                    <div className="settings-row">
                      <span className="settings-select-wrap">
                        <select
                          className="settings-select"
                          value={addProvider}
                          disabled={!connected || keyBusy}
                          onChange={(e) => {
                            setAddProvider(e.target.value);
                            setKeyNotice(null);
                          }}
                          aria-label="Provider for the new key"
                        >
                          {keyableProviders.map((option) => (
                            <option key={option.name} value={option.name}>
                              {prettifyModelName(option.name)}
                            </option>
                          ))}
                        </select>
                      </span>
                    </div>
                    <div className="settings-row">
                      <input
                        className="settings-input"
                        type="text"
                        value={draftNames[addProvider] ?? ""}
                        onChange={(e) => {
                          const value = e.target.value;
                          setDraftNames((prev) => ({ ...prev, [addProvider]: value }));
                          setKeyNotice(null);
                        }}
                        placeholder="Name (optional)"
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        disabled={!connected || keyBusy}
                        aria-label={"Name for a new " + addProvider + " key"}
                      />
                    </div>
                    <div className="settings-row">
                      <input
                        className="settings-input"
                        type="password"
                        value={draftKeys[addProvider] ?? ""}
                        onChange={(e) => {
                          const value = e.target.value;
                          setDraftKeys((prev) => ({ ...prev, [addProvider]: value }));
                          setKeyNotice(null);
                        }}
                        placeholder={"API key for " + addProvider}
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        disabled={!connected || keyBusy}
                        aria-label={"New API key for " + addProvider}
                      />
                    </div>
                    <div className="settings-row settings-key-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={
                          !connected ||
                          keyBusy ||
                          !addProvider ||
                          !(draftKeys[addProvider] ?? "").trim()
                        }
                        onClick={() =>
                          void saveDraft(addProvider).then((ok) => {
                            if (ok) setAddingKey(false);
                          })
                        }
                      >
                        {keyBusy ? "Saving..." : "Save key"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-quiet"
                        disabled={keyBusy}
                        onClick={closeAddForm}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </section>
            )}

            {keyNotice && <p className="settings-hint">{keyNotice}</p>}
            <p className="settings-hint">
              Stored by the OS credential manager, never in a config file. Nothing
              here is shown until you ask for it.
            </p>

            {/*
              The endpoint, kept where it always was. It is not a model setting:
              it is how a local Ollama or a proxy is reached, and no other surface
              in this window can set it.
            */}
            <section className="settings-group">
              <h3>Base URL</h3>
              <p className="settings-note">
                Only needed for a non-standard endpoint, such as a local
                Ollama/LM Studio server or an OpenAI-compatible proxy. Applies to
                the provider this window has bound.
              </p>
              <div className="settings-row">
                <input
                  className="settings-input"
                  type="text"
                  value={draftBaseUrl}
                  onChange={(e) => setDraftBaseUrl(e.target.value)}
                  disabled={!connected || busy || !provider}
                  placeholder="https://... (optional)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  aria-label="Base URL"
                />
                <button
                  type="button"
                  className="btn"
                  onClick={() => onApplyEndpoint(draftBaseUrl.trim())}
                  disabled={!connected || busy || !provider}
                >
                  Set endpoint
                </button>
              </div>
              <p className="settings-hint">
                Include the scheme (https:// or http://), or leave it empty to use
                the provider's own default.
              </p>
            </section>
          </>
        )}

        {tab === "app" && (
          <>
            <section className="settings-group">
              <h3>Desktop pet</h3>
              <p className="settings-note">
                A small card in the corner of the screen that says what the agent
                is doing, and whether it needs you. It never takes the keyboard, so
                a status update cannot pull your typing out of another window.
              </p>
              {/*
                A checkbox rather than a switch, and it is the panel's only one
                that is not a permission: it changes nothing about the agent.

                Enabled while `connected` is false, unlike every control around
                it. The card is a *window* -- the shell makes it without a core,
                and one that says "waiting" beside a stopped core is telling the
                truth. Disabling it would be refusing to do a job this window can
                do.
              */}
              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={petOpen}
                  onChange={onPet}
                />
                <span>
                  Show the card
                  <em>
                    Drag it anywhere on the screen; press it to bring this window
                    forward. The rail's pet button does the same thing.
                  </em>
                </span>
              </label>
            </section>

            <section className="settings-group">
              <h3>Version</h3>
              <p className="settings-note">
                This window is TONYAgent {update?.current || "\u2026"}.
              </p>
              {/*
                The status line is the answer, whatever it is. It is never
                hidden behind a spinner: a check that failed has something to
                say, and a check that succeeded has something else. See
                `updateMessage` for why none of the failures say "up to date".
              */}
              <p className="settings-value">{updateMessage(update)}</p>
              {update?.available && update.notes && (
                <details className="settings-notes">
                  <summary>Release notes</summary>
                  <pre>{update.notes}</pre>
                </details>
              )}
              {/*
                **The install half is this card's, not a card of its own.**

                It was a second `settings-group` headed Install, and the heading
                was the problem: "which version am I running" and "do I want the
                new one" are one question read twice, so two cards meant two
                headings for one answer -- and the second card only existed while
                an update did, which is exactly when the first is being read.

                So the download and the install sit under the version they belong
                to, in the order they happen: what this is, what is available,
                what was fetched, and the one press that runs it. The check row
                stays last, because it is the pair of tools for looking again and
                it is on this card whether or not there is anything to install.

                The *reporting* is still split even though the presses are not. A
                fetch fails for its own reasons (offline, a digest that did not
                match) and an install is refused for others (this is a source
                checkout, or there is no installer yet), and the two say
                different things. That is also why the download button survives
                as a plain control: it is a retry as often as a first attempt.

                A release with no `.msi` attached is answered before the button is
                drawn rather than after the fetch fails: the check already knows,
                and offering a control that cannot work is the thing this panel
                avoids everywhere else.
              */}
              {update?.available &&
                (!update.asset ? (
                  <p className="settings-value">
                    That release has no installer attached, so there is nothing
                    to download. Use "Release notes" to see the release itself.
                  </p>
                ) : updateReady?.ok ? (
                  <>
                    <p className="settings-note">
                      {updateReady.name} is downloaded and verified against the
                      digest GitHub published for the release.
                    </p>
                    <p className="settings-note">
                      Installing closes TONYAgent and starts the Windows
                      installer, which will ask for permission.
                    </p>
                    <div className="settings-row">
                      <button type="button" className="btn btn-accent" onClick={onInstallUpdate}>
                        Install and restart
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="settings-note">
                      {updateFetching
                        ? "Fetching the installer now that a newer version is known."
                        : "The installer is fetched from the release as soon as a newer version is known, and checked against its published SHA-256 before anything runs it."}
                    </p>
                    {updateReady && !updateReady.ok && (
                      <p className="settings-value">
                        {updateReady.reason === "no_digest"
                          ? "That release carries no SHA-256 digest, so it will not be downloaded."
                          : updateReady.reason === "offline"
                            ? "The download could not be completed. Check your connection."
                            : updateReady.reason === "digest"
                              ? "The downloaded file did not match its published digest, so it was deleted."
                              : "There is no installer attached to that release yet."}
                      </p>
                    )}
                    <div className="settings-row">
                      <button
                        type="button"
                        className="btn"
                        onClick={onDownloadUpdate}
                        disabled={updateFetching || updateChecking || !connected}
                      >
                        {updateFetching ? "Downloading\u2026" : "Download the installer"}
                      </button>
                    </div>
                  </>
                ))}
              <div className="settings-row">
                <button
                  type="button"
                  className="btn"
                  onClick={() => onCheckUpdate(true)}
                  disabled={updateChecking || !connected}
                >
                  {updateChecking ? "Checking\u2026" : "Check for updates"}
                </button>
                <button type="button" className="btn" onClick={onOpenReleases}>
                  Release notes
                </button>
              </div>
            </section>

            {/*
              What a bug report needs, in one place.

              **Beside the version rather than in a tab of its own.** "Which
              build am I running" and "where does it keep its files" are one
              question read twice -- the version card names the number, and this
              one names where it runs from and where to look when it misbehaves.
              A tab of its own would be a fifth label in a row that already
              renamed one to fit four.

              The facts come from `diagnostics.get` rather than from constants
              here: the config path depends on the platform and on which APPDATA
              the core sees, and a path this window guessed at is how a user ends
              up looking for logs in a folder that was never written to. "Not
              read yet" is drawn instead of empty facts for the reason the other
              reads give: a missing log folder and a missing answer are different
              claims.
            */}
            <section className="settings-group">
              <h3>Diagnostics</h3>
              <p className="settings-note">
                The build, where it runs from, and where its files live -- copied
                as text, so it can be pasted straight into an issue.
              </p>
              {diagnostics ? (
                <>
                  <p className="settings-value">
                    TONYAgent {diagnostics.version} by {diagnostics.author}
                  </p>
                  <p className="settings-value">{diagnosticsRuntime(diagnostics)}</p>
                  <div className="settings-row">
                    <span className="settings-value" title={diagnostics.config_path}>
                      Config: {diagnostics.config_path}
                    </span>
                  </div>
                  <div className="settings-row">
                    <span className="settings-value" title={diagnostics.log_dir}>
                      Logs: {diagnostics.log_dir}
                    </span>
                  </div>
                </>
              ) : (
                <p className="settings-value">Not read yet.</p>
              )}
              <div className="settings-row">
                <button
                  type="button"
                  className="btn"
                  onClick={onOpenLogFolder}
                  disabled={!connected || !diagnostics}
                >
                  Open log folder
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => void copyDiagnostics()}
                  disabled={!connected || !diagnostics}
                >
                  Copy diagnostics
                </button>
              </div>
              {diagnosticsNotice && (
                <p className="settings-hint">{diagnosticsNotice}</p>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
