/**
 * Native folder picker.
 *
 * Split out from `App.tsx` for the same reason the sidecar transport is split
 * out of `backend.ts`: `@tauri-apps/plugin-dialog` is imported lazily via
 * `import()` so that importing this module in plain Node does not require a
 * Tauri install. A top-level import would be hoisted and evaluated eagerly.
 *
 * The picker is a Rust-side dialog, not an HTML `<input type="file">`. That is
 * deliberate: a web file input yields a `File`, not a directory path, and the
 * core needs a real path it can hand to the sandbox.
 */

type DialogModule = typeof import("@tauri-apps/plugin-dialog");

let cached: DialogModule | null = null;

async function loadDialog(): Promise<DialogModule> {
  if (!cached) cached = await import("@tauri-apps/plugin-dialog");
  return cached;
}

/**
 * Ask the user for a directory.
 *
 * @returns the absolute path, or `null` if the user cancelled. A cancel is a
 *   normal outcome, not an error -- callers must not surface it as one.
 */
export async function pickFolder(title = "Choose a project folder"): Promise<string | null> {
  const { open } = await loadDialog();
  const selected = (await open({
    directory: true,
    multiple: false,
    title,
  })) as string | string[] | null;
  // `multiple: false` narrows to a string today. The cast keeps the array case
  // handled anyway: a plugin upgrade that widens the return type would
  // otherwise hand the caller a first-element-of-array bug at runtime, with
  // the types still claiming it cannot happen.
  if (typeof selected === "string") return selected;
  if (Array.isArray(selected) && selected.length > 0) return selected[0];
  return null;
}
