/**
 * Top bar: what the conversation is, and whether it is working.
 *
 * Deliberately not a second navigation surface. It used to carry a sidebar
 * toggle, a clear button and a new-chat button -- each of which also existed in
 * the rail directly to its left. Two controls for one action is not a choice the
 * user made; it is the same action listed twice, and it makes the window read as
 * cluttered while giving no extra capability.
 *
 * So this bar answers exactly one question -- "what am I looking at, and is it
 * busy?" -- and the rail answers "what can I do?".
 */

interface Props {
  busy: boolean;
}

export function TopBar({ busy }: Props) {
  return (
    <header className="topbar">
      <div className="tab">
        {busy && <span className="tab-spinner" aria-label="Working" />}
        <span>TONYAgent</span>
      </div>
    </header>
  );
}