/**
 * A dismissible surface that covers the window.
 *
 * Three of them exist -- the tool confirmation, the settings panel, the search
 * panel -- and all three had the same lifecycle written out separately in the
 * window that owns them: a flag for whether it was open, a second flag for
 * whether it was still on screen, a `closing` prop threaded into the child so
 * the child could decide which animation to play, and a conditional render on
 * the second flag. Five pieces of coordination for one idea, copied three
 * times, and any one of them forgotten turns the exit into a hard cut while the
 * other two keep animating.
 *
 * This component is that idea, once. The caller passes `open` -- which is the
 * only thing it actually knows -- and gets a backdrop that appears when `open`
 * goes true, plays its exit when `open` goes false, and is gone a moment
 * later. Children are rendered only while it is on screen, so a closed panel
 * does no work either.
 *
 * Two things deliberately do *not* live here. The rail's row menu is fixed to a
 * click rather than centred over the window, and the log strip grows inline
 * between the transcript and the composer; neither has a backdrop to own, so
 * both call `useDelayedUnmount` and publish `data-state` themselves.
 */

import type { ReactNode } from "react";

import { useDelayedUnmount } from "./useDelayedUnmount.js";

interface Props {
  /** The surface is showing while this is true. Flipping it is how it closes. */
  open: boolean;
  /** Clicking away dismisses. Omitted for a surface that may not be dismissed. */
  onDismiss?: () => void;
  children: ReactNode;
}

export function Overlay({ open, onDismiss, children }: Props) {
  const mounted = useDelayedUnmount(open);
  if (!mounted) return null;

  return (
    <div
      className="modal-backdrop"
      // The stylesheet animates on this attribute rather than on a class,
      // because `closed` is a real state the surface is in for a measurable
      // length of time, not a transient. It also carries `pointer-events: none`
      // there: a full-window backdrop that is still clickable after the user
      // closed the dialog swallows their next click.
      data-state={open ? "open" : "closed"}
      onClick={onDismiss}
    >
      {children}
    </div>
  );
}
