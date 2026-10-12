/**
 * The provider's own dashboard, opened in the browser window the host owns.
 *
 * Split out of `Dashboard.tsx` for the same reason `dialog.ts` is split out of
 * `App.tsx`: the view should not know how the window is reached, and a test
 * that renders the dashboard should not need a window to exist.
 *
 * **Why a browser and not a fetch.** The number the user wants is the account's
 * own usage, and it lives behind their sign-in. Nothing the page can call has
 * that cookie, and nothing the core can call is the whole of it either — the
 * credit balance and the other keys are the site's own report. So the host
 * opens a real window at the page and the user reads it there, signed in once
 * because the profile outlives the process.
 */

import { host, type AccountRead, type AccountView } from "./bridge.js";

/**
 * What came of asking. Two ways to fail, and they are told apart.
 *
 * The provider's page can be behind no browser at all -- there is no host, so
 * this page is not running inside the app -- or behind a host that refused to
 * create a second window. Both are "the user cannot see the page", and they are
 * not the same sentence: the first is a normal way for a page to run, and the
 * second is the app failing to do something it promised.
 */
export type AccountOpen =
  | { opened: true; url: string }
  | { opened: false; reason: "no-host" | "refused" };

/**
 * Ask the host to show one of the provider's pages.
 *
 * `host()` is the synchronous read rather than `whenHostReady()`, and that is a
 * deliberate difference from `dialog.ts`. A picker can be asked for from
 * anywhere; this is a press in a view that only renders after the app's
 * bootstrap has waited for the bridge, so by the time a button can be pressed
 * the answer is already known — and a page with no host should say so at once
 * rather than after a timeout.
 */
export async function openAccountView(view: AccountView): Promise<AccountOpen> {
  const api = host();
  if (!api) return { opened: false, reason: "no-host" };
  const { url, opened } = await api.open_account_view(view);
  return opened ? { opened: true, url } : { opened: false, reason: "refused" };
}

/**
 * Show one of the provider's pages and read the figures it is displaying.
 *
 * @returns what the page said, or `null` when there is no host to ask. The
 *   result carries its own failure in `ok`/`reason` rather than rejecting,
 *   because "the page did not arrive in time" is a normal outcome of reading
 *   somebody else's website and the view has a sentence for it.
 *
 * The read is slow on purpose: it navigates a real window and waits for the page
 * to fetch its own numbers, which is seconds rather than milliseconds. The view
 * says so while it waits rather than looking frozen.
 */
export async function readAccountView(view: AccountView): Promise<AccountRead | null> {
  const api = host();
  if (!api) return null;
  try {
    return await api.read_account_view(view);
  } catch {
    // The host refuses an unknown view name by raising, and anything else that
    // escapes this far is the same thing to the view: a read that did not happen.
    return null;
  }
}
