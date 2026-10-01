/**
 * Attaching files from the composer.
 *
 * The attach button used to be `disabled` with the title "Attach -- coming
 * soon". These cover the path a screenshot takes now: picked, shown, sent, and
 * refused out loud when it cannot be.
 *
 * The rule that matters most is the one about a message with files and no
 * words. "What is in this screenshot?" is the obvious use of the feature, and
 * a composer that insists on text makes it the one thing it cannot do.
 *
 * The file input is driven through a real `change` event carrying a `File`,
 * because that is the only path that produces the bytes. jsdom's `File` and
 * `FileReader` are the same ones the webview has, so this exercises the actual
 * read rather than a mock of it.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { act } from "react";

import { Composer, type ModeInfo, type ReasoningInfo } from "./Composer.js";
import type { ModelList } from "./ModelPicker.js";
import { all, click, one, render, setValue } from "./test-render.js";
import { dom } from "./test-dom.js";

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Anything goes", writes: true },
];

const NO_LIST: ModelList | null = null;

async function composer() {
  const sent: { text: string; files: number }[] = [];
  const container = await render(
    <Composer
      busy={false}
      disabled={false}
      model="stub/model"
      modes={MODES}
      mode="build"
      reasoning={null as ReasoningInfo | null}
      onReasoningChange={() => {}}
      onModeChange={() => {}}
      onSend={(text, files) => sent.push({ text, files: files.length })}
      onCancel={() => {}}
      maxToolCalls={10}
      budgetOpen={false}
      onBudgetOpen={() => {}}
      onBudgetClose={() => {}}
      onBudgetChange={() => {}}
      modelList={NO_LIST}
      modelListError={null}
      onModelMenuOpen={() => {}}
      onModelMenuClose={() => {}}
      onModelChange={() => {}}
      onModelListLoad={() => {}}
    />,
  );
  return { container, sent };
}

const fileInput = (container: HTMLElement) =>
  one(container, ".file-input") as HTMLInputElement;

const attachButton = (container: HTMLElement) =>
  one(container, '[aria-label="Attach a file"]') as HTMLButtonElement;

const sendButton = (container: HTMLElement) =>
  one(container, ".send-btn") as HTMLButtonElement;

const messageField = (container: HTMLElement) =>
  one(container, ".composer-inner textarea") as HTMLTextAreaElement;

/** Hand the hidden input a file, the way a picker would. */
async function pick(
  container: HTMLElement,
  name: string,
  type: string,
  body = "x",
): Promise<void> {
  const input = fileInput(container);
  const file = new dom.window.File([body], name, { type });
  await act(async () => {
    // jsdom implements neither `DataTransfer` nor an assignable `input.value`
    // for a picked file, so the FileList is stood in for: the component only
    // ever spreads it and reads `name`/`type`/`size`, and the bytes still come
    // from a real `File` through a real `FileReader`.
    const files = {
      0: file,
      length: 1,
      item: (index: number) => (index === 0 ? file : null),
      [Symbol.iterator]: function* () {
        yield file;
      },
    };
    Object.defineProperty(input, "files", { value: files, configurable: true });
    input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  });
  // FileReader is async even for a Blob this small, and the read is what
  // produces the base64 the core needs.
  await act(async () => {
    await new Promise((resolve) => dom.window.setTimeout(resolve, 0));
  });
}

// --- the button ------------------------------------------------------------
describe("the attach button", () => {
  test("it is not a dead control", async () => {
    const { container } = await composer();
    assert.equal(attachButton(container).disabled, false);
    assert.doesNotMatch(attachButton(container).getAttribute("title") ?? "", /soon/);
  });

  test("it is named for a screen reader", async () => {
    const { container } = await composer();
    assert.equal(attachButton(container).getAttribute("aria-label"), "Attach a file");
  });

  test("the picker behind it is a real file input", async () => {
    const { container } = await composer();
    // The control's whole job is to reach this input; nothing else in the row
    // opens a file dialog.
    assert.ok(fileInput(container), "no file input behind the button");
    assert.equal(fileInput(container).multiple, true);
    assert.match(fileInput(container).getAttribute("accept") ?? "", /image\/png/);
  });

  test("it is disabled when the window is disabled", async () => {
    const container = await render(
      <Composer
        busy={false}
        disabled
        model="stub/model"
        modes={MODES}
        mode="build"
        reasoning={null as ReasoningInfo | null}
        onReasoningChange={() => {}}
        onModeChange={() => {}}
        onSend={() => {}}
        onCancel={() => {}}
        maxToolCalls={10}
        budgetOpen={false}
        onBudgetOpen={() => {}}
        onBudgetClose={() => {}}
        onBudgetChange={() => {}}
        modelList={NO_LIST}
        modelListError={null}
        onModelMenuOpen={() => {}}
        onModelMenuClose={() => {}}
        onModelChange={() => {}}
        onModelListLoad={() => {}}
      />,
    );
    assert.equal(attachButton(container).disabled, true);
  });
});

// --- the strip -------------------------------------------------------------
describe("a file waiting to be sent", () => {
  test("picking one shows it before anything is sent", async () => {
    // Otherwise the only sign an attachment exists is a message that suddenly
    // contains a screenshot, with no way to take it back until after the model
    // has already answered it.
    const { container } = await composer();
    await pick(container, "shot.png", "image/png");
    const items = all(container, ".attach-item");
    assert.equal(items.length, 1);
    assert.match(items[0].textContent ?? "", /shot\.png/);
  });

  test("it is previewed, so the user can see they sent the wrong window", async () => {
    const { container } = await composer();
    await pick(container, "shot.png", "image/png");
    const thumb = one(container, ".attach-thumb") as HTMLImageElement | null;
    assert.ok(thumb, "an image was attached with no way to see which");
    assert.match(thumb.getAttribute("src") ?? "", /^data:image\/png;base64,/);
  });

  test("a text file is named rather than previewed", async () => {
    const { container } = await composer();
    await pick(container, "notes.md", "text/markdown");
    assert.equal(one(container, ".attach-thumb"), null);
    assert.ok(one(container, ".attach-doc"), "a text file has no mark at all");
  });

  test("it can be taken back", async () => {
    const { container } = await composer();
    await pick(container, "shot.png", "image/png");
    await click(one(container, ".attach-remove")!);
    assert.equal(all(container, ".attach-item").length, 0);
  });

  test("the remove button says which file it removes", async () => {
    const { container } = await composer();
    await pick(container, "shot.png", "image/png");
    assert.equal(
      one(container, ".attach-remove")!.getAttribute("aria-label"),
      "Remove shot.png",
    );
  });

  test("several files can go with one message", async () => {
    const { container } = await composer();
    await pick(container, "a.png", "image/png");
    await pick(container, "b.md", "text/markdown");
    assert.equal(all(container, ".attach-item").length, 2);
  });
});

// --- refusal ---------------------------------------------------------------
describe("a file that cannot go", () => {
  test("a PDF is refused in the composer, not logged", async () => {
    // "That file type is not supported" is the whole feedback a user gets, and
    // a console warning is feedback nobody sees.
    const { container } = await composer();
    await pick(container, "spec.pdf", "application/pdf");
    const error = one(container, ".attach-error");
    assert.ok(error, "a refused file failed silently");
    assert.match(error.textContent ?? "", /PDF/);
    assert.match(error.textContent ?? "", /screenshot/);
    assert.equal(all(container, ".attach-item").length, 0);
  });

  test("the refusal is announced, not only coloured", async () => {
    const { container } = await composer();
    await pick(container, "app.exe", "application/x-msdownload");
    assert.equal(one(container, ".attach-error")!.getAttribute("role"), "alert");
  });
});

// --- sending ---------------------------------------------------------------
describe("sending with files", () => {
  test("text and files travel together", async () => {
    const { container, sent } = await composer();
    await pick(container, "shot.png", "image/png");
    await setValue(messageField(container)!, "what is this?");
    await click(sendButton(container)!);
    assert.deepEqual(sent, [{ text: "what is this?", files: 1 }]);
  });

  test("a file with no words is still a message", async () => {
    // The obvious use of the feature. Refusing it would make "what is in this
    // screenshot?" the one thing attachments cannot do.
    const { container, sent } = await composer();
    await pick(container, "shot.png", "image/png");
    await click(sendButton(container)!);
    assert.deepEqual(sent, [{ text: "", files: 1 }]);
  });

  test("the strip is emptied by the send", async () => {
    // A strip that survived the send would quietly reattach the same file to
    // the next message, and the user would only find out from the answer.
    const { container } = await composer();
    await pick(container, "shot.png", "image/png");
    await setValue(messageField(container)!, "first");
    await click(sendButton(container)!);
    assert.equal(all(container, ".attach-item").length, 0);
  });

  test("an empty composer with no files sends nothing", async () => {
    const { container, sent } = await composer();
    await click(sendButton(container)!);
    assert.deepEqual(sent, []);
  });
});
