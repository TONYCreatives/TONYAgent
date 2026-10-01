/**
 * Attachments, from the picker to the wire.
 *
 * The design decision under test is that the bytes go *in* the message rather
 * than the path going beside it. That is what makes the model see a screenshot
 * instead of being told one exists, and it is why the picker is a file input
 * and not the native dialog in `dialog.ts` -- that one hands back a path
 * because the core gives one to the sandbox, and this needs the bytes.
 *
 * What the tests pin, beyond the happy path:
 *
 * - **The strip exists before the send.** Otherwise the only sign a file went
 *   out is a message that suddenly contains a screenshot, with no way to take
 *   it back until after the model has answered it.
 * - **A refusal is shown.** "This type is not supported" is the whole feedback
 *   a user gets, and a console warning is feedback nobody sees.
 * - **A message with files and no words is a message.** "What is in this
 *   screenshot?" is the obvious use of the feature, and requiring text would
 *   make it the one thing the feature cannot do.
 * - **A saved message reads back as words.** A conversation with an attachment
 *   is stored as content parts; handing that array to a component expecting a
 *   string renders `[object Object]` in the user's own history.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  MAX_ATTACHMENTS,
  MAX_ATTACHMENT_BYTES,
  fileSize,
  isSupported,
  rejectionReason,
  summaryLine,
  textFromContent,
  toWire,
  type PendingAttachment,
} from "./attachments.js";

const pending = (name: string, over: Partial<PendingAttachment> = {}): PendingAttachment => ({
  name,
  size: 1024,
  preview: "",
  kind: "text",
  mime: "text/plain",
  data: "aGVsbG8=",
  ...over,
});

// --- what will go ----------------------------------------------------------
describe("what can be attached", () => {
  test("images are accepted by their declared type", () => {
    assert.equal(isSupported({ name: "shot.png", type: "image/png" }), true);
    assert.equal(isSupported({ name: "shot.jpeg", type: "image/jpeg" }), true);
    assert.equal(isSupported({ name: "shot.webp", type: "image/webp" }), true);
  });

  test("text files are accepted by their extension", () => {
    // A browser on Windows reports "" for a .py file often enough that
    // refusing on an empty type would reject most of what a developer would
    // want to attach.
    for (const name of ["notes.md", "script.py", "data.csv", "config.yaml", "run.sh"]) {
      assert.equal(isSupported({ name, type: "" }), true, name);
    }
  });

  test("a binary is not", () => {
    assert.equal(isSupported({ name: "app.exe", type: "application/x-msdownload" }), false);
    assert.equal(isSupported({ name: "clip.mp4", type: "video/mp4" }), false);
  });

  test("the type limits are the core's, not a second opinion", () => {
    // Mirrored so a user finds out before a multi-megabyte read. The core
    // enforces them anyway, because the window is not a trust boundary -- so
    // these being equal is a convenience, and these being wrong is not fatal.
    assert.equal(MAX_ATTACHMENTS, 5);
    assert.equal(MAX_ATTACHMENT_BYTES, 5 * 1024 * 1024);
  });
});

// --- what is refused -------------------------------------------------------
describe("what is refused", () => {
  test("a PDF is refused with a next step", () => {
    // OpenRouter's chat completions does not take a document part. "Copy the
    // text out" is a thing the user can do; "unsupported" is not.
    const reason = rejectionReason({ name: "spec.pdf", type: "application/pdf", size: 100 });
    assert.match(reason, /PDF/);
    assert.match(reason, /screenshot/);
  });

  test("an oversized file names its own size and the limit", () => {
    const reason = rejectionReason({
      name: "huge.png",
      type: "image/png",
      size: MAX_ATTACHMENT_BYTES + 1,
    });
    assert.match(reason, /huge\.png/);
    assert.match(reason, /limit/);
  });

  test("a file at the limit is not refused", () => {
    assert.equal(
      rejectionReason({ name: "ok.png", type: "image/png", size: MAX_ATTACHMENT_BYTES }),
      "",
    );
  });

  test("an unknown type says what will work", () => {
    const reason = rejectionReason({ name: "mystery", type: "", size: 10 });
    assert.match(reason, /image/i);
    assert.match(reason, /text/i);
  });

  test("a file that can go is refused for nothing", () => {
    assert.equal(rejectionReason({ name: "a.png", type: "image/png", size: 10 }), "");
    assert.equal(rejectionReason({ name: "a.md", type: "", size: 10 }), "");
  });

  test("sizes are readable at each scale", () => {
    assert.equal(fileSize(512), "512 B");
    assert.equal(fileSize(2048), "2 KB");
    assert.equal(fileSize(5 * 1024 * 1024), "5.0 MB");
  });
});

// --- the wire --------------------------------------------------------------
describe("the attachment payload", () => {
  test("it carries the base64 without a data-URL prefix", () => {
    // The core takes the payload alone. Making it know about data URLs it
    // never asked for would be the frontend's formatting leaking inward.
    assert.deepEqual(toWire([pending("a.png")]), [
      { name: "a.png", mime: "text/plain", data: "aGVsbG8=" },
    ]);
  });

  test("the preview is not sent", () => {
    // The preview is a data URL of the same bytes. Sending it would put the
    // file in the message twice.
    const wire = toWire([pending("a.png", { preview: "data:image/png;base64,AAAA" })]);
    assert.equal(wire[0].data, "aGVsbG8=");
  });

  test("an empty list is an empty list", () => {
    assert.deepEqual(toWire([]), []);
  });
});

// --- the transcript --------------------------------------------------------
describe("what the transcript says", () => {
  test("one file is named", () => {
    assert.match(summaryLine([pending("shot.png")]), /1 file: shot\.png/);
  });

  test("several are named, and counted", () => {
    const line = summaryLine([pending("a.png"), pending("b.md")]);
    assert.match(line, /2 files/);
    assert.match(line, /a\.png/);
    assert.match(line, /b\.md/);
  });

  test("nothing attached says nothing", () => {
    assert.equal(summaryLine([]), "");
  });
});

describe("reading a saved message back", () => {
  test("a plain string comes back unchanged", () => {
    assert.equal(textFromContent("hello"), "hello");
  });

  test("an absent message is empty, not undefined", () => {
    assert.equal(textFromContent(null), "");
    assert.equal(textFromContent(undefined), "");
  });

  test("content parts come back as their text", () => {
    // A conversation with an attachment in it is saved as parts and reads back
    // as parts. Handing that array to a component expecting a string renders
    // `[object Object]` in the user's own history.
    const content = [
      { type: "text", text: "what is this?" },
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
    ];
    assert.equal(textFromContent(content), "what is this?");
  });

  test("a text file's wire wrapper is not shown to the reader", () => {
    // The <file> element is there so the *model* can tell which file it is
    // reading. Putting it in front of the person who attached it would be wire
    // formatting leaking into the UI.
    const content = [{ type: "text", text: '<file name="report.md">\n42\n</file>' }];
    assert.equal(textFromContent(content), "42");
  });

  test("an image-only message reads back empty rather than as base64", () => {
    // The bytes are not in the transcript, only the fact that there were some.
    // Rendering the data URL would put a wall of base64 in the user's history.
    const content = [{ type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } }];
    assert.equal(textFromContent(content), "");
  });

  test("several text parts are joined", () => {
    const content = [
      { type: "text", text: "one" },
      { type: "text", text: "two" },
    ];
    assert.equal(textFromContent(content), "one\n\ntwo");
  });

  test("something that is neither a string nor parts does not throw", () => {
    assert.equal(textFromContent(42 as never), "");
    assert.equal(textFromContent([null, 7, "x"] as never), "");
  });
});
