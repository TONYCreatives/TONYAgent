import { useCallback, useRef } from "react";

/**
 * Answer a blocking prompt exactly once, whichever way the answer arrived.
 *
 * The core holds a tool open until an answer arrives, so two answers for one
 * prompt is a second `confirm.respond` for a call that no longer exists. Both
 * surfaces that ask -- the modal for destructive calls and the inline card above
 * the composer -- come through here rather than each keeping its own guard,
 * because "exactly once" is a property of the prompt rather than of the widget
 * that happened to draw it.
 *
 * A ref rather than a boolean, and keyed on the id: the inline card is mounted
 * and unmounted by the event that opened it, and the modal outlives its flag by
 * an animation's worth of time, so the guard has to release by itself for the
 * next prompt instead of needing a reset somebody has to remember.
 */
export function useAnswerOnce(
  id: string,
  onRespond: (id: string, confirmed: boolean) => void,
): (confirmed: boolean) => void {
  const answered = useRef<string | null>(null);
  return useCallback(
    (confirmed: boolean) => {
      if (answered.current === id) return;
      answered.current = id;
      onRespond(id, confirmed);
    },
    [id, onRespond],
  );
}
