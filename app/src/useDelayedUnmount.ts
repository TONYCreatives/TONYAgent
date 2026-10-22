/**
 * The lifecycle of a surface that is dismissed rather than navigated away from.
 *
 * Two hooks, because two things go wrong when an element is closed and
 * immediately deleted. It can vanish without animating, because an unmounted
 * node has no box to animate; that is `useDelayedUnmount`. And it can empty
 * itself on the way out -- a menu that slides back to the window origin, a
 * confirmation that blanks its own tool name -- because the state holding what
 * to show doubles as the flag saying whether to show it; that is `useLastValue`.
 *
 * `<Overlay>` is the one place most surfaces should reach for instead.
 */

import { useEffect, useRef, useState } from "react";

import { isMotionReduced } from "./motion.js";

/**
 * How long a dismissed surface stays in the DOM on its way out.
 *
 * This is not a constant here, because it is not a decision this file gets to
 * make. Every exit animation in styles.css runs on `--motion-fast`, so that
 * token is the single statement of how long an exit takes; copying its value
 * into TypeScript would create a second owner of one number, and the two would
 * drift the first time somebody tuned the animation and forgot this file.
 *
 * Read from the document instead, with a fallback for the cases where there is
 * no stylesheet to read -- jsdom in the tests, mostly. `SLACK_MS` covers the
 * gap between the animation finishing and the frame in which the node is
 * actually removed: too small a margin cuts the animation off mid-frame, and a
 * small overhang is invisible in a way that a short animation is not.
 */
const FALLBACK_MS = 110;
const SLACK_MS = 30;

/** `--motion-fast` in milliseconds, or the fallback if it cannot be read. */
export function exitDurationMs(): number {
  if (typeof window === "undefined" || typeof getComputedStyle !== "function") {
    return FALLBACK_MS + SLACK_MS;
  }
  const declared = getComputedStyle(document.documentElement)
    .getPropertyValue("--motion-fast")
    .trim();
  return parseCssTime(declared) + SLACK_MS;
}

/**
 * A CSS `<time>` in milliseconds.
 *
 * The unit is not decoration. A custom property's computed value is
 * re-serialised by the engine, and Chromium canonicalises times into seconds:
 * a stylesheet saying `110ms` reads back as `0.11s`. Reading the number and
 * assuming milliseconds therefore gets 0.11 -- and a delay of thirty
 * milliseconds under an animation that runs for a hundred and ten, which cuts
 * the exit off before it has finished. jsdom does not re-serialise, so a test
 * against jsdom alone reads `110ms` and passes; only a real browser shows it.
 */
function parseCssTime(declared: string): number {
  const match = /^(\d*\.?\d+)(ms|s)?$/.exec(declared);
  if (!match) return FALLBACK_MS;
  const value = Number.parseFloat(match[1]);
  if (!Number.isFinite(value) || value <= 0) return FALLBACK_MS;
  return match[2] === "s" ? value * 1000 : value;
}

/**
 * Keep a node mounted for a moment after `open` goes false.
 *
 * Every dismissible surface here -- the row menu, the modals, the log strip,
 * the files sidebar -- renders conditionally, so closing one deletes it from the
 * tree. An unmounted node has no box left to animate: there is no "closed"
 * state to fade out of, and the disappearance is a hard cut no duration can
 * soften. Returning `mounted` for a moment after the close gives the caller a
 * window in which the node is still there and still knows it is closing, so CSS
 * can play the exit.
 *
 * Under `prefers-reduced-motion` the stylesheet replaces every one of those
 * animations with `none`, so there is nothing left to wait for and the node is
 * dropped immediately. Holding it for the full duration anyway would give
 * exactly the people who asked for a still app the one behaviour they asked not
 * to have: a ghost element lingering where they dismissed it.
 *
 * `delay` is a parameter rather than being derived always, because a test --
 * and anything that needs to settle faster than a person can watch -- should
 * not have to fake a wall clock to prove the behaviour.
 */
export function useDelayedUnmount(open: boolean, delay?: number): boolean {
  const [mounted, setMounted] = useState(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    // Already down. Returning here (rather than scheduling another timeout that
    // would set the same value) is what stops the effect from re-arming itself
    // forever on every render.
    if (!mounted) return;
    const ms = delay ?? defaultDelay();
    if (ms <= 0) {
      setMounted(false);
      return;
    }
    const timer: ReturnType<typeof setTimeout> = setTimeout(() => setMounted(false), ms);
    return () => clearTimeout(timer);
  }, [open, mounted, delay]);

  return mounted;
}

/** How long to linger: nothing under reduced motion, else the exit animation. */
function defaultDelay(): number {
  if (isMotionReduced()) {
    return 0;
  }
  return exitDurationMs();
}

/**
 * The value a dismissible surface is showing, kept for as long as it is on
 * screen.
 *
 * A surface that shows something -- a menu's anchor, a confirmation's details --
 * clears that something the instant it is dismissed, because the state holding
 * it doubles as the "is it open" flag. But with `useDelayedUnmount` the node
 * outlives the flag by an animation's worth of time, and it has to render the
 * same thing it was showing a moment ago: a menu that fades out from the window
 * origin, or a dialog that clears itself mid-exit, is worse than no animation.
 *
 * So the flag and the payload are separated. The flag is cleared, the payload is
 * remembered. Passing a fresh non-null value also updates it, so the two cannot
 * drift; the write is idempotent and safe under React's repeated renders.
 */
export function useLastValue<T>(value: T | null): T | null {
  const last = useRef<T | null>(null);
  if (value !== null) last.current = value;
  return value ?? last.current;
}
