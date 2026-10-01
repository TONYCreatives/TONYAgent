import type { ChatState } from "./events";

interface Props {
  /**
   * What to show.
   *
   * Deliberately not nullable. Whether to show it belongs to the `Overlay` the
   * window puts around this, and that overlay keeps the dialog mounted after a
   * close so it can animate out -- which is why the window holds on to the
   * last request rather than passing null.
   */
  request: NonNullable<ChatState["pendingConfirm"]>;
  onRespond: (id: string, confirmed: boolean) => void;
}

/**
 * Blocking prompt for a destructive tool call.
 *
 * The core holds the tool open until `confirm.respond` arrives, so the turn
 * stays busy while this is up. It is rendered as a modal rather than inline
 * because denying is the safe default and should not be a misclick.
 *
 * Not dismissible by clicking away: this one is a decision, not a peek, and a
 * stray click must not be readable as an answer.
 */
export function ConfirmDialog({ request, onRespond }: Props) {
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">Confirm tool execution</h2>

        <dl className="confirm-detail">
          <dt>Tool</dt>
          <dd>{request.name}</dd>
          {request.arguments && (
            <>
              <dt>Arguments</dt>
              <dd>
                <code>{request.arguments}</code>
              </dd>
            </>
          )}
        </dl>

        {request.destructive && (
          <p className="warn">This action is destructive and cannot be undone.</p>
        )}

        <div className="modal-actions">
          <button type="button" className="btn btn-danger" onClick={() => onRespond(request.id, true)}>
            Allow
          </button>
          <button type="button" className="btn" onClick={() => onRespond(request.id, false)}>
            Deny
          </button>
        </div>
    </div>
  );
}
