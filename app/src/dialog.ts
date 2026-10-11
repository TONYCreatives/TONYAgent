/**
 * Native folder picker.
 *
 * Split out from `App.tsx` for the same reason the transport is split out of
 * `backend.ts`: the App should not know how the window is reached, and a test
 * that renders the App should not need a window to exist.
 *
 * The picker is the host's, not an HTML `<input type="file">`. That is
 * deliberate, and it was deliberate when it was Tauri's too: a web file input
 * yields a `File`, not a directory path, and the core needs a real path it can
 * hand to the sandbox.
 */

import { whenHostReady } from "./bridge.js";

/**
 * Ask the user for a directory.
 *
 * @returns the absolute path, or `null` if no folder was chosen. Two different
 *   things land in that one answer -- the user cancelled, and there is no host
 *   to ask -- and they are the same thing to every caller, which is why they
 *   are not told apart. A cancel is a normal outcome rather than an error; a
 *   page open in a browser has nowhere to put a picker's answer.
 */
export async function pickFolder(): Promise<string | null> {
  const api = await whenHostReady();
  if (!api) return null;
  const { path } = await api.pick_folder();
  return path ?? null;
}

