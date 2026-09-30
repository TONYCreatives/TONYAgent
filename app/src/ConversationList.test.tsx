/**
 * The conversation row's menu and its inline rename editor.
 *
 * These are interaction tests rather than render tests, because the rules worth
 * protecting are all about *what a keystroke does*: Enter commits, blur
 * commits, Escape throws the edit away, and a blank name is refused. A
 * snapshot of the markup would pass unchanged while every one of those four
 * behaviours was broken.
 *
 * The interesting one is the blank name. The core refuses it, but the editor
 * has to refuse it too, and refusing it wrongly -- by closing and showing the
 * old title -- reads as a successful rename. So the assertion is on both
 * halves: nothing is saved, *and* what the user typed is still there.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import {
  ConversationList,
  type ConversationSummary,
} from "./ConversationList.js";
import { dom } from "./test-dom.js";

const { window } = dom;

function conversation(over: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    id: "a".repeat(32),
    title: "Original title",
    project: "",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    message_count: 3,
    ...over,
  };
}

interface Handlers {
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDuplicate: (id: string) => void;
}

let root: Root | null = null;
let calls: Handlers & { renamed: [string, string][]; opened: string[]; deleted: string[]; duplicated: string[]; news: number };

/** Mount the list and return its container. Cleaned up after each test. */
async function render(rows: ConversationSummary[], active = ""): Promise<HTMLElement> {
  const container = window.document.createElement("div");
  window.document.body.appendChild(container);
  root = createRoot(container);

  calls = {
    onNew: () => { calls.news += 1; },
    onOpen: (id) => { calls.opened.push(id); },
    onDelete: (id) => { calls.deleted.push(id); },
    onRename: (id, title) => { calls.renamed.push([id, title]); },
    onDuplicate: (id) => { calls.duplicated.push(id); },
    renamed: [],
    opened: [],
    deleted: [],
    duplicated: [],
    news: 0,
  };

  await act(async () => {
    root!.render(
      <ConversationList
        conversations={rows}
        active={active}
        busy={false}
        connected
        {...calls}
      />,
    );
  });
  return container;
}

afterEach(async () => {
  if (root) {
    const current = root;
    root = null;
    await act(async () => { current.unmount(); });
  }
  window.document.body.innerHTML = "";
});

const rows = (container: HTMLElement) =>
  [...container.querySelectorAll(".chatrow")] as HTMLElement[];

const titles = (container: HTMLElement) =>
  [...container.querySelectorAll(".chatrow-title")].map((n) => n.textContent);

const input = (container: HTMLElement) =>
  container.querySelector(".chatrow-input") as HTMLInputElement | null;

const menuItems = (container: HTMLElement) =>
  [...container.querySelectorAll(".rowmenu [role='menuitem']")].map(
    (n) => n.textContent,
  );

async function rightClick(row: HTMLElement): Promise<void> {
  await act(async () => {
    row.dispatchEvent(
      new window.MouseEvent("contextmenu", {
        bubbles: true,
        clientX: 40,
        clientY: 20,
      }),
    );
  });
}

async function chooseMenuItem(container: HTMLElement, label: string): Promise<void> {
  const item = [...container.querySelectorAll(".rowmenu [role='menuitem']")].find(
    (n) => n.textContent === label,
  ) as HTMLElement;
  assert.ok(item, `no "${label}" in the menu`);
  await act(async () => { item.click(); });
}

/**
 * Type into the rename field the way a person does.
 *
 * Assigning `input.value` does not notify React -- it patches the DOM node's
 * own property, and React listens for the `input` event -- so the native
 * setter has to be used, exactly as a browser would.
 */
async function type(value: string): Promise<void> {
  const field = input(document.body) as HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setter.call(field, value);
    field.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}

async function press(key: string, field: HTMLElement): Promise<void> {
  await act(async () => {
    field.dispatchEvent(
      new window.KeyboardEvent("keydown", { key, bubbles: true }),
    );
  });
}

async function openEditor(container: HTMLElement, index = 0): Promise<HTMLInputElement> {
  await rightClick(rows(container)[index]);
  await chooseMenuItem(container, "Rename");
  const field = input(container);
  assert.ok(field, "Rename did not open an editor");
  return field;
}

// --- the menu -------------------------------------------------------------
describe("the row menu", () => {
  test("a right-click offers rename, duplicate and delete", async () => {
    const container = await render([conversation()]);
    await rightClick(rows(container)[0]);
    assert.deepEqual(menuItems(container), ["Rename", "Duplicate", "Delete"]);
  });

  test("it opens on the row that was clicked, not the first one", async () => {
    const first = conversation();
    const second = conversation({ id: "b".repeat(32), title: "Second" });
    const container = await render([first, second]);
    await rightClick(rows(container)[1]);
    await chooseMenuItem(container, "Duplicate");
    assert.deepEqual(calls.duplicated, [second.id]);
  });

  test("the ... button opens the same menu, for anyone not holding a mouse", async () => {
    const container = await render([conversation()]);
    const more = container.querySelector(".chatrow-more") as HTMLElement;
    assert.ok(more, "the row has no keyboard-reachable trigger");
    await act(async () => { more.click(); });
    assert.deepEqual(menuItems(container), ["Rename", "Duplicate", "Delete"]);
  });

  test("escape closes it without acting", async () => {
    const container = await render([conversation()]);
    await rightClick(rows(container)[0]);
    await act(async () => {
      window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
    });
    assert.equal(container.querySelector(".rowmenu"), null);
    assert.deepEqual(calls.renamed, []);
    assert.deepEqual(calls.deleted, []);
  });

  test("pressing elsewhere closes it", async () => {
    const container = await render([conversation()]);
    await rightClick(rows(container)[0]);
    assert.ok(container.querySelector(".rowmenu"));
    await act(async () => {
      window.document.body.dispatchEvent(
        new window.Event("pointerdown", { bubbles: true }),
      );
    });
    assert.equal(container.querySelector(".rowmenu"), null);
  });

  test("delete removes the row it was opened on", async () => {
    const container = await render([conversation()]);
    await rightClick(rows(container)[0]);
    await chooseMenuItem(container, "Delete");
    assert.deepEqual(calls.deleted, [conversation().id]);
  });
});

// --- the inline editor ----------------------------------------------------
describe("renaming a conversation", () => {
  test("it opens holding the current title, focused", async () => {
    const container = await render([conversation({ title: "What I said" })]);
    const field = await openEditor(container);
    assert.equal(field.value, "What I said");
    assert.equal(window.document.activeElement, field);
    assert.equal(container.querySelector(".chatrow-title"), null);
  });

  test("enter saves the new title and closes the editor", async () => {
    const container = await render([conversation()]);
    const field = await openEditor(container);
    await type("Invoice questions");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "Invoice questions"]]);
    assert.equal(input(container), null);
  });

  test("blur saves too, because clicking away is also finishing", async () => {
    const container = await render([conversation()]);
    const field = await openEditor(container);
    await type("Clicked away");
    await act(async () => { field.blur(); });
    assert.deepEqual(calls.renamed, [[conversation().id, "Clicked away"]]);
    assert.equal(input(container), null);
  });

  test("surrounding whitespace is trimmed off the name", async () => {
    const container = await render([conversation()]);
    const field = await openEditor(container);
    await type("   Padded   ");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "Padded"]]);
  });

  test("escape abandons the edit and keeps the old title", async () => {
    const container = await render([conversation({ title: "Keep me" })]);
    const field = await openEditor(container);
    await type("Discarded");
    await press("Escape", field);
    assert.deepEqual(calls.renamed, []);
    assert.equal(input(container), null);
    assert.deepEqual(titles(container), ["Keep me"]);
  });

  test("a blank name is refused and what was typed is not thrown away", async () => {
    const container = await render([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await type("");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [], "a blank name must not be saved");
    assert.ok(input(container), "the editor closed on a refused name");
    assert.equal((input(container) as HTMLInputElement).value, "");
  });

  test("a name of only spaces is refused the same way", async () => {
    const container = await render([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await type("   \t  ");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, []);
    assert.ok(input(container), "the editor closed on a refused name");
    assert.deepEqual(titles(container), []);
  });

  test("a refused name does not silently fall back to the old one", async () => {
    /**
     * The failure this guards: closing the editor and leaving the old title on
     * screen. That looks exactly like a rename that worked, and the user has no
     * way to tell their name was dropped.
     */
    const container = await render([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await type("  ");
    await press("Enter", field);
    assert.ok(input(container), "the row fell back to the old title");
    assert.equal(container.querySelector(".chatrow-title"), null);
  });

  test("escape after a refused name still cancels cleanly", async () => {
    const container = await render([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await type("");
    await press("Enter", field);
    await press("Escape", field);
    assert.deepEqual(calls.renamed, []);
    assert.deepEqual(titles(container), ["Untouched"]);
  });

  test("a name in another language survives the round trip", async () => {
    const container = await render([conversation()]);
    const field = await openEditor(container);
    await type("코어 동작 설명");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "코어 동작 설명"]]);
  });
});
