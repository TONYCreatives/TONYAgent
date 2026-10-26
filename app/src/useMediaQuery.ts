/**
 * A viewport question, answered as React state.
 *
 * The workspace has two docked panes whose behaviour depends on whether the
 * window can hold them, and that is not a question CSS alone can answer: below
 * the dock widths the *same* open state must render as an overlay with the rail
 * still underneath, and a rule that only moved boxes would leave the rail
 * focusable behind a panel. So the shell asks once, and the answer decides what
 * is mounted.
 *
 * `matchMedia` is absent in jsdom and in any non-window context, and that is the
 * compact answer rather than an error: a test renders the narrow shell, which is
 * the one with no dock columns and therefore the one whose landmarks are stable.
 */
import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const read = () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false;

  const [matches, setMatches] = useState<boolean>(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    // Read once on mount as well as subscribing: the query may have changed
    // between the first render and this effect, and a stale `false` would draw
    // a dock column for one frame before the change arrived.
    update();
    list.addEventListener("change", update);
    // **And the window's own resize.** `change` is the correct event and the
    // one WebView2 sends; a resized viewport in some harnesses (including the
    // preview browser this window is developed in) moves the media query's
    // answer without dispatching it. Resize is the belt to that braces: the
    // listener re-reads a value that has already been computed, so it cannot
    // disagree with a `change` that never arrived.
    window.addEventListener("resize", update);
    return () => {
      list.removeEventListener("change", update);
      window.removeEventListener("resize", update);
    };
  }, [query]);

  return matches;
}
