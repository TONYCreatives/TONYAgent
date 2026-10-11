"""Attachments: turning picked files into something the model can see.

The core had no attachment path at all. `_h_send` read ``params["text"]`` and
`session.send` took a string, so the only way to talk to the agent about a
file was to name its path and hope it had a tool that could read it. That is a
different product: the model is told a file exists and has to ask for it, which
costs an extra round trip and fails in a new place each time. This module
builds the content parts an OpenAI-compatible endpoint already accepts, so the
bytes go in the message and the model sees the file.

Validation lives here, not in the frontend. The window is not the trust
boundary -- a message is a JSON object on a pipe, and anything that can write
to that pipe can claim a 400MB attachment is 4KB. The limits below are the
ones that keep a request inside what a provider will accept and inside what a
human meant to attach.

PDF is refused rather than half-supported. OpenRouter's chat completions does
not accept a document part, so a PDF would have to become text, and a PDF made
of text is usually not what someone attaching it wants -- they want the layout,
the diagrams, the scanned signature. Saying no is more useful than a lossy
conversion the user cannot see.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

#: Image types a vision model accepts on the wire.
IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)

#: Text types worth inlining whole. Deliberately not a list of every type that
#: exists: binary formats read as mojibake and cost tokens for nothing, and
#: the honest answer for those is the refusal below.
TEXT_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "text/x-python",
        "application/json",
        "application/x-yaml",
        "application/yaml",
        "application/xml",
        "application/x-sh",
    }
)

#: Extensions mapped to a MIME type, for the files a browser reports without
#: one. A `<input type="file">` on Windows reports `""` for a `.py` file often
#: enough that refusing on an empty type would reject most source files.
EXTENSION_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".html": "text/html",
    ".json": "application/json",
    ".py": "text/x-python",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".xml": "application/xml",
    ".sh": "application/x-sh",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

#: How many files one message may carry. A message with twenty screenshots is
#: a mistake, and a vision model bills every one of them.
MAX_ATTACHMENTS = 5

#: Bytes per file, after base64 decoding. OpenRouter accepts large images but
#: a phone photo is a few megabytes and ten of them is a request the provider
#: will refuse with a much less useful message than this one.
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

#: Total bytes across one message, for the same reason with several files.
MAX_TOTAL_BYTES = 12 * 1024 * 1024

#: Characters of a text file kept. A 2MB log file is not a question, it is an
#: accident, and sending it whole costs a fortune and answers nothing.
MAX_TEXT_CHARS = 100_000


class AttachmentError(ValueError):
    """An attachment the core refuses, with a reason the user can act on."""


def _extension_of(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def resolve_mime(raw: Any, name: str) -> str:
    """The MIME type to treat this file as.

    Falls back to the extension, then to the name itself. A browser is
    unreliable about the type of a file it did not create -- on Windows a
    ``.py`` arrives as an empty string often enough that refusing on that
    would reject most of what a developer would want to attach.
    """
    if isinstance(raw, str) and raw.strip():
        return raw.split(";")[0].strip().lower()
    return EXTENSION_MIME_TYPES.get(_extension_of(name), "")


def _decode_image(data: str, name: str) -> bytes:
    """base64 to bytes, with the failure named in terms the user can act on."""
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError(
            f"{name} could not be read as an image; the file may be corrupt."
        ) from exc


def validate(raw: Any) -> list[dict[str, Any]]:
    """Check one incoming attachment list, and return it in internal form.

    Raises :class:`AttachmentError` with a sentence the window can show. Every
    check that can be made here is made here rather than in the frontend,
    because the frontend is a rendering layer and not a trust boundary.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("attachments must be a list")
    if not raw:
        return []
    if len(raw) > MAX_ATTACHMENTS:
        raise AttachmentError(
            f"at most {MAX_ATTACHMENTS} files can be attached at once "
            f"({len(raw)} were sent)"
        )

    accepted: list[dict[str, Any]] = []
    total = 0
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise AttachmentError(f"attachment {index + 1} is not an object")
        name = str(entry.get("name") or "").strip() or f"attachment {index + 1}"
        mime = resolve_mime(entry.get("mime"), name)
        data = entry.get("data")
        if not isinstance(data, str) or not data:
            raise AttachmentError(f"{name} has no content")

        if mime.startswith("image/"):
            if mime not in IMAGE_MIME_TYPES:
                raise AttachmentError(
                    f"{name} is a {mime} image, which models do not accept. "
                    "Use PNG, JPEG, WebP or GIF."
                )
            size = len(_decode_image(data, name))
            total += size
            if size > MAX_ATTACHMENT_BYTES:
                raise AttachmentError(
                    f"{name} is {size // 1024}KB, over the "
                    f"{MAX_ATTACHMENT_BYTES // 1024}KB limit for one image"
                )
            accepted.append(
                {"name": name, "kind": "image", "mime": mime, "data": data}
            )
            continue

        if mime in TEXT_MIME_TYPES:
            text = _decode_text(data, name)
            total += len(text.encode("utf-8", "replace"))
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS]
            accepted.append({"name": name, "kind": "text", "mime": mime, "text": text})
            continue

        # The PDF check comes first, and it looks at the extension as well as
        # the declared type. A browser on Windows reports no type for many
        # files, so a PDF can arrive as `""` -- and falling through to the
        # unknown-type message below refuses it just as firmly while telling
        # the user the wrong thing about why.
        if mime == "application/pdf" or _extension_of(name) == ".pdf":
            raise AttachmentError(
                f"{name} is a PDF, which this endpoint cannot read inline. "
                "Copy the text out, or attach a screenshot of the page."
            )
        if not mime:
            raise AttachmentError(
                f"{name} has no type this can read. Attach an image "
                "(PNG, JPEG, WebP, GIF) or a text file."
            )
        raise AttachmentError(
            f"{name} is a {mime} file, which this endpoint cannot read inline. "
            "Attach an image (PNG, JPEG, WebP, GIF) or a text file."
        )

    if total > MAX_TOTAL_BYTES:
        raise AttachmentError(
            f"the attachments add up to {total // 1024}KB, over the "
            f"{MAX_TOTAL_BYTES // 1024}KB limit for one message"
        )
    return accepted


def _decode_text(data: str, name: str) -> str:
    """Text attachments arrive base64 too, so one wire shape covers both."""
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        # A frontend that read a text file as UTF-8 and sent it raw is a
        # plausible mistake, and refusing it outright would be unhelpful when
        # the text is sitting right there in the payload.
        if "<" in data and ">" in data:
            return data
        raise AttachmentError(f"{name} could not be read as text.") from exc
    return raw.decode("utf-8", "replace")


def build_parts(attachments: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """The content parts for one user message, in the order a person expects.

    The typed text comes first even when there are files, because that is the
    question and the files are its evidence. A message that opens with a wall
    of base64 has put the answer after the payload.
    """
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for item in attachments:
        if item["kind"] == "image":
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{item['mime']};base64,{item['data']}"
                    },
                }
            )
        else:
            parts.append(
                {
                    "type": "text",
                    "text": f"<file name=\"{item['name']}\">\n{item['text']}\n</file>",
                }
            )
    return parts


def summarise(attachments: list[dict[str, Any]]) -> str:
    """One line describing what was attached, for the transcript bubble.

    The window needs to show something after a reload -- the conversation is
    saved, but a message whose only content was an image comes back as a list
    of parts, and a bubble with no words in it looks like nothing was sent.
    """
    if not attachments:
        return ""
    names = ", ".join(item["name"] for item in attachments)
    noun = "file" if len(attachments) == 1 else "files"
    return f"Attached {len(attachments)} {noun}: {names}"


def strip_images(messages: list[Any]) -> list[dict[str, Any]]:
    """Messages as plain dicts, with base64 image parts left out.

    Every conversation is written to disk as ``[m.to_dict() for m in messages]``,
    and an `image_url` part carries its whole picture inline as base64. A user
    attachment is one file and the user chose it; a screenshot tool can fire
    several times in a turn, and at 1568px each is a megabyte of base64. Ten
    captures would make one saved chat larger than the entire rest of the store.

    So the pixels are dropped on the way to disk and replaced by a note saying
    one was here. The model still saw it: this runs when the turn is already
    over, and a screenshot is a picture of *now*, which would be misleading on a
    reload in any case -- the window the user had open then is not the one they
    have open now.

    Text parts and every other field are untouched, and a message with no image
    in it comes back byte for byte.
    """
    kept: list[dict[str, Any]] = []
    for message in messages:
        data = message.to_dict()
        content = data.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in content
        ):
            data["content"] = [
                part
                if not (isinstance(part, dict) and part.get("type") == "image_url")
                else {
                    "type": "text",
                    "text": "[an image was returned by a tool and is not kept in the saved conversation]",
                }
                for part in content
            ]
        kept.append(data)
    return kept
