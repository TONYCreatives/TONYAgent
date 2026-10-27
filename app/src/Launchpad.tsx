/**
 * The window before the first message: what this is, what is missing, and four
 * ways to begin.
 *
 * It replaces the old first-run panel, which was a mark, a slogan, the project
 * folder and two keyboard hints. That panel was honest and it was inert: the
 * only thing on it a user could press was the folder, and the two things a new
 * user most needs -- what to ask, and which setup step is blocking them -- were
 * nowhere on it. This is the same panel with those two answers added.
 *
 * **Every suggestion is a prefill, never a send.** Pressing one writes a
 * sentence into the composer and puts the caret at its end; the user edits it
 * or sends it. A card that sent on press would be a demo of the agent rather
 * than a starting point for the user's own request, and this window has no place
 * for a scripted conversation.
 *
 * **The setup card only lists what is actually missing.** No folder, no
 * provider, no model -- each row is computed from the window's own state, so a
 * configured window draws no card at all and a half-configured one is told
 * exactly the next step. The model row has no button on purpose: the model menu
 * is in the title bar, one glance up from here, and a second control for it
 * would be a second thing to keep in step.
 *
 * **Nothing here is drawn without a core.** With the backend stopped, a
 * suggestion that fills a disabled field is a promise the window cannot keep --
 * the status strip is already saying why.
 */

import { AppMark } from "./AppMark.js";
import { Icon } from "./icons.js";
import type { ConversationSummary } from "./ConversationList.js";
import { when } from "./relativeTime.js";

interface Props {
  /** The project folder the core is working on, or "" when there is none. */
  project: string;
  /** The core is running. Without it nothing on this panel can be acted on. */
  connected: boolean;
  /** The core has no provider bound. */
  needsProvider: boolean;
  /** The bound model id, or "" when none is chosen. */
  model: string;
  /** The conversations the core knows about, for the recent row. */
  conversations?: ConversationSummary[];
  /** The open conversation, so it is not offered back to the user. */
  activeId?: string;
  onChooseFolder?: () => void;
  canChooseFolder?: boolean;
  /** Open one of the recent chats. */
  onOpen: (id: string) => void;
  /** Put a sentence in the composer; the user finishes or sends it. */
  onPrefill: (text: string) => void;
  /** Open the page that fixes a missing provider. */
  onSetup: () => void;
}

/** One suggestion: what the card says, and what it puts in the field. */
interface Suggestion {
  label: string;
  text: string;
}

/**
 * The prompts, in two sets.
 *
 * With a folder, they are about *this* project, because that is what the agent
 * can see. Without one, they are about the work itself -- and none of them
 * promises a file or a change, because a model with no folder has no file to
 * open. Both sets end with the same unfinished sentence: a prefill that invites
 * the user to finish it is the one that cannot be mistaken for a command.
 */
const PROJECT_PROMPTS: Suggestion[] = [
  {
    label: "Explain how this project is laid out",
    text: "Explain how this project is laid out, starting with the top-level folders.",
  },
  {
    label: "Find the entry point",
    text: "Find this project's entry point and walk me through what happens when it starts.",
  },
  {
    label: "Find the tests and what they cover",
    text: "Find this project's tests and tell me what they cover.",
  },
  {
    label: "Turn an idea into a plan",
    text: "Turn this idea into a step-by-step plan: ",
  },
];

const BLANK_PROMPTS: Suggestion[] = [
  {
    label: "Explain what you can do",
    text: "Explain what you can do in this window and which tools you have.",
  },
  {
    label: "Turn an idea into a plan",
    text: "Turn this idea into a step-by-step plan: ",
  },
  {
    label: "Draft a technical spec",
    text: "Draft a technical spec for this: ",
  },
  {
    label: "Show me a good first project",
    text: "Suggest a small first project I could build here, and what it would involve.",
  },
];

/** The folder's own name, out of a path, on either separator. */
function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** One missing thing, and the control that fixes it (when there is one). */
interface Missing {
  key: string;
  label: string;
  hint: string;
  action?: { label: string; run: () => void; disabled?: boolean };
}

export function Launchpad({
  project,
  connected,
  needsProvider,
  model,
  conversations = [],
  activeId = "",
  onChooseFolder,
  canChooseFolder = true,
  onOpen,
  onPrefill,
  onSetup,
}: Props) {
  const missing: Missing[] = [];
  if (connected) {
    if (!project) {
      missing.push({
        key: "folder",
        label: "No project folder",
        hint: "The agent's tools resolve every path against one.",
        action: onChooseFolder
          ? {
              label: "Choose folder...",
              run: onChooseFolder,
              disabled: !canChooseFolder,
            }
          : undefined,
      });
    }
    if (needsProvider) {
      missing.push({
        key: "provider",
        label: "No provider connected",
        hint: "Choose a provider and its key in Settings.",
        action: { label: "Open settings", run: onSetup },
      });
    } else if (!model) {
      missing.push({
        key: "model",
        label: "No model chosen",
        hint: "Pick one from the model menu in the title bar.",
      });
    }
  }

  const suggestions = connected
    ? project
      ? PROJECT_PROMPTS
      : BLANK_PROMPTS
    : [];

  const recent = conversations
    .filter((c) => c.id !== activeId && c.message_count > 0)
    .sort((a, b) => b.updated_at - a.updated_at)
    .slice(0, 3);

  // The standalone folder row is the whole setup when nothing is missing, and
  // the card's own row when something is -- never both. A window with no folder
  // would otherwise name the absence twice in the same column.
  const folderInCard = missing.some((row) => row.key === "folder");

  return (
    <div className="empty">
      <div className="empty-inner">
        <AppMark className="empty-mark" size={104} />
        <h1>TONYAgent</h1>
        <p>Ask for something. The agent will use its tools to do it.</p>

        {missing.length > 0 && (
          <section className="launch-setup" aria-label="Before the first turn">
            <h2 className="launch-title">Before the first turn</h2>
            <ul className="launch-setup-rows">
              {missing.map((row) => (
                <li key={row.key} className="launch-setup-row">
                  <span className="launch-setup-label">{row.label}</span>
                  <span className="launch-setup-hint">{row.hint}</span>
                  {row.action && (
                    <button
                      type="button"
                      className="btn"
                      onClick={row.action.run}
                      disabled={row.action.disabled}
                    >
                      {row.action.label}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {suggestions.length > 0 && (
          <ul className="launch-suggestions">
            {suggestions.map((suggestion) => (
              <li key={suggestion.label}>
                <button
                  type="button"
                  className="launch-card"
                  onClick={() => onPrefill(suggestion.text)}
                >
                  <span className="launch-card-label">{suggestion.label}</span>
                  <Icon name="forward" size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {recent.length > 0 && (
          <section className="launch-recent" aria-label="Recent chats">
            <h2 className="launch-title">Pick up where you left off</h2>
            <ul className="launch-recent-rows">
              {recent.map((chat) => (
                <li key={chat.id}>
                  <button
                    type="button"
                    className="launch-recent-row"
                    onClick={() => onOpen(chat.id)}
                    title={chat.title}
                  >
                    <span className="launch-recent-name">{chat.title}</span>
                    <span className="launch-recent-when">
                      {when(chat.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {!folderInCard && (
          <div className="empty-folder">
            <Icon name="folder" size={16} className="empty-folder-icon" />
            <p className="empty-folder-name" title={project || undefined}>
              {project ? folderName(project) : "No project folder"}
            </p>
            {onChooseFolder && (
              <button
                type="button"
                className="btn"
                onClick={onChooseFolder}
                disabled={!canChooseFolder}
              >
                {project ? "Change..." : "Choose folder..."}
              </button>
            )}
          </div>
        )}

        <ul className="empty-hints">
          <li>
            <kbd>/</kbd> for skills
          </li>
          <li>
            <kbd>@</kbd> for threads or files
          </li>
        </ul>
      </div>
    </div>
  );
}
