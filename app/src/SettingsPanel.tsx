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
  PermissionMenu,
  ThinkingMenu,
  type PermissionList,
  type ReasoningInfo,
} from "./SettingsMenus.js";

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
}

/** One stored key, as key.list reports it. Never carries a value. */
export interface KeyEntry {
  provider: string;
  name: string;
  active: boolean;
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
}: Props) {
  const [tab, setTab] = useState<SettingsTab>("permission");

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

  // The revealed row, and only one at a time: a list that can show every key at
  // once is a page of plaintext credentials. openKey remembers which value was
  // fetched, so a timer fires with the closure it was created in and hides
  // exactly the row it showed.
  const [openKey, setOpenKey] = useState<{ provider: string; name: string; value: string } | null>(
    null,
  );
  const rowTimer = useRef(0);

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

  /** Store the key typed into one provider's add row. */
  const saveDraft = async (target: string) => {
    const apiKey = (draftKeys[target] ?? "").trim();
    if (!apiKey) return;
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
  };

  const running = sandbox === "running";
  const starting = sandbox === "starting";
  const canStart = Boolean(project) && !running && !starting;

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
            <section className="settings-group">
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
          </>
        )}

        {tab === "keys" && (
          <>
            {providers.length === 0 && (
              <p className="settings-hint">No providers are registered.</p>
            )}

            {providers.map((entry) => {
              const rows = keys.filter((row) => row.provider === entry.name);
              return (
                <section className="settings-group" key={entry.name}>
                  <h3>{entry.name}</h3>
                  <p className="settings-note">
                    Keys stored for this provider. The one marked Active is the key
                    a turn spends; the others are kept but not used.
                  </p>

                  {rows.length === 0 ? (
                    <p className="settings-hint">No keys stored for this provider yet.</p>
                  ) : (
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
                  )}

                  {/*
                    The add row. Name above key above button, because the sidebar
                    gives this column 241px and two fields plus a button on one
                    line is three controls fighting over it.
                  */}
                  <div className="settings-key settings-key-new">
                    <div className="settings-row">
                      <input
                        className="settings-input"
                        type="text"
                        value={draftNames[entry.name] ?? ""}
                        onChange={(e) => {
                          const value = e.target.value;
                          setDraftNames((prev) => ({ ...prev, [entry.name]: value }));
                          setKeyNotice(null);
                        }}
                        placeholder="Name (optional)"
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        disabled={!connected || keyBusy}
                        aria-label={"Name for a new " + entry.name + " key"}
                      />
                    </div>
                    <div className="settings-row">
                      <input
                        className="settings-input"
                        type="password"
                        value={draftKeys[entry.name] ?? ""}
                        onChange={(e) => {
                          const value = e.target.value;
                          setDraftKeys((prev) => ({ ...prev, [entry.name]: value }));
                          setKeyNotice(null);
                        }}
                        placeholder={"API key for " + entry.name}
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        disabled={!connected || keyBusy}
                        aria-label={"New API key for " + entry.name}
                      />
                    </div>
                    <div className="settings-row settings-key-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={
                          !connected || keyBusy || !(draftKeys[entry.name] ?? "").trim()
                        }
                        onClick={() => void saveDraft(entry.name)}
                      >
                        {keyBusy ? "Saving..." : "Save key"}
                      </button>
                    </div>
                  </div>
                </section>
              );
            })}

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
          </>
        )}
      </div>
    </div>
  );
}
