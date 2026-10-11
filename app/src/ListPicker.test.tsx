/**
 * The settings panel's provider and model pickers.
 *
 * The one worth reading is the free-text case. The model row promises that any
 * id can be typed -- a self-hosted gateway serves ids the core has never heard
 * of -- and a picker that only offered what the provider listed would take that
 * away without anything looking broken. So the typed value is asserted to be
 * offered and to be choosable, and the empty field is asserted to still mean
 * "the provider default".
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ListPicker } from "./ListPicker.js";
import { all, click, one, render, setValue, texts } from "./test-render.js";

const MODELS = ["openrouter/auto", "anthropic/claude-sonnet-4.5", "openai/gpt-5"];

async function picker(props: {
  value?: string;
  options?: string[];
  allowFreeText?: boolean;
  disabled?: boolean;
} = {}) {
  const chosen: string[] = [];
  const container = await render(
    <ListPicker
      label="Model"
      value={props.value ?? ""}
      options={props.options ?? MODELS}
      placeholder="default"
      disabled={props.disabled ?? false}
      allowFreeText={props.allowFreeText}
      onChange={(next) => chosen.push(next)}
    />,
  );
  return { container, chosen };
}

test("the trigger shows what is bound, or the placeholder when nothing is", async () => {
  const bound = await picker({ value: "openai/gpt-5" });
  assert.match(texts(bound.container, ".chip")[0] ?? "", /openai\/gpt-5/);

  const empty = await picker({});
  assert.match(texts(empty.container, ".chip")[0] ?? "", /default/);
});

test("choosing from the list reports the id, not the label", async () => {
  const { container, chosen } = await picker({ value: "openrouter/auto" });
  await click(one(container, ".chip")!);
  const item = all(container, ".modelpicker-item").find((n) =>
    (n.textContent ?? "").includes("claude-sonnet-4.5"),
  );
  assert.ok(item, "the model is not in the list");
  await click(item);
  assert.deepEqual(chosen, ["anthropic/claude-sonnet-4.5"]);
});

test("a typed value that matches nothing is still choosable", async () => {
  // The promise the row's note makes. Without this the picker silently closes
  // the door on every id the provider does not happen to list.
  const { container, chosen } = await picker({ allowFreeText: true });
  await click(one(container, ".chip")!);
  await setValue(
    one(container, ".modelpicker-filter") as HTMLInputElement,
    "my-gateway/uncensored-9b",
  );

  const offered = all(container, ".modelpicker-item").find((n) =>
    (n.textContent ?? "").includes("my-gateway/uncensored-9b"),
  );
  assert.ok(offered, "the typed id was not offered");
  await click(offered);
  assert.deepEqual(chosen, ["my-gateway/uncensored-9b"]);
});

test("an empty field still offers the provider default", async () => {
  // It is the only way back to "use whatever the provider defaults to", and
  // it was a documented behaviour of the input this replaced.
  const { container, chosen } = await picker({ value: "openai/gpt-5", allowFreeText: true });
  await click(one(container, ".chip")!);
  const first = all(container, ".modelpicker-item")[0];
  assert.match(first.textContent ?? "", /default/);
  await click(first);
  assert.deepEqual(chosen, [""]);
});

test("a filter narrows the list to what matches", async () => {
  const { container } = await picker({});
  await click(one(container, ".chip")!);
  await setValue(one(container, ".modelpicker-filter") as HTMLInputElement, "gpt");
  assert.equal(all(container, ".modelpicker-item").length, 1);
  assert.match(all(container, ".modelpicker-item")[0].textContent ?? "", /gpt-5/);
});

test("a disabled picker does not open", async () => {
  const { container } = await picker({ disabled: true });
  await click(one(container, ".chip")!);
  assert.equal(one(container, ".modelpicker"), null);
});
