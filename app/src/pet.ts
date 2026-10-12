/**
 * The desktop pet, from the two pages that talk to it.
 *
 * Split out for the same reason `dialog.ts` and `account.ts` are: neither the
 * dashboard nor the app should know how a window is reached, and a test that
 * renders either should not need a window to exist.
 *
 * **Two callers, and they are different.** The app window asks for the state and
 * changes it, and pushes what the card should draw. The card itself only
 * announces that it is listening, and raises the app when clicked. One module
 * because they are one relationship -- see `Bridge.pet`.
 */

import { whenHostReady, type HostApi } from "./bridge.js";
import type { PetStatus } from "./pet-status.js";

/**
 * The bridge, waiting for it if it has not been injected yet.
 *
 * **`whenHostReady`, not `host()`, and the difference was measured.** pywebview
 * injects `window.pywebview.api` *after* the document loads and announces it with
 * `pywebviewready`. The app's window never notices, because it bootstraps through
 * this same helper and does not draw until the bridge is there. The card does: it
 * renders on mount, so its effect called `host()`, got `null`, and dropped the
 * one `ready` that tells the host anything is listening -- after which no status
 * ever arrived and the card sat on "ready when you are" for its whole life while
 * the agent worked. Read off a real window: `page_ready: false`.
 *
 * Nothing is imported from pywebview for this; `whenHostReady` resolves to `null`
 * on a page with no host at all, which is what a browser preview is.
 */
async function api(): Promise<HostApi | null> {
  return await whenHostReady();
}

export interface PetState {
  /** Whether a card window exists right now. */
  open: boolean;
  /** Whether it should be up when the app next starts. */
  wanted: boolean;
}

const CLOSED: PetState = { open: false, wanted: false };

/** What the app's toggle draws itself from. */
export async function petState(): Promise<PetState> {
  const host = await api();
  if (!host) return CLOSED;
  return await host.pet("state");
}

/** Show the card, or hide it. Resolves to what is actually true afterwards. */
export async function petSet(open: boolean): Promise<PetState> {
  const host = await api();
  if (!host) return CLOSED;
  return await host.pet(open ? "show" : "hide");
}

/**
 * Tell the card what to draw.
 *
 * Called on every change of the agent's status, and it is deliberately cheap:
 * one host call and nothing else. The host keeps the last one, so a card opened
 * later draws the current status rather than waiting for something to happen
 * before it says anything.
 */
export async function petDraw(status: PetStatus): Promise<void> {
  const host = await api();
  if (!host) return;
  await host.pet("status", status as unknown as Record<string, unknown>);
}

/**
 * The card's own: it is listening, so the host can push what it remembered.
 *
 * @returns whether the host actually took it. **The answer is the point.**
 *   Announcing once and hoping is what was measured failing: the card asked
 *   before the bridge had been injected, and because that one call was the only
 *   one, the host never learned the page was listening -- so no status was ever
 *   delivered and the card said "ready when you are" for its whole life while the
 *   agent worked. A card that misses this has no second chance, so the caller
 *   retries until this says `true`, and the host's `mark_ready` is idempotent so a
 *   repeat costs one round trip.
 */
export async function petReady(): Promise<boolean> {
  const host = await api();
  if (!host) return false;
  await host.pet("ready");
  return true;
}

/** The card's own: bring the app forward. */
export async function petFocusApp(): Promise<void> {
  const host = await api();
  if (!host) return;
  await host.pet("focus");
}
