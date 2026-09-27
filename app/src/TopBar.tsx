/**
 * Top bar: sidebar toggle, the conversation tab, and new-chat.
 *
 * The tab is a pill because that is the reference's affordance, and the spinner
 * inside it is the only place a turn's progress is shown — the status bar
 * carries connection and provider state, which is a different question.
 */

interface Props {
  busy: boolean;
  connected: boolean;
  onNewChat: () => void;
  onClear: () => void;
  onToggleRail: () => void;
}

export function TopBar({ busy, connected, onNewChat, onClear, onToggleRail }: Props) {
  return (
    <header className="topbar">
      <button
        type="button"
        className="topbar-toggle"
        onClick={onToggleRail}
        title="Toggle sidebar"
        aria-label="Toggle sidebar"
      >
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
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M9 4v16" />
        </svg>
      </button>

      <div className="tab">
        {busy && <span className="tab-spinner" aria-label="Working" />}
        <span>TONYAgent</span>
        <button
          type="button"
          className="tab-clear"
          onClick={onClear}
          disabled={!connected || busy}
          title="Clear conversation"
          aria-label="Clear conversation"
        >
          &#215;
        </button>
      </div>

      <button
        type="button"
        className="topbar-new"
        onClick={onNewChat}
        disabled={!connected || busy}
        title="New chat"
        aria-label="New chat"
      >
        +
      </button>

      <div className="topbar-spacer" />
    </header>
  );
}
