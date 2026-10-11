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

/** Shape of one entry in the providers.list reply. */
export interface ProviderInfo {
  name: string;
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
 * Three, because there are three questions in here and they get asked at
 * different times: what may this window do, what is it working on, and what is
 * it talking to. The third tab is Keys rather than Model now that the model
 * pickers are gone -- the credential is the only thing left on it.
 */
const SETTINGS_TABS = [
  { id: "permission", label: "Permission" },
  { id: "project", label: "Project" },
  { id: "keys", label: "Keys" },
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
    <div
      className="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      onClick={(e) => e.stopPropagation()}
    >
      <h2 id="settings-title">Settings</h2>

      {error && <p className="warn">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <div
        className="settings-tabs"
        role="tablist"
        aria-label="Settings"
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

      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
