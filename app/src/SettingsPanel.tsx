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
  onClose: () => void;
  onChooseFolder: () => void;
  onStopSandbox: () => void;
  onBindProvider: (name: string, model: string) => void;
  onTrust: (project: string, trusted: boolean) => void;
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
  project,
  sandbox,
  trusted,
  error,
  onClose,
  onChooseFolder,
  onStopSandbox,
  onBindProvider,
  onTrust,
}: Props) {
  // Local mirror of the provider selection, so changing the provider does not
  // immediately re-bind: the user picks a provider, then a model, then
  // confirms. Two round trips per keystroke would be its own bug.
  const [draftProvider, setDraftProvider] = useState(provider);
  const [draftModel, setDraftModel] = useState(model);

  // Adopt whatever the core reports, but only when the panel is not mid-edit:
  // an incoming event must not silently discard a half-made selection.
  useEffect(() => {
    if (busy) return;
    setDraftProvider(provider);
    setDraftModel(model);
  }, [provider, model, busy]);

  const running = sandbox === "running";
  const models =
    providers.find((p) => p.name === draftProvider)?.models ?? [];

  // Switching provider invalidates the model, since model ids are
  // provider-specific: "gpt-4o" means nothing to Anthropic.
  const onProviderChange = (name: string) => {
    setDraftProvider(name);
    setDraftModel("");
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
            <select
              className="settings-select"
              value={draftModel}
              onChange={(e) => setDraftModel(e.target.value)}
              disabled={!connected || busy || models.length === 0}
              aria-label="Model"
            >
              <option value="">default</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-accent"
              onClick={() => onBindProvider(draftProvider, draftModel)}
              disabled={!connected || busy || !draftProvider}
            >
              Apply
            </button>
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
