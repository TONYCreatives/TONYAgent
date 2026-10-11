/**
 * Pasting a picture into the composer.
 *
 * The file picker was the only way to attach an image, which made the most
 * obvious case -- "here is a screenshot of the bug" -- the one case with the
 * most steps. Ctrl+V now takes the images off the clipboard and puts them in
 * the pending strip.
 *
 * Three things are worth pinning, and the middle one is the dangerous one:
 *
 *   1. an image on the clipboard becomes a pending attachment, named for where
 *      it came from rather than whatever the source app called it;
 *   2. **a paste with no image is left alone.** `preventDefault` before the
 *      check is the bug this whole feature invites: it makes Ctrl+V do nothing
 *      in a text field, which is the most ordinary thing a text field does;
 *   3. the two routes into the strip share one routine, so a paste and a pick
 *      cannot disagree about the five-file limit.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { act } from "react";

import { Composer, type ModeInfo } from "./Composer.js";
import { imagesFromClipboard } from "./attachments.js";
import { all, one, render, setValue } from "./test-render.js";
import { dom } from "./test-dom.js";

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Anything goes", writes: true },
];

async function composer() {
  const sent: { text: string; names: string[] }[] = [];
  const container = await render(
    <Composer
      busy={false}
      disabled={false}
      modes={MODES}
      mode="build"
      onModeChange={() => {}}
      onSend={(text, files) => sent.push({ text, names: files.map((f) => f.name) })}
      onCancel={() => {}}
      maxToolCalls={10}
      budgetOpen={false}
      onBudgetOpen={() => {}}
      onBudgetClose={() => {}}
      onBudgetChange={() => {}}
    />,
  );
  return { container, sent };
}

const field = (c: HTMLElement) =>
  one(c, ".composer-inner textarea") as HTMLTextAreaElement;

/** A clipboard holding images, or plain text, as the real one would. */
function clipboard(images: { name: string; type: string; body?: string }[], text = "") {
  const items = images.map((img) => ({
    kind: "file",
    type: img.type,
    getAsFile: () =>
      new dom.window.File([img.body ?? "PNG"], img.name, { type: img.type }),
  }));
  if (text) {
    items.push({
      kind: "string",
      type: "text/plain",
      getAsFile: () => null,
    } as unknown as (typeof items)[number]);
  }
  return { items, getData: (t: string) => (t === "text/plain" ? text : ""), files: [] };
}

/**
 * Fire a paste and wait for whatever it produces.
 *
 * Two things this has to get right, both learned from `ComposerAttach`'s
 * `pick()`:
 *
 *   * React's synthetic event reads `clipboardData` off the native one, so the
 *     object goes straight onto the DOM event.
 *   * The attachment is read through the component's own `FileReader`, and
 *     `onload` lands on a task rather than on the microtask queue `act` drains.
 *     Dispatching and asserting in the same turn reads an empty strip. So poll
 *     for the consequence, with one `act` per poll -- React flushes when an
 *     `act` scope *ends*, so a loop inside one scope would never see the DOM.
 *
 * `expect` says what the caller is about to assert on, so a paste that
 * produces neither an item nor an error is reported as such instead of
 * surfacing later as a confusing count.
 */
async function paste(
  c: HTMLElement,
  data: ReturnType<typeof clipboard>,
  expect: "item" | "nothing" = "item",
): Promise<{ defaultPrevented: boolean }> {
  const el = field(c);
  const event = new dom.window.Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: data });
  let prevented = false;
  await act(async () => {
    el.dispatchEvent(event);
    prevented = event.defaultPrevented;
  });

  if (expect === "nothing") return { defaultPrevented: prevented };

  // Wait for the paste to *settle*, not merely to produce something.
  //
  // It used to break as soon as an attachment or an error appeared, and a paste
  // that is over the limit produces **both**: `acceptFiles` sets the error before
  // it starts reading, and the attachments land after `readFile` resolves. So the
  // loop could stop on the error and the caller would count zero files -- an
  // intermittent failure that read as "the limit was ignored". Measured: `0 !== 5`.
  //
  // Two ticks with nothing changing is the paste being done; one is not, because
  // the error is exactly one tick ahead of the files.
  const deadline = Date.now() + 5000;
  const snapshot = () =>
    `${c.querySelectorAll(".attach-item").length}${
      c.querySelector(".attach-error") ? "e" : "-"
    }`;
  let last = "";
  let still = 0;
  for (;;) {
    await act(async () => {
      await new Promise((resolve) => dom.window.setTimeout(resolve, 5));
    });
    const now = snapshot();
    still = now === last ? still + 1 : 0;
    last = now;
    if (still >= 2 && now !== "0-") break;
    if (Date.now() > deadline) {
      throw new Error("a paste produced neither an attachment nor an error");
    }
  }
  return { defaultPrevented: prevented };
}

const stripNames = (c: HTMLElement) =>
  all(c, ".attach-strip li").map((li) => (li.textContent ?? "").trim());

describe("pasting a picture", () => {
  test("an image on the clipboard becomes a pending attachment", async () => {
    const { container } = await composer();
    await paste(container, clipboard([{ name: "image.png", type: "image/png" }]));

    const strip = all(container, ".attach-strip li");
    assert.equal(strip.length, 1, "the pasted image is not in the strip");
    assert.match(stripNames(container)[0], /pasted-1\.png/);
  });

  test("it is named for the paste, not for whatever the app called it", async () => {
    // Chrome says `image.png`, Word says `image2.png`, a browser gives a
    // fragment-laden name. None of them says anything, and two of them pasted
    // in a row would collide.
    const { container } = await composer();
    await paste(
      container,
      clipboard([
        { name: "image2.png", type: "image/png" },
        { name: "Screenshot 2026-10-04 at 14.22.51.png", type: "image/png" },
      ]),
    );
    assert.deepEqual(
      all(container, ".attach-strip li").map((li) => li.querySelector("img") !== null),
      [true, true],
    );
    const names = stripNames(container);
    assert.match(names[0], /pasted-1\.png/);
    assert.match(names[1], /pasted-2\.png/);
  });

  test("two pastes do not both end up called the same thing", async () => {
    // `removeAttachment` deletes by name, so two attachments sharing one name
    // means one click on the first removes both.
    const { container } = await composer();
    await paste(container, clipboard([{ name: "image.png", type: "image/png" }]));
    await paste(container, clipboard([{ name: "image.png", type: "image/png" }]));

    const names = all(container, ".attach-strip li").map(
      (li) => li.querySelector("strong, b, span")?.textContent ?? li.textContent ?? "",
    );
    const joined = names.join("|");
    assert.match(joined, /pasted-1\.png/);
    assert.match(joined, /pasted-1-2\.png|pasted-2\.png/, `both were called the same: ${joined}`);
  });

  test("a paste with no picture is left to the browser", async () => {
    // The one that matters most: swallowing this would make Ctrl+V do nothing
    // in a text field.
    const { container } = await composer();
    await setValue(field(container), "before");
    const { defaultPrevented } = await paste(container, clipboard([], "pasted words"), "nothing");
    assert.equal(defaultPrevented, false, "a text paste was swallowed");
    assert.equal(all(container, ".attach-strip li").length, 0, "text became an attachment");
    assert.equal(field(container).value, "before");
  });

  test("a picture and words together take the picture", async () => {
    // Copying an image out of a browser puts an image and text/html on the
    // clipboard. The picture is what was asked for.
    const { container } = await composer();
    const { defaultPrevented } = await paste(
      container,
      clipboard([{ name: "image.png", type: "image/png" }], "<img src=x>"),
    );
    assert.equal(defaultPrevented, true);
    assert.equal(all(container, ".attach-strip li").length, 1);
  });

  test("a pasted image can be sent, and can go with no words", async () => {
    // "What is wrong with this?" with a screenshot and no text is the case
    // that motivates the whole thing.
    const { container, sent } = await composer();
    await paste(container, clipboard([{ name: "shot.png", type: "image/png" }]));
    await act(async () => {
      (one(container, ".send-btn") as HTMLButtonElement).click();
    });
    assert.equal(sent.length, 1, `the message was not sent: ${JSON.stringify(sent)}`);
    assert.match(sent[0].names[0], /pasted-1\.png/);
  });

  test("the file limit is the same one the picker obeys", async () => {
    // One routine behind both, so a paste cannot be a way around the limit.
    const { container } = await composer();
    const many = Array.from({ length: 7 }, (_, i) => ({
      name: `image${i}.png`,
      type: "image/png",
    }));
    await paste(container, clipboard(many));
    assert.equal(all(container, ".attach-strip li").length, 5, "the paste ignored the limit");
    assert.match(
      one(container, ".attach-error")?.textContent ?? "",
      /Only 5 files/,
    );
  });
});

describe("reading the clipboard", () => {
  test("no clipboard is no images", () => {
    assert.deepEqual(imagesFromClipboard(null), []);
  });

  test("a clipboard with no items is no images", () => {
    assert.deepEqual(imagesFromClipboard({ items: [] } as unknown as DataTransfer), []);
  });

  test("text items are left alone", () => {
    const data = clipboard([], "just words");
    assert.deepEqual(imagesFromClipboard(data as unknown as DataTransfer), []);
  });

  test("one image in, one named file out", () => {
    // The happy path, which the empty-list cases above never asked for. It is
    // here because a reader that only ever returns [] passes every other test
    // in this describe block and leaves the composer looking broken.
    const [file] = imagesFromClipboard(
      clipboard([{ name: "image.png", type: "image/png" }]) as unknown as DataTransfer,
    );
    assert.equal(file.name, "pasted-1.png");
    assert.equal(file.type, "image/png");
    assert.ok(file.size > 0, "the file came back empty, so nothing could be sent");
  });

  test("several images are numbered, so two pastes do not collide", () => {
    const files = imagesFromClipboard(
      clipboard([
        { name: "image.png", type: "image/png" },
        { name: "image2.png", type: "image/jpeg" },
        { name: "shot.gif", type: "image/gif" },
      ]) as unknown as DataTransfer,
    );
    // The extension comes from the *type*, not the source name: `image2.png`
    // holding a JPEG would otherwise be saved as a PNG that is not one.
    assert.deepEqual(files.map((f) => f.name), ["pasted-1.png", "pasted-2.jpg", "pasted-3.gif"]);
  });

  test("an image type we have no extension for still gets a name", () => {
    const [file] = imagesFromClipboard(
      clipboard([{ name: "x", type: "image/avif" }]) as unknown as DataTransfer,
    );
    // No extension rather than a wrong one: the mime travels separately and is
    // what the core checks.
    assert.equal(file.name, "pasted-1");
    assert.equal(file.type, "image/avif");
  });

  test("an image item whose file could not be read is skipped, not faked", () => {
    const data = {
      items: [{ kind: "file", type: "image/png", getAsFile: () => null }],
    } as unknown as DataTransfer;
    assert.deepEqual(imagesFromClipboard(data), []);
  });
});