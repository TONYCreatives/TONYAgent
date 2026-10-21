/**
 * The id-to-words fallback the chrome reads when the catalog has no name.
 *
 * One rule per test: separators become spaces, every token is capitalised,
 * and a vendor prefix the name repeats is said once. The catalog wins wherever
 * it answers -- this only has to read better than the raw id, not to know how
 * a vendor capitalises itself.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { brandToken, capitalizeFirst, prettifyModelName } from "./displayNames.js";

describe("capitalise one word", () => {
  test("the first letter goes up and the rest is untouched", () => {
    assert.equal(capitalizeFirst("connected"), "Connected");
    assert.equal(capitalizeFirst("stopped"), "Stopped");
    assert.equal(capitalizeFirst("V4.1"), "V4.1");
  });

  test("empty stays empty rather than throwing on charAt", () => {
    assert.equal(capitalizeFirst(""), "");
  });
});

describe("brand readings", () => {
  test("a brand reads as itself, whatever the case of the id", () => {
    assert.equal(brandToken("opencode"), "OpenCode");
    assert.equal(brandToken("OpenRouter"), "OpenRouter");
    assert.equal(brandToken("DEEPSEEK"), "DeepSeek");
    assert.equal(brandToken("gpt"), "GPT");
  });

  test("anything else keeps the naive reading", () => {
    assert.equal(brandToken("anthropic"), "Anthropic");
    assert.equal(brandToken("kimi"), "Kimi");
  });
});

describe("a model id as a person would write it", () => {
  test("dashes become spaces and brands read as themselves", () => {
    assert.equal(prettifyModelName("deepseek-v4.1-flash"), "DeepSeek V4.1 Flash");
    assert.equal(prettifyModelName("opencode-go"), "OpenCode Go");
  });

  test("a vendor prefix the name repeats is said once", () => {
    assert.equal(
      prettifyModelName("deepseek/deepseek-chat-v3-0324"),
      "DeepSeek Chat V3 0324",
    );
  });

  test("a vendor prefix the name only extends is said once too", () => {
    assert.equal(
      prettifyModelName("qwen/qwen2.5-coder-0.5b-instruct"),
      "Qwen2.5 Coder 0.5b Instruct",
    );
  });

  test("a vendor the name does not repeat is kept", () => {
    assert.equal(
      prettifyModelName("nvidia/nemotron-3-super-120b-a12b:free"),
      "Nvidia Nemotron 3 Super 120b A12b Free",
    );
  });

  test("an id with no separators is one capitalised word", () => {
    assert.equal(prettifyModelName("gpt-5"), "GPT 5");
    assert.equal(prettifyModelName("ollama"), "Ollama");
  });

  test("an already-pretty name survives untouched", () => {
    // Provider lists sometimes carry display names rather than ids. Reading
    // them through the same helper must not mangle what is already words.
    assert.equal(prettifyModelName("OpenRouter"), "OpenRouter");
    assert.equal(prettifyModelName("OpenCode Go"), "OpenCode Go");
  });
});
