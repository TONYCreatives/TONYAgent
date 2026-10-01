/**
 * Attachments on the way to the core.
 *
 * The bytes go into the message rather than a folder the agent is told about.
 * That is the whole design decision, and it has one consequence worth naming:
 * the window needs the file's *contents*, not its path, so the read happens
 * here in the webview and the file crosses the pipe as base64.
 *
 * The native dialog in `dialog.ts` is for folders and stays that way -- it
 * hands back a path because the core needs to give one to the sandbox. A
 * `<input type="file">` hands back a `File`, which is exactly what this needs,
 * and it costs no Rust command, no capability and no rebuild.
 *
 * The size and type limits are mirrored in the core, not instead of it. They
 * are here so a user finds out before a multi-megabyte read, and they are
 * there because the window is a rendering layer and not a trust boundary.
 */

/** One file waiting to be sent. */
export interface PendingAttachment {
  name: string;
  /** The size shown next to the name, and checked against the limit. */
  size: number;
  /** A data URL, for the image preview. Empty for a text file. */
  preview: string;
  kind: "image" | "text";
  mime: string;
  /** base64, no prefix. What the core expects. */
  data: string;
}

/** Mirrors `attachments.MAX_ATTACHMENTS` in the core. */
export const MAX_ATTACHMENTS = 5;

/** Mirrors `attachments.MAX_ATTACHMENT_BYTES`. */
export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

/** Mirrors `attachments.TEXT_MIME_TYPES`, by extension. */
const TEXT_EXTENSIONS = [
  ".txt", ".md", ".csv", ".html", ".json",
  ".py", ".yaml", ".yml", ".xml", ".sh",
];

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

export function isSupported(file: { name: string; type: string }): boolean {
  if ((file.type || "").startsWith("image/")) return true;
  if (TEXT_EXTENSIONS.includes(extensionOf(file.name))) return true;
  return false;
}

export function fileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

/** Why this file cannot be attached, or "" if it can. */
export function rejectionReason(file: { name: string; type: string; size: number }): string {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return `${file.name} is ${fileSize(file.size)}, over the ${fileSize(
      MAX_ATTACHMENT_BYTES,
    )} limit for one file.`;
  }
  if (extensionOf(file.name) === ".pdf") {
    return `${file.name} is a PDF, which this endpoint cannot read inline. Copy the text out, or attach a screenshot.`;
  }
  if (!isSupported(file)) {
    return `${file.name} is a ${file.type || "unknown"} file. Attach an image (PNG, JPEG, WebP, GIF) or a text file.`;
  }
  return "";
}

/** Read one file into the shape the core's `send` expects. */
export function readFile(file: File): Promise<PendingAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`${file.name} could not be read.`));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      const comma = result.indexOf(",");
      // A data URL is `data:<mime>;base64,<payload>`. The core takes the
      // payload alone, so the prefix is stripped here rather than making the
      // core know about data URLs it never asked for.
      const base64 = comma === -1 ? "" : result.slice(comma + 1);
      const isImage = (file.type || "").startsWith("image/");
      resolve({
        name: file.name,
        size: file.size,
        preview: isImage ? result : "",
        kind: isImage ? "image" : "text",
        mime: file.type || "",
        data: base64,
      });
    };
    reader.readAsDataURL(file);
  });
}

/** The `attachments` payload for the `send` RPC. */
export function toWire(attachments: PendingAttachment[]) {
  return attachments.map((a) => ({ name: a.name, mime: a.mime, data: a.data }));
}

/** One line for the transcript bubble, matching the core's own wording. */
export function summaryLine(attachments: PendingAttachment[]): string {
  if (attachments.length === 0) return "";
  const names = attachments.map((a) => a.name).join(", ");
  return `Attached ${attachments.length} ${
    attachments.length === 1 ? "file" : "files"
  }: ${names}`;
}

/**
 * The text of a saved message, whether its content is a string or parts.
 *
 * A conversation with an attachment in it is saved with content parts, and
 * reads back as parts. Handing that array straight to a component expecting a
 * string renders `[object Object]` in the user's own history -- a bubble that
 * used to be a screenshot now shows nonsense. The image part contributes
 * nothing, so an image-only message comes back with no words, which is the
 * honest answer: the bytes are not in the transcript, only the fact of them.
 */
export function textFromContent(content: string | unknown[] | null | undefined): string {
  if (content === null || content === undefined) return "";
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const pieces: string[] = [];
  for (const part of content) {
    if (!part || typeof part !== "object") continue;
    const value = (part as Record<string, unknown>).text;
    if (typeof value !== "string") continue;
    // A text file is stored wrapped in a <file> element so the model can tell
    // which file it is reading. The wrapper is wire formatting, not something
    // to put in front of the person who attached it.
    const unwrapped = value.replace(/^<file name="[^"]*">\n?/, "").replace(/\n?<\/file>$/, "");
    if (unwrapped.trim()) pieces.push(unwrapped);
  }
  return pieces.join("\n\n");
}
