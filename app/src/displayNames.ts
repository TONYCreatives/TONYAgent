/**
 * Display names for things the core names in lowercase.
 *
 * Model ids are addresses (`deepseek/deepseek-chat-v3-0324`), and the status
 * bar and the composer chip used to draw them verbatim -- which is how the
 * window ended up saying "connected" and "deepseek-v4.1-flash" where a person
 * would write "Connected" and "DeepSeek V4.1 Flash". The ids stay the ids
 * everywhere they are acted on (binds, filters, tooltips); these helpers are
 * for the words a person reads.
 */

/** `stopped` becomes `Stopped`. Empty stays empty. */
export function capitalizeFirst(word: string): string {
  if (!word) return word;
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/**
 * An id as a person would write it: `deepseek/deepseek-v4.1-flash` becomes
 * `DeepSeek V4.1 Flash`.
 *
 * Split on the separators ids are built from, drop a vendor prefix the name
 * already starts with (so `deepseek/deepseek-chat` does not read the vendor
 * twice), and capitalise each token. A fallback, not a catalog: rows the
 * catalog knows keep the catalog's own name, and this is what the rest read
 * as. It cannot know camel boundaries (`Deepseek`, not `DeepSeek`), which is
 * exactly why the catalog wins wherever it has an answer.
 */
export function prettifyModelName(id: string): string {
  const tokens = id.split(/[/\-_ :]+/).filter(Boolean);
  if (
    tokens.length > 1 &&
    tokens[1].toLowerCase().startsWith(tokens[0].toLowerCase())
  ) {
    tokens.shift();
  }
  return tokens.map(capitalizeFirst).join(" ");
}
