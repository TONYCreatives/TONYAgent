/**
 * The file viewer: drawing, reading, editing, and the states in between.
 *
 * Three groups, and the third is the one worth having. The first is that it
 * *renders* what the core sent -- lines, colours, a picture, a grid. The
 * second is the read-only contract: while the agent is working there is no
 * editable element at all, and that is asserted rather than assumed, because
 * the cheapest way to add selection to a viewer is to swap the whole body for
 * a textarea. The third is the editing path, which exists only because the
 * user asked for it: the buffer, the dirty state, Ctrl+S, discard, and the
 * refusal to close over unsaved work.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { CodeViewer, type TextFile, type ViewerFile } from "./CodeViewer.js";
import { all, click, one, press, render, rerender, setValue, texts } from "./test-render.js";

const SOURCE: TextFile = {
  kind: "text",
  path: "src/app.ts",
  content: ["// a comment", "const answer = 42;", "", 'export const name = "agent";'].join("\n"),
  total_lines: 4,
  language: "typescript",
  size: 64,
};

const MARKDOWN: TextFile = {
  kind: "text",
  path: "README.md",
  content: "# Title\n\nSome **bold** text.\n",
  total_lines: 3,
  language: "markdown",
  size: 30,
};

const CSV: TextFile = {
  kind: "text",
  path: "data.csv",
  content: "name,count\nwidget,3\ngadget,5\n",
  total_lines: 3,
  language: "csv",
  size: 30,
};

function props(over: Partial<React.ComponentProps<typeof CodeViewer>> = {}) {
  return {
    path: SOURCE.path,
    file: SOURCE as ViewerFile | null,
    loading: false,
    error: null,
    readOnly: true,
    locked: false,
    onToggleReadOnly: () => {},
    saving: false,
    onSave: () => {},
    onDiscard: () => {},
    onDirtyChange: () => {},
    palette: "dark-plus",
    onPalette: () => {},
    onClose: () => {},
    onOpenExternal: () => {},
    ...over,
  };
}

const body = (container: HTMLElement) => one(container, ".code-body")!;
const field = (container: HTMLElement) => one(container, "textarea.code-input");

describe("what the viewer draws", () => {
  test("it numbers every line and shows the file's text", async () => {
    const container = await render(<CodeViewer {...props()} />);
    assert.deepEqual(texts(container, ".code-gutter"), ["1", "2", "3", "4"]);
    assert.match(body(container).textContent ?? "", /const answer = 42;/);
  });

  test("it colours a token from the chosen palette", async () => {
    const container = await render(<CodeViewer {...props()} />);
    const styles = all(container, ".code-text span[style]").map((n) => n.getAttribute("style"));
    assert.ok(
      styles.some((style) => (style ?? "").includes("#6a9955") || (style ?? "").includes("106, 153, 85")),
      `no comment colour in ${styles.join(" | ")}`,
    );
  });

  test("the header names the file, the language and the lock", async () => {
    const container = await render(<CodeViewer {...props()} readOnly />);
    assert.equal(one(container, ".code-path-name")!.textContent, "app.ts");
    assert.equal(one(container, ".code-path-dir")!.textContent, "src/");
    assert.deepEqual(texts(container, ".code-chip"), ["typescript", "🔒 read-only"]);
  });

  test("the theme is chosen in the app's own menu, not the platform's", async () => {
    // The `<select>` this replaces was the one control in the window the OS
    // drew: its popup, its focus ring and its listbox colours are none of them
    // stylable, so the viewer shipped a control that looked like a different
    // application beside buttons that did not. What it has to be instead is the
    // menu the composer's model chip already opens.
    const container = await render(<CodeViewer {...props()} />);
    assert.equal(one(container, ".code-theme select"), null, "a native select is back");

    const trigger = one(container, ".code-theme .chip")!;
    assert.equal(trigger.getAttribute("aria-haspopup"), "dialog");
    // Short on the chip, full in the list -- the chip is 124px of a header that
    // is holding a path, two chips and three buttons.
    assert.match(trigger.textContent ?? "", /^Dark\+\s*▾?$/);

    await click(trigger);
    assert.deepEqual(texts(container, ".modelpicker-item"), [
      "Dark+ (default dark)",
      "Light+ (default light)",
      "Monokai",
    ]);
  });

  test("the footer counts lines, size and language", async () => {
    const container = await render(<CodeViewer {...props()} />);
    const footer = one(container, ".code-footer")!.textContent ?? "";
    assert.match(footer, /4 lines/);
    assert.match(footer, /typescript/);
  });

  test("a failure is shown as the core's sentence", async () => {
    const container = await render(
      <CodeViewer {...props({ file: null, error: "File not found: gone.txt" })} />,
    );
    assert.match(one(container, ".code-notice-error")!.textContent ?? "", /not found/);
  });

  test("a truncated read is announced, and cannot be edited", async () => {
    const container = await render(
      <CodeViewer
        {...props({ file: { ...SOURCE, truncated: true }, readOnly: false })}
      />,
    );
    assert.deepEqual(texts(container, ".code-chip"), ["typescript", "truncated", "🔓 editable"]);
    assert.match(one(container, ".code-notice")!.textContent ?? "", /larger than the viewer's limit/);
    assert.equal(field(container), null, "a partial read must not be saveable");
  });
});

describe("images and files with no preview", () => {
  test("an image is drawn from the bytes the core sent", async () => {
    const container = await render(
      <CodeViewer
        {...props({
          path: "shot.png",
          file: {
            kind: "image",
            path: "shot.png",
            mime: "image/png",
            data: "QUJD",
            size: 2048,
            width: 800,
            height: 600,
            display_width: 800,
            display_height: 600,
            downscaled: false,
          },
        })}
      />,
    );
    const image = one(container, ".code-image img")! as HTMLImageElement;
    assert.equal(image.getAttribute("src"), "data:image/png;base64,QUJD");
    assert.equal(image.getAttribute("alt"), "shot.png");
    assert.match(one(container, ".code-footer")!.textContent ?? "", /800×600/);
    assert.equal(field(container), null);
  });

  test("a downscaled image says what it is showing", async () => {
    const container = await render(
      <CodeViewer
        {...props({
          path: "wide.png",
          file: {
            kind: "image",
            path: "wide.png",
            mime: "image/png",
            data: "QUJD",
            size: 4096,
            width: 8000,
            height: 100,
            display_width: 2048,
            display_height: 26,
            downscaled: true,
          },
        })}
      />,
    );
    assert.match(one(container, ".code-footer")!.textContent ?? "", /shown at 2048×26/);
  });

  test("an SVG draws as an image, with no pixel size to report", async () => {
    // SVG is text, so without the core's special case this would read as
    // `xml` source. The raw text *is* the image: the `<img>` draws it, and
    // the footer says "vector" rather than lying about a 0×0 picture.
    const container = await render(
      <CodeViewer
        {...props({
          path: "mark.svg",
          file: {
            kind: "image",
            path: "mark.svg",
            mime: "image/svg+xml",
            data: "PHN2Zz48L3N2Zz4=",
            size: 16,
            width: 0,
            height: 0,
            display_width: 0,
            display_height: 0,
            downscaled: false,
          },
        })}
      />,
    );
    const image = one(container, ".code-image img")! as HTMLImageElement;
    assert.equal(image.getAttribute("src"), "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=");
    assert.match(one(container, ".code-footer")!.textContent ?? "", /vector/);
  });

  test("a binary file is named with its reason, not rendered as text", async () => {
    const container = await render(
      <CodeViewer
        {...props({
          path: "blob.zip",
          file: {
            kind: "binary",
            path: "blob.zip",
            size: 4096,
            reason: "blob.zip is a binary file, which the viewer does not show.",
          },
        })}
      />,
    );
    assert.deepEqual(texts(container, ".code-chip"), ["no preview", "🔒 read-only"]);
    assert.match(one(container, ".code-notice")!.textContent ?? "", /binary file/);
    assert.equal(one(container, ".code-body"), null);
  });

  test("a binary file offers the OS default app, and names what it opens", async () => {
    // The way out for everything the window cannot draw. Asserts the path,
    // not just the press: a button that opened the wrong file would be
    // worse than none.
    const opened: string[] = [];
    const container = await render(
      <CodeViewer
        {...props({
          path: "blob.zip",
          file: {
            kind: "binary",
            path: "blob.zip",
            size: 4096,
            reason: "blob.zip is a binary file, which the viewer does not show.",
          },
          onOpenExternal: (path) => opened.push(path),
        })}
      />,
    );
    const button = all(container, ".code-notice button").find(
      (b) => (b.textContent ?? "").trim() === "Open externally",
    );
    assert.ok(button, "the binary screen has no Open externally button");
    await click(button);
    assert.deepEqual(opened, ["blob.zip"]);
  });
});

describe("a PDF draws in the native frame", () => {
  const PDF = {
    kind: "pdf",
    path: "spec.pdf",
    mime: "application/pdf",
    data: "JVBERi0xLjQK",
    size: 8192,
  } as const;

  test("the frame carries the bytes, and the chips name it", async () => {
    const container = await render(
      <CodeViewer {...props({ path: "spec.pdf", file: { ...PDF } })} />,
    );
    const frame = one(container, ".code-pdf-frame")! as HTMLIFrameElement;
    assert.equal(
      frame.getAttribute("src"),
      "data:application/pdf;base64,JVBERi0xLjQK",
    );
    assert.equal(frame.getAttribute("title"), "spec.pdf");
    assert.deepEqual(texts(container, ".code-chip"), ["pdf", "🔒 read-only"]);
    assert.equal(field(container), null);
  });

  test("the fallback names the file it would open", async () => {
    // Where the frame cannot draw, the OS default app can. Asserts the
    // path, for the reason the binary test gives.
    const opened: string[] = [];
    const container = await render(
      <CodeViewer
        {...props({
          path: "spec.pdf",
          file: { ...PDF },
          onOpenExternal: (path) => opened.push(path),
        })}
      />,
    );
    const button = all(container, ".code-pdf-bar button").find(
      (b) => (b.textContent ?? "").trim() === "Open externally",
    );
    assert.ok(button, "the PDF bar has no Open externally button");
    await click(button);
    assert.deepEqual(opened, ["spec.pdf"]);
  });
});

describe("audio and video play in the native tags", () => {
  test("an mp3 draws a player carrying the bytes", async () => {
    const container = await render(
      <CodeViewer
        {...props({
          path: "take.mp3",
          file: {
            kind: "media",
            media: "audio",
            path: "take.mp3",
            mime: "audio/mpeg",
            data: "SUQz",
            size: 2048,
          },
        })}
      />,
    );
    const player = one(container, ".code-media audio")! as HTMLAudioElement;
    assert.equal(player.getAttribute("src"), "data:audio/mpeg;base64,SUQz");
    assert.ok(player.hasAttribute("controls"), "a player with no controls plays nothing");
    assert.deepEqual(texts(container, ".code-chip"), ["audio", "🔒 read-only"]);
    assert.equal(field(container), null);
  });

  test("an mp4 draws a player, not an audio tag", async () => {
    const container = await render(
      <CodeViewer
        {...props({
          path: "clip.mp4",
          file: {
            kind: "media",
            media: "video",
            path: "clip.mp4",
            mime: "video/mp4",
            data: "AAAA",
            size: 4096,
          },
        })}
      />,
    );
    const player = one(container, ".code-media video")! as HTMLVideoElement;
    assert.equal(player.getAttribute("src"), "data:video/mp4;base64,AAAA");
    assert.deepEqual(texts(container, ".code-chip"), ["video", "🔒 read-only"]);
  });
});

describe("documents with a rendered view", () => {
  test("markdown opens on its preview, with the source one press away", async () => {
    const container = await render(<CodeViewer {...props({ path: "README.md", file: MARKDOWN })} />);

    assert.deepEqual(texts(container, ".code-viewswitch button"), ["Source", "Preview"]);
    const rendered = one(container, ".code-preview")!;
    assert.equal(one(rendered, ".md-h1")!.textContent, "Title");
    assert.match(rendered.textContent ?? "", /bold/);

    await click(all(container, ".code-viewswitch button")[0]);
    assert.match(body(container).textContent ?? "", /# Title/);
  });

  test("a markdown table renders as a grid, honouring alignment", async () => {
    // Parser and renderer together, through the same preview the markdown
    // test above opens on: a table as a paragraph of pipes is the failure.
    const container = await render(
      <CodeViewer
        {...props({
          path: "README.md",
          file: {
            kind: "text",
            path: "README.md",
            content: "| name | count |\n| ---- | ----: |\n| widget | 3 |",
            total_lines: 3,
            language: "markdown",
            size: 48,
          },
        })}
      />,
    );
    assert.deepEqual(texts(container, ".md-table th"), ["name", "count"]);
    assert.deepEqual(texts(container, ".md-table tbody td"), ["widget", "3"]);
    const cells = all(container, ".md-table th");
    assert.equal((cells[1] as HTMLElement).style.textAlign, "right");
  });

  test("a csv can be shown as a table", async () => {
    const container = await render(<CodeViewer {...props({ path: "data.csv", file: CSV })} />);
    assert.deepEqual(texts(container, ".code-viewswitch button"), ["Source", "Table"]);

    await click(all(container, ".code-viewswitch button")[1]);
    assert.deepEqual(texts(container, ".code-table th"), ["name", "count"]);
    assert.deepEqual(texts(container, ".code-table tbody td"), ["widget", "3", "gadget", "5"]);
  });

  test("a plain text file offers no preview toggle at all", async () => {
    const container = await render(<CodeViewer {...props()} />);
    assert.equal(one(container, ".code-viewswitch"), null);
  });
});

describe("read-only, and the switch that leaves it", () => {
  test("read-only means there is nothing to type into", async () => {
    const container = await render(<CodeViewer {...props({ readOnly: true })} />);
    assert.equal(field(container), null);
    assert.equal(body(container).getAttribute("aria-readonly"), "true");
    assert.equal(body(container).getAttribute("role"), "textbox");
  });

  test("the agent working keeps it read-only even when the switch is off", async () => {
    // The lock is the window's, not the user's: a file being written
    // underneath a caret is worse than a disabled one.
    const container = await render(<CodeViewer {...props({ readOnly: false, locked: true })} />);
    assert.equal(field(container), null);
    assert.match(one(container, ".code-lock")!.textContent ?? "", /agent working/);
    assert.equal(container.querySelector("section")!.getAttribute("data-locked"), "true");
  });

  test("the toggle is disabled while the agent works", async () => {
    const container = await render(<CodeViewer {...props({ readOnly: true, locked: true })} />);
    const toggle = all(container, "button").find((b) => b.textContent === "Edit")!;
    assert.equal((toggle as HTMLButtonElement).disabled, true);
  });

  test("the switch reports upward, both ways", async () => {
    const asked: boolean[] = [];
    const container = await render(
      <CodeViewer {...props({ readOnly: true, onToggleReadOnly: (next) => asked.push(next) })} />,
    );
    await click(all(container, "button").find((b) => b.textContent === "Edit")!);
    assert.deepEqual(asked, [false], "the Edit button must ask to leave read-only");

    const editable = await render(
      <CodeViewer {...props({ readOnly: false, onToggleReadOnly: (next) => asked.push(next) })} />,
    );
    await click(all(editable, "button").find((b) => b.textContent === "Lock")!);
    assert.deepEqual(asked, [false, true]);
  });
});

describe("editing", () => {
  const editable = { readOnly: false, locked: false };

  test("the field holds the file, and typing reports a dirty buffer", async () => {
    const changes: boolean[] = [];
    const container = await render(
      <CodeViewer {...props({ ...editable, onDirtyChange: (dirty) => changes.push(dirty) })} />,
    );
    const area = field(container)! as HTMLTextAreaElement;
    assert.equal(area.value, SOURCE.content);
    assert.equal(area.getAttribute("spellcheck"), "false", "code is not prose to spellcheck");

    await setValue(area, "changed\n");

    assert.equal((field(container) as HTMLTextAreaElement).value, "changed\n");
    assert.ok(changes.includes(true), "the parent was never told the buffer is dirty");
    assert.match(one(container, ".code-dirty")!.textContent ?? "", /•/);
  });

  test("Save is disabled until something changed, then sends the buffer", async () => {
    const saved: string[] = [];
    const container = await render(<CodeViewer {...props({ ...editable, onSave: (c) => saved.push(c) })} />);

    const saveButton = () => all(container, "button").find((b) => b.textContent === "Save")!;
    assert.equal((saveButton() as HTMLButtonElement).disabled, true);

    await setValue(field(container) as HTMLTextAreaElement, "new text\n");
    assert.equal((saveButton() as HTMLButtonElement).disabled, false);

    await click(saveButton());
    assert.deepEqual(saved, ["new text\n"]);
  });

  test("Ctrl+S saves, and does not reach the webview's own save", async () => {
    const saved: string[] = [];
    const container = await render(<CodeViewer {...props({ ...editable, onSave: (c) => saved.push(c) })} />);
    await setValue(field(container) as HTMLTextAreaElement, "typed\n");

    const event = await press("s", field(container)!, { ctrlKey: true });
    assert.deepEqual(saved, ["typed\n"]);
    assert.equal(event.defaultPrevented, true, "the browser's save dialog was left to open");
  });

  test("a plain 's' types rather than saving", async () => {
    const saved: string[] = [];
    const container = await render(<CodeViewer {...props({ ...editable, onSave: (c) => saved.push(c) })} />);
    await press("s", field(container)!);
    assert.deepEqual(saved, []);
  });

  test("Discard is offered only while dirty, and reports upward", async () => {
    let discarded = 0;
    const container = await render(
      <CodeViewer {...props({ ...editable, onDiscard: () => (discarded += 1) })} />,
    );
    const discard = () => all(container, "button").find((b) => b.textContent === "Discard");
    assert.equal(discard(), undefined, "nothing to discard on a clean buffer");

    await setValue(field(container) as HTMLTextAreaElement, "typed\n");
    await click(discard()!);
    assert.equal(discarded, 1);
  });

  test("closing is refused while there are unsaved changes", async () => {
    let closed = 0;
    const container = await render(<CodeViewer {...props({ ...editable, onClose: () => (closed += 1) })} />);

    await setValue(field(container) as HTMLTextAreaElement, "typed\n");
    const close = one(container, ".code-close")! as HTMLButtonElement;
    assert.equal(close.disabled, true, "closing would silently discard the buffer");
    await click(close);
    assert.equal(closed, 0);
  });

  test("a save that comes back with new content clears the buffer", async () => {
    // The parent hands the viewer what is now on disk; the draft is keyed on
    // that content, so clearing is what the new file *is* rather than a
    // separate instruction the caller could forget.
    const container = await render(<CodeViewer {...props({ ...editable })} />);
    await setValue(field(container) as HTMLTextAreaElement, "typed\n");
    assert.ok(one(container, ".code-dirty"), "expected a dirty marker first");

    // `rerender`, not a second `render`: this is the same viewer being handed
    // the saved file, which is the thing under test. A fresh mount would pass
    // this assertion without any of the behaviour existing.
    await rerender(
      <CodeViewer {...props({ ...editable, file: { ...SOURCE, content: "typed\n" } })} />,
    );
    assert.equal(one(container, ".code-dirty"), null, "the dirty marker survived the save");
    assert.equal((field(container) as HTMLTextAreaElement).value, "typed\n");
  });

  test("read-only files grow no editor at all", async () => {
    const container = await render(<CodeViewer {...props({ readOnly: true })} />);
    assert.equal(field(container), null);
    assert.equal(all(container, "button").some((b) => b.textContent === "Save"), false);
  });
});
