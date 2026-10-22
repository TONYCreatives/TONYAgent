/**
 * The window's motion preference: what the settings page's Motion menu chose.
 *
 * The stylesheet's reduced-motion block follows the operating system's
 * `prefers-reduced-motion` on its own. This preference is the override on top
 * of it: `system` (the default) leaves the OS answer alone, `full` keeps the
 * animations even when the OS asks for stillness, and `reduced` drops them
 * even when it does not.
 *
 * A window preference rather than project state, for the same reason the rail
 * and the palette are: it is about this program on this machine, and it is
 * read before any project is open.
 */

export type MotionPreference = "system" | "full" | "reduced";

const STORAGE_KEY = "tonyagent.motion";

/** The persistent store, or null where there is none (or none to have). */
function getStorage(): Storage | null {
  // `window.localStorage` first: the test DOM installs a window but no bare
  // `localStorage` binding, and a bare read there throws rather than answering.
  try {
    if (typeof window !== "undefined" && typeof window.localStorage !== "undefined") {
      return window.localStorage;
    }
  } catch {
    // Denied (opaque origin): fall through to the bare binding.
  }
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    // No binding at all.
  }
  return null;
}

/** The root element, or null where there is no document (a bare test). */
function getRoot(): Element | null {
  try {
    if (typeof document !== "undefined") return document.documentElement;
  } catch {
    // No document.
  }
  return null;
}

export function readMotionPreference(): MotionPreference {
  try {
    const raw = getStorage()?.getItem(STORAGE_KEY);
    if (raw === "full" || raw === "reduced" || raw === "system") return raw;
  } catch {
    // Private mode or storage disabled: fall back to the OS answer.
  }
  return "system";
}

/**
 * Carry the preference into the cascade.
 *
 * `system` removes the attribute rather than writing it, so the stylesheet's
 * media query answers on its own. Anything else is named outright, and the
 * two override blocks in `reduced-motion.css` key off it.
 */
export function applyMotionPreference(preference: MotionPreference): void {
  try {
    const root = getRoot();
    if (root) {
      if (preference === "system") {
        root.removeAttribute("data-motion");
      } else {
        root.setAttribute("data-motion", preference);
      }
    }
    getStorage()?.setItem(STORAGE_KEY, preference);
  } catch {
    // Private mode or storage disabled: the preference just does not stick.
  }
}

/**
 * Whether motion is off right now, whatever asked for it.
 *
 * The stylesheet knows this on its own, but JS that times an exit animation
 * cannot read the cascade -- `useDelayedUnmount` asks here instead, so a
 * dismissed surface does not linger for an animation that will never play.
 */
export function isMotionReduced(): boolean {
  try {
    const override = getRoot()?.getAttribute("data-motion");
    if (override === "full") return false;
    if (override === "reduced") return true;
  } catch {
    // No document (a test without a DOM): fall through to the OS answer.
  }
  try {
    return (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  } catch {
    return false;
  }
}
