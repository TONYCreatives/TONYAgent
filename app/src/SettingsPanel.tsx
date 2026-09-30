/**
 * Settings panel.
 *
 * One modal for the two things the rail can now actually change, rather than
 * two separate surfaces: the project folder and the provider both answer "what
 * is this window working on", and splitting them would mean two modals to style
 * and two ways to reach the same core methods.
 *
 * Every control here maps to a protocol method that already exists. The panel
 * deliberately contains nothing that is presentation-only -- a control the
 * core cannot honour is the failure mode this project keeps running into (see
 * the mode pills in Composer, which are still presentation-only on purpose).
 *
 * The API key field is the one place a secret is typed into this app. Two
 * rules follow from that, and both are load-bearing rather than stylistic:
 * the input is uncontrolled-then-cleared so the value lives in the DOM for the
 * shortest possible time, and the panel reports only success or failure --
 * there is no way here to read a stored key back, because the protocol has no
 * method that returns one.
 */

import { useEffect, useState } from "react";

/** Shape of one entry in the `providers.list` reply. */
export interface ProviderInfo {
  name: string;
  models: string[];
  has_credentials: boolean;
}

interface Props {
  connected: boolean;
  busy: boolean;
  providers: ProviderInfo[];
  provider: string;
  model: string;
  /**
   * The endpoint override last bound, or "" for the provider default.
   *
   * Held by the window rather than the core because the reply to
   * `bind_provider` echoes only what was requested; the core never claims a
   * default the provider chooses for itself.
   */
  baseUrl: string;
  project: string;
  sandbox: string;
  /**
   * Whether the core currently trusts `project`.
   *
   * Passed in rather than read here because the protocol has no `trust.get`:
   * the orchestrator keeps the set in memory, and the only way a frontend can
   * learn the answer is to remember what it asked for. Inventing a getter
   * would mean the panel could disagree with the core.
   */
  trusted: boolean;
  /** Non-null while a call is in flight, so the panel can show what failed. */
  error: string | null;
  /**
   * Degraded-but-working, e.g. a project folder attached without an isolated
   * sandbox. Kept apart from `error` because nothing here needs fixing, and an
   * error style would imply otherwise.
   */
  notice: string | null;
  onClose: () => void;
  onChooseFolder: () => void;
  onStopSandbox: () => void;
  onBindProvider: (name: string, model: string, baseUrl: string) => void;
  onTrust: (project: string, trusted: boolean) => void;
  onSaveKey: (provider: string, apiKey: string) => Promise<boolean>;
  onDeleteKey: (provider: string) => Promise<boolean>;
}

/** Show the last segment of a path; the full one is in the title attribute. */
function shortPath(path: string): string {
  if (!path) return "";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export function SettingsPanel({
  connected,
  busy,
  providers,
  provider,
  model,
  baseUrl,
  project,
  sandbox,
  trusted,
  error,
  notice,
  onClose,
  onChooseFolder,
  onStopSandbox,
  onBindProvider,
  onTrust,
  onSaveKey,
  onDeleteKey,
}: Props) {
  // Local mirror of the provider selection, so changing the provider does not
  // immediately re-bind: the user picks a provider, then a model, then
  // confirms. Two round trips per keystroke would be its own bug.
  const [draftProvider, setDraftProvider] = useState(provider);
  const [draftModel, setDraftModel] = useState(model);
  const [draftBaseUrl, setDraftBaseUrl] = useState(baseUrl);

  // The key being typed. Held in state so the Save button can enable on a
  // non-empty value, and cleared the instant the save resolves -- a field that
  // keeps a credential sitting in the DOM after it is stored is a field that
  // ends up in a screenshot or a support bundle.
  const [apiKey, setApiKey] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyNotice, setKeyNotice] = useState<string | null>(null);

  // Adopt whatever the core reports, but only when the panel is not mid-edit:
  // an incoming event must not silently discard a half-made selection.
  useEffect(() => {
    if (busy) return;
    setDraftProvider(provider);
    setDraftModel(model);
    setDraftBaseUrl(baseUrl);
  }, [provider, model, baseUrl, busy]);

  const running = sandbox === "running";
  // Only used to populate the suggestion list. The model field is a free-text
  // input, not a select: a provider's `models` is a handful of illustrative
  // ids, and OpenRouter alone serves hundreds more than fit in a dropdown.
  const models =
    providers.find((p) => p.name === draftProvider)?.models ?? [];

  // Switching provider invalidates the model and the endpoint, since both are
  // provider-specific: "gpt-4o" means nothing to Anthropic, and one gateway's
  // base URL is meaningless to another.
  const onProviderChange = (name: string) => {
    setDraftProvider(name);
    setDraftModel("");
    setDraftBaseUrl("");
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
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

        <section className="settings-group">
          <h3>Project folder</h3>
          <p className="settings-note">
            The sandbox runs the agent against one directory. Tools are refused
            outside it.
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

        <section className="settings-group">
          <h3>Model</h3>
          <p className="settings-note">
            The model list is a set of suggestions, not a closed set. Type any
            model id -- OpenRouter namespaces its models ("anthropic/
            claude-sonnet-4.5", "deepseek/deepseek-chat:free") and a self-hosted
            gateway uses ids the core has never heard of. Leave it empty to use
            the provider default.
          </p>
          <div className="settings-row">
            <select
              className="settings-select"
              value={draftProvider}
              onChange={(e) => onProviderChange(e.target.value)}
              disabled={!connected || busy}
              aria-label="Provider"
            >
              {providers.length === 0 && <option value="">no providers</option>}
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                  {p.has_credentials ? "" : " (no key)"}
                </option>
              ))}
            </select>
            {/*
              A plain text input with a `<datalist>`, not a `<select>`: the
              native combobox suggests the provider's known ids while still
              accepting anything the user types. `datalist` renders no markup of
              its own and needs no dependency, which keeps this panel's only
              interactive machinery the browser's.
            */}
            <input
              className="settings-input"
              type="text"
              list="model-suggestions"
              value={draftModel}
              onChange={(e) => setDraftModel(e.target.value)}
              disabled={!connected || busy}
              placeholder="default"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              aria-label="Model"
            />
            <datalist id="model-suggestions">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <button
              type="button"
              className="btn btn-accent"
              onClick={() =>
                onBindProvider(
                  draftProvider,
                  draftModel.trim(),
                  draftBaseUrl.trim(),
                )
              }
              disabled={!connected || busy || !draftProvider}
            >
              Apply
            </button>
          </div>

          {/*
            An optional endpoint override. Empty means "use the provider's own
            default", which is OpenRouter's API.
          */}
          <div className="settings-row">
            <input
              className="settings-input"
              type="text"
              value={draftBaseUrl}
              onChange={(e) => setDraftBaseUrl(e.target.value)}
              disabled={!connected || busy}
              placeholder="Base URL -- optional, must start with https://"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              aria-label="Base URL"
            />
          </div>
          <p className="settings-hint">
            Base URL is only needed for a non-standard endpoint, such as a local
            Ollama/LM Studio server or an OpenAI-compatible proxy. Include the
            scheme (<code>https://</code> or <code>http://</code>) -- a bare
            host is rejected with an explicit error rather than failing as a
            confusing network problem later.
          </p>

          {/*
            The key field. `type="password"` with the manager's reveal toggle
            off, and the value is cleared as soon as the save resolves --
            success or failure. There is deliberately no "show stored key":
            the protocol has no method that returns one, and adding one would
            put a live credential one screenshot away.
          */}
          <div className="settings-key">
            <div className="settings-row">
              <input
                className="settings-input"
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setKeyNotice(null);
                }}
                placeholder={`API key for ${draftProvider || "provider"}`}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                disabled={!connected || keyBusy || !draftProvider}
                aria-label={`API key for ${draftProvider}`}
              />
              <button
                type="button"
                className="btn"
                disabled={!connected || keyBusy || !draftProvider || !apiKey.trim()}
                onClick={async () => {
                  setKeyBusy(true);
                  setKeyNotice(null);
                  const ok = await onSaveKey(draftProvider, apiKey);
                  // Clear unconditionally. On failure the value is still in
                  // the DOM, which is no better than on success.
                  setApiKey("");
                  setKeyBusy(false);
                  setKeyNotice(ok ? "Key saved to the system keyring." : "Could not save the key.");
                }}
              >
                {keyBusy ? "Saving..." : "Save key"}
              </button>
              {providers.find((p) => p.name === draftProvider)?.has_credentials && (
                <button
                  type="button"
                  className="btn"
                  disabled={!connected || keyBusy}
                  onClick={async () => {
                    setKeyBusy(true);
                    const ok = await onDeleteKey(draftProvider);
                    setKeyBusy(false);
                    setKeyNotice(ok ? "Key removed." : "Could not remove the key.");
                  }}
                >
                  Remove
                </button>
              )}
            </div>
            {keyNotice && <p className="settings-hint">{keyNotice}</p>}
            <p className="settings-hint">
              Stored by the OS credential manager, never in a config file. It
              cannot be displayed again after saving.
            </p>
          </div>
        </section>

        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
