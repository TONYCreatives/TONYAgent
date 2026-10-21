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
 * Tokens naive capitalisation gets wrong.
 *
 * `capitalizeFirst("opencode")` reads "Opencode", which is a misspelling of a
 * brand, not a simplification of an id. The map holds only those: anything
 * else keeps the naive reading, and an unknown vendor still reads better
 * capitalised than raw. Small on purpose -- the catalog is what knows model
 * names, and this is the fallback for what it does not.
 */
const BRANDS: Record<string, string> = {
  opencode: "OpenCode",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  deepseek: "DeepSeek",
  glm: "GLM",
  gpt: "GPT",
};

/** One token as a person would write it: brand readings first, then naive. */
export function brandToken(token: string): string {
  return BRANDS[token.toLowerCase()] ?? capitalizeFirst(token);
}

/**
 * An id as a person would write it: `deepseek/deepseek-v4.1-flash` becomes
 * `DeepSeek V4.1 Flash`, and `opencode-go` becomes `OpenCode Go`.
 *
 * Split on the separators ids are built from, drop a vendor prefix the name
 * already starts with (so `deepseek/deepseek-chat` does not read the vendor
 * twice), and read each token through `brandToken`. A fallback, not a
 * catalog: rows the catalog knows keep the catalog's own name, and this is
 * what the rest read as.
 */
export function prettifyModelName(id: string): string {
  const tokens = id.split(/[/\-_ :]+/).filter(Boolean);
  if (
    tokens.length > 1 &&
    tokens[1].toLowerCase().startsWith(tokens[0].toLowerCase())
  ) {
    tokens.shift();
  }
  return tokens.map(brandToken).join(" ");
}
